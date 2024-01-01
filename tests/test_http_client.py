from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from videovector import __version__
from videovector._config import ClientConfig
from videovector._exceptions import (
    ConflictError,
    ConnectionError,
    ExternalServiceError,
    RateLimitError,
    VideoVectorError,
)
from videovector._http import AsyncHttpClient, SyncHttpClient


def test_sync_http_uses_api_key_header() -> None:
    cfg = ClientConfig.from_env(api_key="vv_test_api_key")
    client = SyncHttpClient(cfg)
    try:
        headers = dict(client._client.headers)
        assert headers.get("x-api-key") == "vv_test_api_key"
        assert "authorization" not in headers
    finally:
        client.close()


def test_sync_http_sets_user_agent_with_current_version() -> None:
    cfg = ClientConfig.from_env(api_key="vv_test_api_key")
    client = SyncHttpClient(cfg)
    try:
        headers = dict(client._client.headers)
        assert headers.get("user-agent") == f"videovector-python/{__version__}"
    finally:
        client.close()


def test_sync_http_uses_bearer_header() -> None:
    cfg = ClientConfig.from_env(bearer_token="bearer-token")
    client = SyncHttpClient(cfg)
    try:
        headers = dict(client._client.headers)
        assert headers.get("authorization") == "Bearer bearer-token"
        assert "x-api-key" not in headers
    finally:
        client.close()


def test_sync_http_prefers_auth_mode_when_both_credentials_present() -> None:
    cfg = ClientConfig.from_env(
        api_key="vv_test_api_key",
        bearer_token="bearer-token",
        auth_mode="api_key",
    )
    client = SyncHttpClient(cfg)
    try:
        headers = dict(client._client.headers)
        assert headers.get("x-api-key") == "vv_test_api_key"
        assert "authorization" not in headers
    finally:
        client.close()


def test_sync_multipart_upload_sets_form_content_type() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["content_type"] = request.headers.get("content-type", "")
        return httpx.Response(201, json={"video_id": "v1"})

    cfg = ClientConfig.from_env(api_key="vv_test_api_key", base_url="https://example.test/api/v2")
    client = SyncHttpClient(cfg)
    client._client.close()
    client._client = httpx.Client(
        base_url=cfg.base_url,
        headers=client._default_headers(),
        transport=httpx.MockTransport(handler),
    )

    try:
        client.post(
            "/videos/upload",
            data={"title": "Demo"},
            files={"file": ("demo.mp4", b"binary", "video/mp4")},
        )
    finally:
        client.close()

    assert captured["content_type"].startswith("multipart/form-data")
    assert "application/json" not in captured["content_type"]


def test_sync_binary_stream_is_authenticated_bounded_and_not_json_decoded() -> None:
    captured: dict[str, str] = {}
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        captured["authorization"] = request.headers.get("x-api-key", "")
        captured["path"] = request.url.path
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=b'{"valid":"bytes"}',
        )

    cfg = ClientConfig.from_env(
        api_key="vv_test_api_key",
        base_url="https://example.test/api/v2",
        max_retries=3,
    )
    client = SyncHttpClient(cfg)
    client._client.close()
    client._client = httpx.Client(
        base_url=cfg.base_url,
        headers=client._default_headers(),
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = b"".join(
            client.iter_bytes(
                "/exports/export_1/download",
                chunk_size=4,
                max_bytes=32,
            )
        )
    finally:
        client.close()

    assert payload == b'{"valid":"bytes"}'
    assert calls == 1
    assert captured == {
        "authorization": "vv_test_api_key",
        "path": "/api/v2/exports/export_1/download",
    }


def test_sync_binary_stream_rejects_content_length_above_limit_without_retry() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=b"0123456789",
        )

    cfg = ClientConfig.from_env(
        api_key="vv_test_api_key",
        base_url="https://example.test/api/v2",
        max_retries=3,
    )
    client = SyncHttpClient(cfg)
    client._client.close()
    client._client = httpx.Client(
        base_url=cfg.base_url,
        headers=client._default_headers(),
        transport=httpx.MockTransport(handler),
    )

    try:
        with pytest.raises(VideoVectorError) as exc_info:
            list(client.iter_bytes("/exports/export_1/download", max_bytes=9))
    finally:
        client.close()

    assert calls == 1
    assert exc_info.value.error_code == "download_size_limit_exceeded"


def test_sync_binary_stream_preserves_structured_rate_limit() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "60"},
            json={
                "error": {
                    "code": "resource_rate_quota_exceeded",
                    "message": "Export download quota exceeded",
                    "details": {"resource": "metadata_export_download_bytes_per_day"},
                }
            },
        )

    cfg = ClientConfig.from_env(
        api_key="vv_test_api_key",
        base_url="https://example.test/api/v2",
    )
    client = SyncHttpClient(cfg)
    client._client.close()
    client._client = httpx.Client(
        base_url=cfg.base_url,
        headers=client._default_headers(),
        transport=httpx.MockTransport(handler),
    )

    try:
        with pytest.raises(RateLimitError) as exc_info:
            list(client.iter_bytes("/exports/export_1/download", max_bytes=32))
    finally:
        client.close()

    assert exc_info.value.error_code == "resource_rate_quota_exceeded"
    assert exc_info.value.retry_after == 60


def test_sync_binary_stream_rejects_redirect_without_following_or_retrying() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            302,
            headers={"Location": "https://storage.example.test/unbounded"},
        )

    cfg = ClientConfig.from_env(
        api_key="vv_test_api_key",
        base_url="https://example.test/api/v2",
        max_retries=3,
    )
    client = SyncHttpClient(cfg)
    client._client.close()
    client._client = httpx.Client(
        base_url=cfg.base_url,
        headers=client._default_headers(),
        transport=httpx.MockTransport(handler),
    )

    try:
        with pytest.raises(VideoVectorError) as exc_info:
            list(client.iter_bytes("/exports/export_1/download", max_bytes=32))
    finally:
        client.close()

    assert calls == 1
    assert exc_info.value.error_code == "unexpected_download_status"
    assert exc_info.value.status_code == 302


@pytest.mark.parametrize("status_code", [204, 206])
def test_sync_binary_stream_rejects_non_full_success_status(
    status_code: int,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            headers={
                "Content-Type": "application/json",
                "Content-Length": "5",
            },
            content=b"short" if status_code == 206 else None,
        )

    cfg = ClientConfig.from_env(
        api_key="vv_test_api_key",
        base_url="https://example.test/api/v2",
    )
    client = SyncHttpClient(cfg)
    client._client.close()
    client._client = httpx.Client(
        base_url=cfg.base_url,
        headers=client._default_headers(),
        transport=httpx.MockTransport(handler),
    )

    try:
        with pytest.raises(VideoVectorError) as exc_info:
            list(client.iter_bytes("/exports/export_1/download", max_bytes=32))
    finally:
        client.close()

    assert exc_info.value.error_code == "unexpected_download_status"
    assert exc_info.value.status_code == status_code


@pytest.mark.parametrize(
    ("headers", "expected_error"),
    [
        ({"Content-Length": "5"}, "unexpected_download_content_type"),
        ({"Content-Type": "application/json"}, "missing_download_content_length"),
        (
            {
                "Content-Type": "application/json",
                "Content-Length": "5",
                "Content-Encoding": "gzip",
            },
            "unexpected_download_content_encoding",
        ),
    ],
)
def test_sync_binary_stream_requires_canonical_complete_response_headers(
    headers: dict[str, str],
    expected_error: str,
) -> None:
    class _Body(httpx.SyncByteStream):
        def __iter__(self) -> Any:
            yield b"short"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers=headers, stream=_Body())

    cfg = ClientConfig.from_env(
        api_key="vv_test_api_key",
        base_url="https://example.test/api/v2",
    )
    client = SyncHttpClient(cfg)
    client._client.close()
    client._client = httpx.Client(
        base_url=cfg.base_url,
        headers=client._default_headers(),
        transport=httpx.MockTransport(handler),
    )

    try:
        with pytest.raises(VideoVectorError) as exc_info:
            list(client.iter_bytes("/exports/export_1/download", max_bytes=32))
    finally:
        client.close()

    assert exc_info.value.error_code == expected_error


def test_sync_binary_stream_rejects_incomplete_declared_body() -> None:
    class _ShortBody(httpx.SyncByteStream):
        def __iter__(self) -> Any:
            yield b"short"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "Content-Length": "10",
                "Content-Type": "application/json",
            },
            stream=_ShortBody(),
        )

    cfg = ClientConfig.from_env(
        api_key="vv_test_api_key",
        base_url="https://example.test/api/v2",
    )
    client = SyncHttpClient(cfg)
    client._client.close()
    client._client = httpx.Client(
        base_url=cfg.base_url,
        headers=client._default_headers(),
        transport=httpx.MockTransport(handler),
    )

    try:
        with pytest.raises(VideoVectorError) as exc_info:
            list(client.iter_bytes("/exports/export_1/download", max_bytes=32))
    finally:
        client.close()

    assert exc_info.value.error_code == "download_incomplete"
    assert exc_info.value.details == {
        "expected_bytes": 10,
        "received_bytes": 5,
    }


def test_sync_post_without_idempotency_key_does_not_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = ClientConfig.from_env(api_key="vv_test_api_key", max_retries=3)
    client = SyncHttpClient(cfg)
    calls = {"count": 0}

    def fail_request(*args: Any, **kwargs: Any) -> httpx.Response:
        calls["count"] += 1
        request = httpx.Request("POST", "https://example.test/api/v2/prompt-runs/execute")
        raise httpx.ConnectError("boom", request=request)

    monkeypatch.setattr(client._client, "request", fail_request)
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)

    with pytest.raises(ConnectionError):
        client.post("/prompt-runs/execute", json={"prompt_id": "p"})

    client.close()
    assert calls["count"] == 1


def test_sync_post_with_idempotency_key_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = ClientConfig.from_env(api_key="vv_test_api_key", max_retries=2)
    client = SyncHttpClient(cfg)
    calls = {"count": 0}

    def fail_request(*args: Any, **kwargs: Any) -> httpx.Response:
        calls["count"] += 1
        request = httpx.Request("POST", "https://example.test/api/v2/prompt-runs/execute")
        raise httpx.ConnectError("boom", request=request)

    monkeypatch.setattr(client._client, "request", fail_request)
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)

    with pytest.raises(ConnectionError):
        client.post(
            "/prompt-runs/execute",
            json={"prompt_id": "p"},
            idempotency_key="req-1",
        )

    client.close()
    assert calls["count"] == 3


def test_sync_rate_limit_preserves_structured_quota_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = ClientConfig.from_env(api_key="vv_test_api_key", max_retries=0)
    client = SyncHttpClient(cfg)

    def rate_limited(*args: Any, **kwargs: Any) -> httpx.Response:
        request = httpx.Request("POST", "https://example.test/api/v2/videos")
        return httpx.Response(
            429,
            headers={"Retry-After": "42"},
            json={
                "error": {
                    "code": "resource_rate_quota_exceeded",
                    "message": "Resource quota exceeded",
                    "details": {
                        "resource": "ingested_bytes_per_day",
                        "reset_time": "2026-07-17T00:00:00+00:00",
                    },
                }
            },
            request=request,
        )

    monkeypatch.setattr(client._client, "request", rate_limited)

    with pytest.raises(RateLimitError) as exc_info:
        client.post("/videos", json={"title": "demo"})

    client.close()
    assert exc_info.value.error_code == "resource_rate_quota_exceeded"
    assert exc_info.value.details == {
        "resource": "ingested_bytes_per_day",
        "reset_time": "2026-07-17T00:00:00+00:00",
    }
    assert exc_info.value.retry_after == 42


def test_sync_rate_limit_preserves_final_structured_contract_after_safe_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = ClientConfig.from_env(api_key="vv_test_api_key", max_retries=1)
    client = SyncHttpClient(cfg)
    calls = {"count": 0}

    def rate_limited(*args: Any, **kwargs: Any) -> httpx.Response:
        calls["count"] += 1
        request = httpx.Request("GET", "https://example.test/api/v2/indexes")
        return httpx.Response(
            429,
            headers={"Retry-After": "0"},
            json={
                "error": {
                    "code": (
                        "first_rate_limit"
                        if calls["count"] == 1
                        else "resource_rate_quota_exceeded"
                    ),
                    "message": "Resource quota exceeded",
                    "details": {"attempt": calls["count"]},
                }
            },
            request=request,
        )

    monkeypatch.setattr(client._client, "request", rate_limited)
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)

    try:
        with pytest.raises(RateLimitError) as exc_info:
            client.get("/indexes")
    finally:
        client.close()

    assert calls["count"] == 2
    assert exc_info.value.error_code == "resource_rate_quota_exceeded"
    assert exc_info.value.details == {"attempt": 2}
    assert exc_info.value.retry_after == 0


def test_sync_persistent_resource_quota_maps_to_structured_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = ClientConfig.from_env(api_key="vv_test_api_key", max_retries=0)
    client = SyncHttpClient(cfg)

    def quota_exceeded(*args: Any, **kwargs: Any) -> httpx.Response:
        request = httpx.Request("POST", "https://example.test/api/v2/indexes")
        return httpx.Response(
            409,
            json={
                "error": {
                    "code": "resource_quota_exceeded",
                    "message": "Resource quota exceeded",
                    "details": {
                        "resource": "indexes",
                        "limit": 5,
                        "used": 5,
                        "reserved": 0,
                    },
                }
            },
            request=request,
        )

    monkeypatch.setattr(client._client, "request", quota_exceeded)

    try:
        with pytest.raises(ConflictError) as exc_info:
            client.post("/indexes", json={"name": "Blocked"})
    finally:
        client.close()

    assert exc_info.value.error_code == "resource_quota_exceeded"
    assert exc_info.value.details == {
        "resource": "indexes",
        "limit": 5,
        "used": 5,
        "reserved": 0,
    }


def test_async_multipart_upload_sets_form_content_type() -> None:
    captured: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["content_type"] = request.headers.get("content-type", "")
        return httpx.Response(201, json={"video_id": "v1"})

    cfg = ClientConfig.from_env(api_key="vv_test_api_key", base_url="https://example.test/api/v2")
    client = AsyncHttpClient(cfg)
    async_client = httpx.AsyncClient(
        base_url=cfg.base_url,
        headers=client._default_headers(),
        transport=httpx.MockTransport(handler),
    )

    async def ensure_client() -> httpx.AsyncClient:
        return async_client

    client._client = async_client
    client._ensure_client = ensure_client  # type: ignore[assignment]

    async def _run() -> None:
        try:
            await client.post(
                "/videos/upload",
                data={"title": "Demo"},
                files={"file": ("demo.mp4", b"binary", "video/mp4")},
            )
        finally:
            await client.close()

    asyncio.run(_run())

    assert captured["content_type"].startswith("multipart/form-data")


def test_async_binary_stream_is_authenticated_bounded_and_not_retried() -> None:
    calls = 0
    captured: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        captured["authorization"] = request.headers.get("authorization", "")
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=b"binary-export",
        )

    cfg = ClientConfig.from_env(
        bearer_token="bearer-token",
        base_url="https://example.test/api/v2",
        max_retries=3,
    )
    client = AsyncHttpClient(cfg)
    async_client = httpx.AsyncClient(
        base_url=cfg.base_url,
        headers=client._default_headers(),
        transport=httpx.MockTransport(handler),
    )
    client._client = async_client

    async def _run() -> bytes:
        chunks = []
        try:
            async for chunk in client.iter_bytes(
                "/exports/export_1/download",
                chunk_size=3,
                max_bytes=32,
            ):
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            await client.close()

    assert asyncio.run(_run()) == b"binary-export"
    assert calls == 1
    assert captured["authorization"] == "Bearer bearer-token"


def test_async_binary_stream_rejects_partial_success_response() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            206,
            headers={"Content-Type": "application/json"},
            content=b"partial",
        )

    cfg = ClientConfig.from_env(
        api_key="vv_test_api_key",
        base_url="https://example.test/api/v2",
    )
    client = AsyncHttpClient(cfg)
    client._client = httpx.AsyncClient(
        base_url=cfg.base_url,
        headers=client._default_headers(),
        transport=httpx.MockTransport(handler),
    )

    async def _run() -> VideoVectorError:
        try:
            with pytest.raises(VideoVectorError) as exc_info:
                async for _chunk in client.iter_bytes(
                    "/exports/export_1/download",
                    max_bytes=32,
                ):
                    pass
            return exc_info.value
        finally:
            await client.close()

    error = asyncio.run(_run())
    assert error.error_code == "unexpected_download_status"
    assert error.status_code == 206


def test_async_post_without_idempotency_key_does_not_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = ClientConfig.from_env(api_key="vv_test_api_key", max_retries=3)
    client = AsyncHttpClient(cfg)
    calls = {"count": 0}

    async def fail_request(*args: Any, **kwargs: Any) -> httpx.Response:
        calls["count"] += 1
        request = httpx.Request("POST", "https://example.test/api/v2/prompt-runs/execute")
        raise httpx.ConnectError("boom", request=request)

    async_client = httpx.AsyncClient(base_url=cfg.base_url, headers=client._default_headers())
    monkeypatch.setattr(async_client, "request", fail_request)

    async def ensure_client() -> httpx.AsyncClient:
        return async_client

    client._client = async_client
    client._ensure_client = ensure_client  # type: ignore[assignment]

    async def _run() -> None:
        with pytest.raises(ConnectionError):
            await client.post("/prompt-runs/execute", json={"prompt_id": "p"})
        await client.close()

    asyncio.run(_run())
    assert calls["count"] == 1


def test_async_post_with_idempotency_key_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = ClientConfig.from_env(api_key="vv_test_api_key", max_retries=2)
    client = AsyncHttpClient(cfg)
    calls = {"count": 0}

    async def fail_request(*args: Any, **kwargs: Any) -> httpx.Response:
        calls["count"] += 1
        request = httpx.Request("POST", "https://example.test/api/v2/prompt-runs/execute")
        raise httpx.ConnectError("boom", request=request)

    async_client = httpx.AsyncClient(base_url=cfg.base_url, headers=client._default_headers())
    monkeypatch.setattr(async_client, "request", fail_request)

    async def ensure_client() -> httpx.AsyncClient:
        return async_client

    client._client = async_client
    client._ensure_client = ensure_client  # type: ignore[assignment]

    async def _run() -> None:
        with pytest.raises(ConnectionError):
            await client.post(
                "/prompt-runs/execute",
                json={"prompt_id": "p"},
                idempotency_key="req-1",
            )
        await client.close()

    asyncio.run(_run())
    assert calls["count"] == 3


def test_async_rate_limit_preserves_structured_llm_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = ClientConfig.from_env(api_key="vv_test_api_key", max_retries=0)
    client = AsyncHttpClient(cfg)

    async def rate_limited(*args: Any, **kwargs: Any) -> httpx.Response:
        request = httpx.Request("POST", "https://example.test/api/v2/chat/sessions/s1/turns")
        return httpx.Response(
            429,
            headers={"Retry-After": "60"},
            json={
                "error": {
                    "code": "llm_daily_budget_exceeded",
                    "message": "Daily LLM budget exceeded",
                    "details": {"reset_time": "2026-07-17T00:00:00+00:00"},
                }
            },
            request=request,
        )

    async_client = httpx.AsyncClient(base_url=cfg.base_url, headers=client._default_headers())
    monkeypatch.setattr(async_client, "request", rate_limited)

    async def ensure_client() -> httpx.AsyncClient:
        return async_client

    client._client = async_client
    client._ensure_client = ensure_client  # type: ignore[assignment]

    async def _run() -> RateLimitError:
        try:
            with pytest.raises(RateLimitError) as exc_info:
                await client.post("/chat/sessions/s1/turns", json={"message": "hello"})
            return exc_info.value
        finally:
            await client.close()

    error = asyncio.run(_run())
    assert error.error_code == "llm_daily_budget_exceeded"
    assert error.details == {"reset_time": "2026-07-17T00:00:00+00:00"}
    assert error.retry_after == 60


def test_async_rate_limit_preserves_final_structured_contract_after_safe_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = ClientConfig.from_env(api_key="vv_test_api_key", max_retries=1)
    client = AsyncHttpClient(cfg)
    calls = {"count": 0}

    async def rate_limited(*args: Any, **kwargs: Any) -> httpx.Response:
        calls["count"] += 1
        request = httpx.Request("POST", "https://example.test/api/v2/chat/sessions/s1/turns")
        return httpx.Response(
            429,
            headers={"Retry-After": "0"},
            json={
                "error": {
                    "code": (
                        "first_rate_limit" if calls["count"] == 1 else "llm_daily_budget_exceeded"
                    ),
                    "message": "Daily LLM budget exceeded",
                    "details": {"attempt": calls["count"]},
                }
            },
            request=request,
        )

    async_client = httpx.AsyncClient(base_url=cfg.base_url, headers=client._default_headers())
    monkeypatch.setattr(async_client, "request", rate_limited)

    async def no_sleep(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", no_sleep)

    async def ensure_client() -> httpx.AsyncClient:
        return async_client

    client._client = async_client
    client._ensure_client = ensure_client  # type: ignore[assignment]

    async def _run() -> RateLimitError:
        try:
            with pytest.raises(RateLimitError) as exc_info:
                await client.post(
                    "/chat/sessions/s1/turns",
                    json={"message": "hello"},
                    idempotency_key="request-1",
                )
            return exc_info.value
        finally:
            await client.close()

    error = asyncio.run(_run())
    assert calls["count"] == 2
    assert error.error_code == "llm_daily_budget_exceeded"
    assert error.details == {"attempt": 2}
    assert error.retry_after == 0


def test_async_global_llm_guard_maps_to_structured_service_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = ClientConfig.from_env(api_key="vv_test_api_key", max_retries=0)
    client = AsyncHttpClient(cfg)

    async def budget_guard_open(*args: Any, **kwargs: Any) -> httpx.Response:
        request = httpx.Request("POST", "https://example.test/api/v2/prompts/generate")
        return httpx.Response(
            503,
            json={
                "error": {
                    "code": "llm_budget_guard_open",
                    "message": "Public LLM generation is temporarily unavailable",
                }
            },
            request=request,
        )

    async_client = httpx.AsyncClient(base_url=cfg.base_url, headers=client._default_headers())
    monkeypatch.setattr(async_client, "request", budget_guard_open)

    async def ensure_client() -> httpx.AsyncClient:
        return async_client

    client._client = async_client
    client._ensure_client = ensure_client  # type: ignore[assignment]

    async def _run() -> ExternalServiceError:
        try:
            with pytest.raises(ExternalServiceError) as exc_info:
                await client.post("/prompts/generate", json={"instruction": "summarize"})
            return exc_info.value
        finally:
            await client.close()

    error = asyncio.run(_run())
    assert error.error_code == "llm_budget_guard_open"
    assert error.status_code == 503
    assert error.details == {}


def test_async_http_prefers_auth_mode_when_both_credentials_present() -> None:
    cfg = ClientConfig.from_env(
        api_key="vv_test_api_key",
        bearer_token="bearer-token",
        auth_mode="bearer",
    )
    client = AsyncHttpClient(cfg)
    headers = client._default_headers()
    assert headers.get("Authorization") == "Bearer bearer-token"
    assert "X-API-Key" not in headers


def test_async_http_sets_user_agent_with_current_version() -> None:
    cfg = ClientConfig.from_env(api_key="vv_test_api_key")
    client = AsyncHttpClient(cfg)
    headers = client._default_headers()
    assert headers.get("User-Agent") == f"videovector-python/{__version__}"
