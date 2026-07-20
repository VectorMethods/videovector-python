"""
VideoVector SDK Exports Resource.

Provides methods for exporting metadata from indexes and prompt runs.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    BinaryIO,
    Dict,
    Iterator,
    List,
    Optional,
    Union,
)
from urllib.parse import parse_qsl, quote, urlencode, urlsplit
from uuid import uuid4

from pydantic import ValidationError as PydanticValidationError

from .._exceptions import VideoVectorError
from .._types import Export, ExportCreateResult, ExportDownloadUrlResult

if TYPE_CHECKING:
    from .._http import AsyncHttpClient, SyncHttpClient


# The API never emits an export artifact above 64 MiB. Keep the client-side
# streaming ceiling aligned so a malformed or misrouted response cannot turn an
# authenticated export download into an unexpectedly large local/network read.
DEFAULT_EXPORT_DOWNLOAD_MAX_BYTES = 64 * 1024 * 1024
DEFAULT_EXPORT_DOWNLOAD_CHUNK_SIZE = 1024 * 1024
MIN_EXPORT_DOWNLOAD_TOKEN_LENGTH = 32
MAX_EXPORT_DOWNLOAD_TOKEN_LENGTH = 2048
_EXPORT_DOWNLOAD_TOKEN_PATTERN = re.compile(r"v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\Z")


def _resolve_export_idempotency_key(idempotency_key: Optional[str]) -> str:
    """Ensure export creation requests can be retried safely."""
    candidate = (idempotency_key or "").strip()
    if candidate:
        return candidate
    return f"export-create:{uuid4().hex}"


def _invalid_export_download_url_response() -> VideoVectorError:
    """Build the one redacted error for every invalid capability response."""
    return VideoVectorError(
        "API returned an invalid export download URL response",
        status_code=502,
        error_code="invalid_export_download_url_response",
    )


def _parse_export_download_url_response(
    response: Any,
    *,
    expected_export_id: str,
    configured_base_url: str,
) -> Optional[str]:
    """Validate the security-sensitive mint response and bind it to the request."""
    result: Optional[ExportDownloadUrlResult] = None
    try:
        result = ExportDownloadUrlResult.model_validate(response)
    except PydanticValidationError:
        # Do not attach the response or the original validation exception: either
        # can contain the bearer credential this boundary is meant to protect.
        pass
    if result is None:
        raise _invalid_export_download_url_response()
    if result.export_id != expected_export_id:
        raise _invalid_export_download_url_response()
    if result.download_url is None:
        return None
    download_url = result.download_url.get_secret_value()
    if not _is_canonical_export_download_url(
        download_url,
        expected_export_id=expected_export_id,
        configured_base_url=configured_base_url,
    ):
        raise _invalid_export_download_url_response()
    return download_url


def _is_canonical_export_download_url(
    value: str,
    *,
    expected_export_id: str,
    configured_base_url: str,
) -> bool:
    """Return whether a minted capability exactly matches the trusted API origin."""
    if not value or value != value.strip():
        return False
    try:
        configured = urlsplit(configured_base_url)
        candidate = urlsplit(value)
        configured_port = 443 if configured.port is None else configured.port
        candidate_port = 443 if candidate.port is None else candidate.port
    except (TypeError, ValueError):
        return False

    if (
        configured.scheme.lower() != "https"
        or candidate.scheme.lower() != "https"
        or not configured.hostname
        or not candidate.hostname
        or configured.username is not None
        or configured.password is not None
        or configured.path != "/api/v2"
        or configured.query
        or configured.fragment
        or "?" in configured_base_url
        or "#" in configured_base_url
        or configured.netloc.endswith(":")
        or candidate.username is not None
        or candidate.password is not None
        or candidate.fragment
        or "#" in value
        or candidate.netloc.endswith(":")
        or configured_port <= 0
        or candidate_port <= 0
        or configured.hostname.lower() != candidate.hostname.lower()
        or configured_port != candidate_port
    ):
        return False

    expected_path = f"/api/v2/exports/{quote(expected_export_id, safe='')}/download"
    if candidate.path != expected_path:
        return False

    try:
        query_items = parse_qsl(
            candidate.query,
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=2,
        )
    except ValueError:
        return False
    if len(query_items) != 1 or query_items[0][0] != "token":
        return False
    token = query_items[0][1]
    if (
        not token
        or len(token) < MIN_EXPORT_DOWNLOAD_TOKEN_LENGTH
        or len(token) > MAX_EXPORT_DOWNLOAD_TOKEN_LENGTH
        or _EXPORT_DOWNLOAD_TOKEN_PATTERN.fullmatch(token) is None
    ):
        return False
    return candidate.query == urlencode({"token": token})


async def _to_thread_settled(callback: Any, *args: Any, **kwargs: Any) -> Any:
    """Let a started filesystem operation finish before propagating cancellation."""
    task = asyncio.create_task(asyncio.to_thread(callback, *args, **kwargs))
    cancellation: Optional[asyncio.CancelledError] = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            cancellation = cancellation or exc
    result = task.result()
    if cancellation is not None:
        raise cancellation
    return result


async def _open_binary_exclusive_settled(path: Path) -> BinaryIO:
    """Open a temporary file without leaking its handle if cancellation wins."""
    task = asyncio.create_task(asyncio.to_thread(path.open, "xb"))
    cancellation: Optional[asyncio.CancelledError] = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            cancellation = cancellation or exc
    handle = task.result()
    if cancellation is not None:
        await _to_thread_settled(handle.close)
        raise cancellation
    return handle


class ExportsResource:
    """
    Synchronous Exports resource.

    Provides methods for exporting metadata from indexes and prompt runs
    to JSON files for analytics, compliance, or data migration.

    Example:
        client = VideoVector(api_key="<VIDEO_VECTOR_API_KEY>")

        # Export all metadata from an index
        export = client.exports.create_index_export(
            index_id="idx_123"
        )

        # Wait for export to complete
        export = client.exports.wait_for_completion(export.export_id)

        # Download the export through the authenticated bounded API
        client.exports.download(export.export_id, "metadata.json")
        print(f"File size: {export.file_size_bytes} bytes")

        # Export specific prompt runs from an index
        export = client.exports.create_index_export(
            index_id="idx_123",
            prompt_run_ids=["run_abc", "run_def"]
        )

        # Export a single prompt run
        export = client.exports.create_prompt_run_export(
            run_id="run_123"
        )

        # List all exports
        exports = client.exports.list()
        for e in exports:
            print(f"{e.export_id}: {e.status}")
    """

    def __init__(self, client: "SyncHttpClient") -> None:
        self._client = client

    def create_index_export(
        self,
        index_id: str,
        *,
        prompt_run_ids: Optional[List[str]] = None,
        destination_connector_id: Optional[str] = None,
        destination_subpath: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> ExportCreateResult:
        """
        Create an export of index metadata.

        Exports all segments and their extracted metadata from an index.
        Optionally filter to specific prompt runs.

        Args:
            index_id: Index ID to export
            prompt_run_ids: Optional list of specific prompt run IDs to include.
                If not provided, exports all prompt runs.
            idempotency_key: Optional key for idempotent requests

        Returns:
            ExportCreateResult: Export job ID and initial status

        Raises:
            NotFoundError: If index doesn't exist
            ValidationError: If prompt_run_ids are invalid
        """
        body: Dict[str, Any] = {}
        if prompt_run_ids:
            body["prompt_run_ids"] = prompt_run_ids
        if destination_connector_id:
            body["destination_connector_id"] = destination_connector_id
        if destination_subpath:
            body["destination_subpath"] = destination_subpath

        response = self._client.post(
            f"/exports/index/{index_id}",
            json=body if body else None,
            idempotency_key=_resolve_export_idempotency_key(idempotency_key),
        )
        return ExportCreateResult.model_validate(response)

    def create_prompt_run_export(
        self,
        run_id: str,
        *,
        destination_connector_id: Optional[str] = None,
        destination_subpath: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> ExportCreateResult:
        """
        Create an export of prompt run metadata.

        Exports all segments and their extracted metadata from a specific
        prompt run.

        Args:
            run_id: Prompt run ID to export
            idempotency_key: Optional key for idempotent requests

        Returns:
            ExportCreateResult: Export job ID and initial status

        Raises:
            NotFoundError: If prompt run doesn't exist
        """
        body: Dict[str, Any] = {}
        if destination_connector_id:
            body["destination_connector_id"] = destination_connector_id
        if destination_subpath:
            body["destination_subpath"] = destination_subpath

        response = self._client.post(
            f"/exports/prompt-run/{run_id}",
            json=body if body else None,
            idempotency_key=_resolve_export_idempotency_key(idempotency_key),
        )
        return ExportCreateResult.model_validate(response)

    def retrieve(self, export_id: str) -> Export:
        """
        Retrieve an export by ID.

        Args:
            export_id: Export ID

        Returns:
            Export: Export details. ``download_url`` is an authenticated API
                endpoint when direct download is available; it is never a
                bearer credential.

        Raises:
            NotFoundError: If export doesn't exist
        """
        response = self._client.get(f"/exports/{export_id}")
        return Export.model_validate(response)

    def list(self, *, limit: int = 50) -> List[Export]:
        """
        List all exports.

        Args:
            limit: Maximum number of exports to return (1-100)

        Returns:
            List[Export]: Export jobs sorted by creation time
        """
        response = self._client.get("/exports", params={"limit": limit})
        return [Export.model_validate(e) for e in response]

    def wait_for_completion(
        self,
        export_id: str,
        *,
        poll_interval: float = 5.0,
        timeout: Optional[float] = None,
    ) -> Export:
        """
        Poll until an export completes.

        Args:
            export_id: Export ID
            poll_interval: Seconds between polls (default 5)
            timeout: Maximum seconds to wait (None for no timeout)

        Returns:
            Export: Completed export status. The model's ``download_url`` is
                an authenticated API endpoint, not a bearer credential.

        Raises:
            TimeoutError: If timeout is reached
            ProcessingError: If export fails
        """
        import time

        from .._exceptions import ProcessingError, TimeoutError

        start_time = time.time()

        while True:
            export = self.retrieve(export_id)

            if export.status in ("completed", "failed"):
                if export.status == "failed":
                    raise ProcessingError(
                        f"Export failed: {export.error_message}",
                        details={"export_id": export_id},
                    )
                return export

            if timeout and (time.time() - start_time) > timeout:
                raise TimeoutError(
                    f"Export did not complete within {timeout} seconds",
                    details={"export_id": export_id, "status": export.status},
                )

            time.sleep(poll_interval)

    def download_url(self, export_id: str) -> Optional[str]:
        """
        Mint a bounded bearer URL for an owned completed direct export.

        This performs an authenticated POST to the explicit mint endpoint.
        The returned URL is short-lived and must be treated as sensitive.
        ``Export.download_url`` has different semantics: status responses expose
        the authenticated download endpoint there and never include a bearer
        token. Prefer :meth:`download` or :meth:`iter_download` so authentication
        and local byte ceilings are applied directly by the SDK.

        Args:
            export_id: Export ID

        Returns:
            Optional[str]: Download URL if export is completed, None otherwise

        Raises:
            NotFoundError: If export doesn't exist
        """
        response = self._client.post(f"/exports/{export_id}/download-url")
        return _parse_export_download_url_response(
            response,
            expected_export_id=export_id,
            configured_base_url=self._client.base_url,
        )

    def iter_download(
        self,
        export_id: str,
        *,
        chunk_size: int = DEFAULT_EXPORT_DOWNLOAD_CHUNK_SIZE,
        max_bytes: int = DEFAULT_EXPORT_DOWNLOAD_MAX_BYTES,
    ) -> Iterator[bytes]:
        """
        Stream an owned completed export through the authenticated API.

        The request is deliberately not retried after streaming starts. The
        server generation-pins the object and enforces distributed egress
        limits; ``max_bytes`` adds a local fail-closed ceiling.
        """
        return self._client.iter_bytes(
            f"/exports/{export_id}/download",
            chunk_size=chunk_size,
            max_bytes=max_bytes,
        )

    def download(
        self,
        export_id: str,
        destination: Union[str, Path, BinaryIO],
        *,
        chunk_size: int = DEFAULT_EXPORT_DOWNLOAD_CHUNK_SIZE,
        max_bytes: int = DEFAULT_EXPORT_DOWNLOAD_MAX_BYTES,
    ) -> int:
        """
        Stream an owned completed export to a path or binary file object.

        Path destinations are written to a sibling temporary file and
        atomically replaced only after the response completes.

        Returns:
            Number of bytes written.
        """
        if hasattr(destination, "write"):
            return _write_sync_chunks(
                destination,  # type: ignore[arg-type]
                self.iter_download(
                    export_id,
                    chunk_size=chunk_size,
                    max_bytes=max_bytes,
                ),
            )

        destination_path = Path(destination)
        temporary_path = destination_path.with_name(f".{destination_path.name}.{uuid4().hex}.part")
        try:
            with temporary_path.open("xb") as handle:
                written = _write_sync_chunks(
                    handle,
                    self.iter_download(
                        export_id,
                        chunk_size=chunk_size,
                        max_bytes=max_bytes,
                    ),
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, destination_path)
            return written
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise


class AsyncExportsResource:
    """
    Asynchronous Exports resource.

    Provides async methods for exporting metadata.

    Example:
        async with AsyncVideoVector(api_key="<VIDEO_VECTOR_API_KEY>") as client:
            # Create an export
            export = await client.exports.create_index_export(
                index_id="idx_123"
            )

            # Wait for completion
            export = await client.exports.wait_for_completion(export.export_id)

            # Download through the authenticated bounded API
            await client.exports.download(export.export_id, "metadata.json")
    """

    def __init__(self, client: "AsyncHttpClient") -> None:
        self._client = client

    async def create_index_export(
        self,
        index_id: str,
        *,
        prompt_run_ids: Optional[List[str]] = None,
        destination_connector_id: Optional[str] = None,
        destination_subpath: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> ExportCreateResult:
        """Create an export of index metadata."""
        body: Dict[str, Any] = {}
        if prompt_run_ids:
            body["prompt_run_ids"] = prompt_run_ids
        if destination_connector_id:
            body["destination_connector_id"] = destination_connector_id
        if destination_subpath:
            body["destination_subpath"] = destination_subpath

        response = await self._client.post(
            f"/exports/index/{index_id}",
            json=body if body else None,
            idempotency_key=_resolve_export_idempotency_key(idempotency_key),
        )
        return ExportCreateResult.model_validate(response)

    async def create_prompt_run_export(
        self,
        run_id: str,
        *,
        destination_connector_id: Optional[str] = None,
        destination_subpath: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> ExportCreateResult:
        """Create an export of prompt run metadata."""
        body: Dict[str, Any] = {}
        if destination_connector_id:
            body["destination_connector_id"] = destination_connector_id
        if destination_subpath:
            body["destination_subpath"] = destination_subpath

        response = await self._client.post(
            f"/exports/prompt-run/{run_id}",
            json=body if body else None,
            idempotency_key=_resolve_export_idempotency_key(idempotency_key),
        )
        return ExportCreateResult.model_validate(response)

    async def retrieve(self, export_id: str) -> Export:
        """Retrieve an export by ID."""
        response = await self._client.get(f"/exports/{export_id}")
        return Export.model_validate(response)

    async def list(self, *, limit: int = 50) -> List[Export]:
        """List all exports."""
        response = await self._client.get("/exports", params={"limit": limit})
        return [Export.model_validate(e) for e in response]

    async def wait_for_completion(
        self,
        export_id: str,
        *,
        poll_interval: float = 5.0,
        timeout: Optional[float] = None,
    ) -> Export:
        """Poll until an export completes."""
        import asyncio
        import time

        from .._exceptions import ProcessingError, TimeoutError

        start_time = time.time()

        while True:
            export = await self.retrieve(export_id)

            if export.status in ("completed", "failed"):
                if export.status == "failed":
                    raise ProcessingError(
                        f"Export failed: {export.error_message}",
                        details={"export_id": export_id},
                    )
                return export

            if timeout and (time.time() - start_time) > timeout:
                raise TimeoutError(
                    f"Export did not complete within {timeout} seconds",
                    details={"export_id": export_id, "status": export.status},
                )

            await asyncio.sleep(poll_interval)

    async def download_url(self, export_id: str) -> Optional[str]:
        """Mint a bounded bearer URL; prefer authenticated streaming."""
        response = await self._client.post(f"/exports/{export_id}/download-url")
        return _parse_export_download_url_response(
            response,
            expected_export_id=export_id,
            configured_base_url=self._client.base_url,
        )

    async def iter_download(
        self,
        export_id: str,
        *,
        chunk_size: int = DEFAULT_EXPORT_DOWNLOAD_CHUNK_SIZE,
        max_bytes: int = DEFAULT_EXPORT_DOWNLOAD_MAX_BYTES,
    ) -> AsyncIterator[bytes]:
        """Stream an owned completed export without buffering it in memory."""
        async for chunk in self._client.iter_bytes(
            f"/exports/{export_id}/download",
            chunk_size=chunk_size,
            max_bytes=max_bytes,
        ):
            yield chunk

    async def download(
        self,
        export_id: str,
        destination: Union[str, Path, BinaryIO],
        *,
        chunk_size: int = DEFAULT_EXPORT_DOWNLOAD_CHUNK_SIZE,
        max_bytes: int = DEFAULT_EXPORT_DOWNLOAD_MAX_BYTES,
    ) -> int:
        """Asynchronously stream an export to a path or binary file object."""
        if hasattr(destination, "write"):
            written = 0
            async for chunk in self.iter_download(
                export_id,
                chunk_size=chunk_size,
                max_bytes=max_bytes,
            ):
                result = await _to_thread_settled(
                    destination.write,  # type: ignore[union-attr]
                    chunk,
                )
                if result is not None and int(result) != len(chunk):
                    raise OSError("Export destination accepted a partial write")
                written += len(chunk)
            return written

        destination_path = Path(destination)
        temporary_path = destination_path.with_name(f".{destination_path.name}.{uuid4().hex}.part")
        try:
            handle = await _open_binary_exclusive_settled(temporary_path)
            try:
                written = 0
                async for chunk in self.iter_download(
                    export_id,
                    chunk_size=chunk_size,
                    max_bytes=max_bytes,
                ):
                    result = await _to_thread_settled(handle.write, chunk)
                    if result is not None and int(result) != len(chunk):
                        raise OSError("Export destination accepted a partial write")
                    written += len(chunk)
                await _to_thread_settled(handle.flush)
                await _to_thread_settled(os.fsync, handle.fileno())
            finally:
                await _to_thread_settled(handle.close)
            await _to_thread_settled(os.replace, temporary_path, destination_path)
            return written
        except BaseException:
            await _to_thread_settled(temporary_path.unlink, missing_ok=True)
            raise


def _write_sync_chunks(destination: BinaryIO, chunks: Iterator[bytes]) -> int:
    written = 0
    for chunk in chunks:
        result = destination.write(chunk)
        if result is not None and int(result) != len(chunk):
            raise OSError("Export destination accepted a partial write")
        written += len(chunk)
    return written
