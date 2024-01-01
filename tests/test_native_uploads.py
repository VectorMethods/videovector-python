"""Native resumable transfers never send API credentials to storage."""

import json
import re
import threading
import time

import httpx
import pytest

from videovector._config import ClientConfig
from videovector._exceptions import VideoVectorError
from videovector._http import AsyncHttpClient, SyncHttpClient
from videovector.resources.workflow import AsyncWorkflowResource, WorkflowResource

BASE = "https://api.example/api/v2"
JOB = BASE + "/workflow/attachments/job_1"
STORAGE = (
    "https://storage.googleapis.com/upload/storage/v1/b/media/o?uploadType=resumable&upload_id="
)


class Backend:
    def __init__(self, *, failed=False, destination=None, offset=0):
        self.failed, self.destination, self.offset = failed, destination, offset
        self.requests, self.files = [], []
        self.active = self.peak = 0
        self.lock = threading.Lock()

    def __call__(self, request):
        body = request.read()
        self.requests.append((request, body))
        if str(request.url) == BASE + "/workflow/attachments":
            assert request.headers["x-api-key"] == "account-secret"
            return httpx.Response(
                200,
                json={
                    "job_id": "job_1",
                    "status": "awaiting_upload",
                    "progress": {},
                    "upload": {
                        "url": JOB + "/files",
                        "complete_url": JOB + "/complete",
                        "token": "scoped-secret",
                    },
                },
            )
        if request.url.host == "storage.googleapis.com":
            assert "authorization" not in request.headers and "x-api-key" not in request.headers
            assert "x-private" not in request.headers
            assert request.method == "PUT" and len(body) == int(request.headers["content-length"])
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", request.headers["content-range"])
            assert match
            start, end, total = map(int, match.groups())
            assert len(body) == end - start + 1
            with self.lock:
                self.active += 1
                self.peak = max(self.peak, self.active)
            time.sleep(0.005)
            with self.lock:
                self.active -= 1
            return httpx.Response(
                500 if self.failed else 200 if end + 1 == total else 308,
                headers={"Range": f"bytes=0-{end}"},
            )
        assert request.headers["authorization"] == "Bearer scoped-secret"
        assert "x-api-key" not in request.headers and "x-private" not in request.headers
        if str(request.url) == JOB + "/files":
            file = json.loads(body)
            self.files.append(file)
            assert len(file["sample_sha256"]) == 64 and file["last_modified"] >= 0
            return httpx.Response(
                200,
                json={
                    "job": {"job_id": "job_1"},
                    "upload": {
                        "transport": "resumable",
                        "url": self.destination or STORAGE + file["file_id"],
                        "total_bytes": file["size_bytes"],
                        "offset": self.offset,
                        "chunk_size": 2,
                    },
                },
            )
        if str(request.url) == JOB + "/complete":
            assert len(json.loads(body)["file_ids"]) >= 1
        else:
            assert str(request.url) == JOB + "/files/complete" and json.loads(body)["file_id"]
        return httpx.Response(
            200,
            json={
                "job_id": "job_1",
                "status": "pending",
                "progress": {"total_files": len(self.files)},
            },
        )


def config():
    return ClientConfig(
        api_key="account-secret", base_url=BASE, custom_headers={"X-Private": "never-storage"}
    )


def files(tmp_path, count=1):
    result = []
    for index in range(count):
        path = tmp_path / f"clip{index}.mp4"
        path.write_bytes(b"video" * (index + 1))
        result.append(path)
    return result


def test_sync_native_batch_is_bounded_and_finalizes_once(tmp_path):
    backend = Backend()
    client = SyncHttpClient(config())
    client._client.close()
    client._client = httpx.Client(
        base_url=BASE, headers=client._default_headers(), transport=httpx.MockTransport(backend)
    )
    try:
        result = WorkflowResource(client).upload_files(files(tmp_path, 7), idempotency_key="same")
    finally:
        client.close()
    urls = [str(request.url) for request, _ in backend.requests]
    assert result.job_id == "job_1"
    assert urls.count(JOB + "/files") == 7 and urls.count(JOB + "/complete") == 1
    assert urls.count(JOB + "/files/complete") == 7
    assert 1 < backend.peak <= 3


@pytest.mark.asyncio
@pytest.mark.parametrize("single", [False, True])
async def test_async_native_resume_starts_at_confirmed_offset(tmp_path, single):
    backend = Backend(offset=2)

    async def handle(request):
        await request.aread()
        return backend(request)

    client = AsyncHttpClient(config())
    client._client = httpx.AsyncClient(
        base_url=BASE, headers=client._default_headers(), transport=httpx.MockTransport(handle)
    )
    try:
        resource = AsyncWorkflowResource(client)
        paths = files(tmp_path)
        result = await (
            resource.upload(paths[0], idempotency_key="same")
            if single
            else resource.upload_files(paths, idempotency_key="same")
        )
    finally:
        await client.close()
    assert result.job_id == "job_1"
    transfers = [
        (request.headers["content-range"], body)
        for request, body in backend.requests
        if request.method == "PUT"
    ]
    assert transfers == [("bytes 2-3/5", b"de"), ("bytes 4-4/5", b"o")]


@pytest.mark.parametrize(
    "options", [{"failed": True}, {"destination": "https://other.example/private-session"}]
)
def test_failed_native_transfer_never_falls_back_or_finalizes(tmp_path, options):
    backend = Backend(**options)
    client = SyncHttpClient(config())
    client._client.close()
    client._client = httpx.Client(
        base_url=BASE, headers=client._default_headers(), transport=httpx.MockTransport(backend)
    )
    try:
        with pytest.raises((ValueError, VideoVectorError)) as raised:
            WorkflowResource(client).upload_files(files(tmp_path), idempotency_key="same")
    finally:
        client.close()
    assert "private-session" not in str(raised.value)
    urls = [str(request.url) for request, _ in backend.requests]
    assert JOB + "/complete" not in urls and JOB + "/files/complete" not in urls


@pytest.mark.parametrize("as_string", [False, True])
def test_single_path_upload_uses_native_storage_without_multipart(tmp_path, as_string):
    backend = Backend()
    client = SyncHttpClient(config())
    client._client.close()
    client._client = httpx.Client(
        base_url=BASE, headers=client._default_headers(), transport=httpx.MockTransport(backend)
    )
    path = files(tmp_path)[0]
    try:
        result = WorkflowResource(client).upload(
            str(path) if as_string else path, index_name="Library", idempotency_key="same"
        )
    finally:
        client.close()
    assert result.job_id == "job_1"
    requests = backend.requests
    assert json.loads(requests[0][1]) == {"index_name": "Library"}
    assert requests[0][0].headers["idempotency-key"] == "same"
    assert len([request for request, _ in requests if str(request.url) == JOB + "/complete"]) == 1
    assert all(request.url.path != "/api/v2/workflow/upload" for request, _ in requests)
