from __future__ import annotations

import asyncio
import io
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import Any, Optional

import httpx
import pytest

from videovector import BatchVideoSegmentsTarget, VideoVectorError
from videovector._config import ClientConfig
from videovector._http import AsyncHttpClient, SyncHttpClient, _get_retry_after
from videovector.resources.connectors import AsyncConnectorsResource, ConnectorsResource
from videovector.resources.videos import (
    AsyncVideosResource,
    VideosResource,
    _batch_segments_payload,
)


class _SyncResourceHttp:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def post(
        self,
        endpoint: str,
        *,
        json: Optional[dict[str, Any]] = None,
        data: Optional[dict[str, Any]] = None,
        files: Optional[dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        **_kwargs: Any,
    ) -> Any:
        self.calls.append(
            {
                "endpoint": endpoint,
                "json": json,
                "data": data,
                "files": files,
                "idempotency_key": idempotency_key,
            }
        )
        if endpoint == "/videos/batch/segments":
            payload = (json or {}).get("targets") or [
                {"video_id": video_id} for video_id in (json or {}).get("video_ids", [])
            ]
            return [
                {
                    "video_id": target["video_id"],
                    "run_id": target.get("run_id"),
                    "segments": [],
                }
                for target in payload
            ]
        if endpoint == "/videos/signed-url":
            return {
                "signed_url": "https://media.example.test/grant",
                "expires_at": "2026-07-18T12:00:00Z",
            }
        if endpoint == "/connectors/gcs":
            return {
                "connector_id": "conn-1",
                "name": "Archive",
                "provider": "gcs",
                "status": "active",
                "scopes": ["import"],
                "import_mode": "all",
            }
        raise AssertionError(f"unexpected endpoint: {endpoint}")


class _AsyncResourceHttp(_SyncResourceHttp):
    async def post(self, endpoint: str, **kwargs: Any) -> Any:  # type: ignore[override]
        return super().post(endpoint, **kwargs)


class _CountingBytesIO(io.BytesIO):
    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.read_count = 0
        self.name = "credentials.json"

    def read(self, size: int = -1) -> bytes:
        self.read_count += 1
        return super().read(size)


def test_batch_video_segment_targets_are_exported_and_run_scoped() -> None:
    http = _SyncResourceHttp()
    resource = VideosResource(http)  # type: ignore[arg-type]
    targets = [
        BatchVideoSegmentsTarget(video_id="video-1", run_id="run-1"),
        BatchVideoSegmentsTarget(video_id="video-2"),
    ]

    result = resource.batch_segments_for_targets(targets)

    assert http.calls[0]["json"] == {
        "targets": [
            {"video_id": "video-1", "run_id": "run-1"},
            {"video_id": "video-2"},
        ]
    }
    assert [item.run_id for item in result] == ["run-1", None]


def test_legacy_batch_segments_payload_is_preserved() -> None:
    http = _SyncResourceHttp()
    resource = VideosResource(http)  # type: ignore[arg-type]

    result = resource.batch_segments(["video-1", "video-2"])

    assert http.calls[0]["json"] == {"video_ids": ["video-1", "video-2"]}
    assert [item.video_id for item in result] == ["video-1", "video-2"]


def test_batch_segments_payload_rejects_ambiguous_or_empty_requests() -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        _batch_segments_payload(
            video_ids=["video-1"],
            targets=[BatchVideoSegmentsTarget(video_id="video-1")],
        )
    with pytest.raises(ValueError, match="mutually exclusive"):
        _batch_segments_payload(
            video_ids=[],
            targets=[BatchVideoSegmentsTarget(video_id="video-1")],
        )
    with pytest.raises(ValueError, match="must be provided"):
        _batch_segments_payload()
    with pytest.raises(ValueError, match="video_ids must not be empty"):
        _batch_segments_payload(video_ids=[])
    with pytest.raises(ValueError, match="targets must not be empty"):
        _batch_segments_payload(targets=[])


def test_signed_url_force_refresh_is_opt_in_and_explicit() -> None:
    http = _SyncResourceHttp()
    resource = VideosResource(http)  # type: ignore[arg-type]

    resource.get_signed_url("gs://bucket/object")
    resource.get_signed_url("gs://bucket/object", force_refresh=True)

    assert http.calls[0]["json"] == {"gcs_uri": "gs://bucket/object"}
    assert http.calls[1]["json"] == {
        "gcs_uri": "gs://bucket/object",
        "force_refresh": True,
    }


def test_async_batch_targets_and_signed_url_match_sync_contract() -> None:
    http = _AsyncResourceHttp()
    resource = AsyncVideosResource(http)  # type: ignore[arg-type]

    async def run() -> None:
        segments = await resource.batch_segments_for_targets(
            [BatchVideoSegmentsTarget(video_id="video-1", run_id="run-1")]
        )
        signed = await resource.get_signed_url(
            "gs://bucket/object",
            force_refresh=True,
        )
        assert segments[0].run_id == "run-1"
        assert signed.signed_url == "https://media.example.test/grant"

    asyncio.run(run())
    assert http.calls[0]["json"] == {"targets": [{"video_id": "video-1", "run_id": "run-1"}]}
    assert http.calls[1]["json"]["force_refresh"] is True


def test_gcs_credentials_are_snapshotted_once_as_immutable_bytes() -> None:
    http = _SyncResourceHttp()
    stream = _CountingBytesIO(b'{"type":"service_account"}')
    resource = ConnectorsResource(http)  # type: ignore[arg-type]

    resource.create_gcs(
        name="Archive",
        bucket="bucket",
        gcp_project_id="project",
        credentials_file=stream,
    )

    assert stream.read_count == 1
    filename, payload, media_type = http.calls[0]["files"]["credentials_file"]
    assert filename == "credentials.json"
    assert payload == b'{"type":"service_account"}'
    assert isinstance(payload, bytes)
    assert media_type == "application/json"
    assert stream.tell() == 0


def test_async_gcs_credentials_use_the_same_snapshot_contract() -> None:
    http = _AsyncResourceHttp()
    stream = _CountingBytesIO(b'{"type":"service_account"}')
    resource = AsyncConnectorsResource(http)  # type: ignore[arg-type]

    asyncio.run(
        resource.create_gcs(
            name="Archive",
            bucket="bucket",
            gcp_project_id="project",
            credentials_file=stream,
        )
    )

    assert stream.read_count == 1
    assert http.calls[0]["files"]["credentials_file"][1] == b'{"type":"service_account"}'


@pytest.mark.parametrize(
    "payload,expected",
    [
        (b"", "must not be empty"),
        (b"x" * (64 * 1024 + 1), "cannot exceed 64 KiB"),
    ],
)
def test_gcs_credential_size_is_fail_closed(payload: bytes, expected: str) -> None:
    http = _SyncResourceHttp()
    resource = ConnectorsResource(http)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match=expected):
        resource.create_gcs(
            name="Archive",
            bucket="bucket",
            gcp_project_id="project",
            credentials_file=io.BytesIO(payload),
        )
    assert http.calls == []


@pytest.mark.parametrize(
    "header",
    [
        "Authorization",
        "authorization",
        "X-API-Key",
        "x-api-key",
        "Content-Type",
        "IDEMPOTENCY-KEY",
        "User-Agent",
    ],
)
def test_reserved_custom_headers_are_rejected_case_insensitively(header: str) -> None:
    with pytest.raises(ValueError, match="reserved headers"):
        ClientConfig.from_env(
            api_key="api-key",
            custom_headers={header: "attacker-controlled"},
        )


def test_sync_and_async_default_headers_are_identical() -> None:
    config = ClientConfig.from_env(
        api_key="api-key",
        custom_headers={"X-Trace-Context": "trace-1"},
    )
    sync = SyncHttpClient(config)
    async_client = AsyncHttpClient(config)
    try:
        assert sync._default_headers() == async_client._default_headers()
    finally:
        sync.close()


def test_retry_after_supports_http_date_and_clamps_to_configured_maximum() -> None:
    now = datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)
    response = httpx.Response(
        429,
        headers={"Retry-After": format_datetime(now + timedelta(seconds=90), usegmt=True)},
    )

    assert _get_retry_after(response, max_delay=120, now=now) == 90
    assert _get_retry_after(response, max_delay=30, now=now) == 30


@pytest.mark.parametrize(
    "header,expected",
    [
        ("600", 120),
        ("-1", 0),
        ("invalid", 60),
    ],
)
def test_retry_after_delta_and_fallback_are_bounded(header: str, expected: int) -> None:
    response = httpx.Response(429, headers={"Retry-After": header})
    assert _get_retry_after(response, max_delay=120) == expected


def test_sync_multipart_retry_replays_identical_encoded_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bodies: list[bytes] = []
    content_types: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.read())
        content_types.append(request.headers["Content-Type"])
        if len(bodies) == 1:
            return httpx.Response(503, json={"error": {"message": "retry"}})
        return httpx.Response(201, json={"connector_id": "conn-1"})

    config = ClientConfig.from_env(
        api_key="api-key",
        base_url="https://api.example.test/api/v2",
        max_retries=1,
    )
    client = SyncHttpClient(config)
    client._client.close()
    client._client = httpx.Client(
        base_url=config.base_url,
        headers=client._default_headers(),
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr("time.sleep", lambda _delay: None)
    try:
        client.post(
            "/connectors/gcs",
            data={"name": "Archive"},
            files={
                "credentials_file": (
                    "credentials.json",
                    b'{"type":"service_account"}',
                    "application/json",
                )
            },
            idempotency_key="connector-create-gcs:stable",
        )
    finally:
        client.close()

    assert len(bodies) == 2
    assert bodies[0] == bodies[1]
    assert content_types[0] == content_types[1]
    assert b'{"type":"service_account"}' in bodies[0]


def test_async_multipart_retry_replays_identical_encoded_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bodies: list[bytes] = []
    content_types: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(await request.aread())
        content_types.append(request.headers["Content-Type"])
        if len(bodies) == 1:
            return httpx.Response(503, json={"error": {"message": "retry"}})
        return httpx.Response(201, json={"connector_id": "conn-1"})

    config = ClientConfig.from_env(
        api_key="api-key",
        base_url="https://api.example.test/api/v2",
        max_retries=1,
    )
    client = AsyncHttpClient(config)
    client._client = httpx.AsyncClient(
        base_url=config.base_url,
        headers=client._default_headers(),
        transport=httpx.MockTransport(handler),
    )

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", no_sleep)

    async def run() -> None:
        try:
            await client.post(
                "/connectors/gcs",
                data={"name": "Archive"},
                files={
                    "credentials_file": (
                        "credentials.json",
                        b'{"type":"service_account"}',
                        "application/json",
                    )
                },
                idempotency_key="connector-create-gcs:stable",
            )
        finally:
            await client.close()

    asyncio.run(run())
    assert len(bodies) == 2
    assert bodies[0] == bodies[1]
    assert content_types[0] == content_types[1]


def test_async_retry_wait_remains_cancellation_aware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "60"}, json={})

    config = ClientConfig.from_env(
        api_key="api-key",
        base_url="https://api.example.test/api/v2",
        max_retries=1,
    )
    client = AsyncHttpClient(config)
    client._client = httpx.AsyncClient(
        base_url=config.base_url,
        headers=client._default_headers(),
        transport=httpx.MockTransport(handler),
    )

    async def cancel_sleep(_delay: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr("asyncio.sleep", cancel_sleep)

    async def run() -> None:
        try:
            with pytest.raises(asyncio.CancelledError):
                await client.get("/indexes")
        finally:
            await client.close()

    asyncio.run(run())


def test_sync_fallback_retry_wait_is_clamped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise RuntimeError("synthetic transport failure")

    config = ClientConfig.from_env(
        api_key="api-key",
        base_url="https://api.example.test/api/v2",
        max_retries=1,
        max_retry_delay=1,
    )
    client = SyncHttpClient(config)
    client._client.close()
    client._client = httpx.Client(
        base_url=config.base_url,
        headers=client._default_headers(),
        transport=httpx.MockTransport(handler),
    )
    delays: list[float] = []
    monkeypatch.setattr("time.sleep", delays.append)
    try:
        with pytest.raises(VideoVectorError, match="Request failed"):
            client.get("/indexes")
    finally:
        client.close()

    assert delays == [1]


def test_async_fallback_retry_wait_is_clamped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise RuntimeError("synthetic transport failure")

    config = ClientConfig.from_env(
        api_key="api-key",
        base_url="https://api.example.test/api/v2",
        max_retries=1,
        max_retry_delay=1,
    )
    client = AsyncHttpClient(config)
    client._client = httpx.AsyncClient(
        base_url=config.base_url,
        headers=client._default_headers(),
        transport=httpx.MockTransport(handler),
    )
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("asyncio.sleep", record_sleep)

    async def run() -> None:
        try:
            with pytest.raises(VideoVectorError, match="Request failed"):
                await client.get("/indexes")
        finally:
            await client.close()

    asyncio.run(run())
    assert delays == [1]
