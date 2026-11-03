"""Bounded local uploads through the shared native resumable session contract."""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, BinaryIO, Dict, Iterator, List, Union
from urllib.parse import quote

if TYPE_CHECKING:
    from .._http import AsyncHttpClient, SyncHttpClient


def local_files(paths: List[Union[str, Path]], key: str) -> List[Dict[str, Any]]:
    if not 1 <= len(paths) <= 8:
        raise ValueError("Provide between 1 and 8 local files")
    result = []
    for index, value in enumerate(paths):
        path = Path(value).expanduser().resolve(strict=True)
        stat = path.stat()
        if not path.is_file() or stat.st_size <= 0:
            raise ValueError("Upload source must be a nonempty regular file")
        result.append(
            {
                "file_id": hashlib.sha256(f"{key}\0{index}".encode()).hexdigest(),
                "file_name": path.name,
                "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                "size_bytes": stat.st_size,
                "path": path,
                "identity": (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns),
            }
        )
    return result


def validate_grant(
    client: Union["SyncHttpClient", "AsyncHttpClient"], job_id: str, grant: Dict[str, Any]
) -> None:
    prefix = client._config.base_url.rstrip("/") + "/workflow/attachments/" + quote(job_id, safe="")
    if (
        grant.get("url") != prefix + "/files"
        or grant.get("complete_url") != prefix + "/complete"
        or not isinstance(grant.get("token"), str)
        or not grant["token"]
    ):
        raise ValueError("Invalid attachment upload grant")


def verify_file(stream: BinaryIO, file: Dict[str, Any]) -> None:
    stat = os.fstat(stream.fileno())
    if (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns) != file["identity"]:
        raise ValueError("Upload source changed after preparation")


def descriptor(stream: BinaryIO, file: Dict[str, Any]) -> Dict[str, Any]:
    verify_file(stream, file)
    sample_size = 64 * 1024
    last = max(0, file["size_bytes"] - sample_size)
    digest = hashlib.sha256()
    for offset in dict.fromkeys((0, last // 2, last)):
        stream.seek(offset)
        sample = stream.read(min(sample_size, file["size_bytes"] - offset))
        if len(sample) != min(sample_size, file["size_bytes"] - offset):
            raise ValueError("Upload source changed while preparing")
        digest.update(sample)
    return {
        "file_id": file["file_id"],
        "file_name": file["file_name"],
        "content_type": file["mime_type"],
        "size_bytes": file["size_bytes"],
        "last_modified": file["identity"][3] // 1_000_000,
        "sample_sha256": digest.hexdigest(),
    }


def session_details(response: Dict[str, Any], size: int) -> Any:
    from .._http import _validate_storage_upload_url

    session = response.get("upload")
    if session is None:
        return None
    if (
        not isinstance(session, dict)
        or session.get("transport") != "resumable"
        or session.get("total_bytes") != size
        or (not isinstance(session.get("offset"), int) or isinstance(session.get("offset"), bool))
        or not 0 <= session["offset"] <= size
        or (
            not isinstance(session.get("chunk_size"), int)
            or isinstance(session.get("chunk_size"), bool)
        )
        or session["chunk_size"] <= 0
    ):
        raise ValueError("Invalid native upload session")
    _validate_storage_upload_url(session["url"])
    return session


def confirmed_offset(status: int, range_header: str, start: int, end: int, total: int) -> int:
    match = re.fullmatch(r"bytes=0-(\d+)", range_header)
    confirmed = (
        int(match[1]) + 1 if status == 308 and match else total if status in (200, 201) else 0
    )
    if not start < confirmed <= end:
        raise ValueError("Storage did not confirm uploaded bytes; resume the same job")
    return confirmed


def chunks(stream: BinaryIO, length: int) -> Iterator[bytes]:
    while length:
        chunk = stream.read(min(64 * 1024, length))
        if not chunk:
            raise ValueError("Upload source ended before its expected size")
        length -= len(chunk)
        yield chunk


async def async_chunks(stream: BinaryIO, length: int) -> AsyncIterator[bytes]:
    while length:
        chunk = await asyncio.to_thread(stream.read, min(64 * 1024, length))
        if not chunk:
            raise ValueError("Upload source ended before its expected size")
        length -= len(chunk)
        yield chunk


def upload_files(
    client: "SyncHttpClient", job: Dict[str, Any], files: List[Dict[str, Any]]
) -> Dict[str, Any]:
    grant = job.get("upload")
    if not grant:
        return job
    validate_grant(client, job["job_id"], grant)

    def upload(file: Dict[str, Any]) -> None:
        with file["path"].open("rb") as stream:
            prepared = client.attachment_request(
                grant["url"], grant["token"], json=descriptor(stream, file)
            )
            session = session_details(prepared, file["size_bytes"])
            if session:
                offset = session["offset"]
                while offset < file["size_bytes"]:
                    verify_file(stream, file)
                    end = min(
                        file["size_bytes"], offset + min(session["chunk_size"], 8 * 1024 * 1024)
                    )
                    stream.seek(offset)
                    status, header = client.upload_capability(
                        session["url"],
                        chunks(stream, end - offset),
                        end - offset,
                        f"bytes {offset}-{end - 1}/{file['size_bytes']}",
                    )
                    offset = confirmed_offset(status, header, offset, end, file["size_bytes"])
            verify_file(stream, file)
            client.attachment_request(
                grant["url"] + "/complete", grant["token"], json={"file_id": file["file_id"]}
            )

    with ThreadPoolExecutor(max_workers=min(3, len(files))) as executor:
        list(executor.map(upload, files))
    result: Dict[str, Any] = client.attachment_request(
        grant["complete_url"],
        grant["token"],
        json={"file_ids": [file["file_id"] for file in files]},
    )
    return result


async def async_upload_files(
    client: "AsyncHttpClient", job: Dict[str, Any], files: List[Dict[str, Any]]
) -> Dict[str, Any]:
    grant = job.get("upload")
    if not grant:
        return job
    validate_grant(client, job["job_id"], grant)
    pending = iter(files)

    async def worker() -> None:
        for file in pending:
            with file["path"].open("rb") as stream:
                manifest = await asyncio.to_thread(descriptor, stream, file)
                prepared = await client.attachment_request(
                    grant["url"], grant["token"], json=manifest
                )
                session = session_details(prepared, file["size_bytes"])
                if session:
                    offset = session["offset"]
                    while offset < file["size_bytes"]:
                        verify_file(stream, file)
                        end = min(
                            file["size_bytes"], offset + min(session["chunk_size"], 8 * 1024 * 1024)
                        )
                        stream.seek(offset)
                        status, header = await client.upload_capability(
                            session["url"],
                            async_chunks(stream, end - offset),
                            end - offset,
                            f"bytes {offset}-{end - 1}/{file['size_bytes']}",
                        )
                        offset = confirmed_offset(status, header, offset, end, file["size_bytes"])
                verify_file(stream, file)
                await client.attachment_request(
                    grant["url"] + "/complete", grant["token"], json={"file_id": file["file_id"]}
                )

    outcomes = await asyncio.gather(
        *(worker() for _ in range(min(3, len(files)))), return_exceptions=True
    )
    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            raise outcome
    result: Dict[str, Any] = await client.attachment_request(
        grant["complete_url"],
        grant["token"],
        json={"file_ids": [file["file_id"] for file in files]},
    )
    return result
