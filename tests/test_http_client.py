from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from videovector import __version__
from videovector._config import ClientConfig
from videovector._exceptions import ConnectionError
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
