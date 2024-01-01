from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from videovector import (
    AsyncVideoVector,
    AuthenticationError,
    VideoVector,
    VideoVectorError,
)
from videovector import (
    ConnectionError as VideoVectorConnectionError,
)
from videovector import (
    TimeoutError as VideoVectorTimeoutError,
)
from videovector._config import ClientConfig
from videovector._http import AsyncHttpClient, SyncHttpClient


def _sync_client(
    provider: Any,
    handler: Any,
    *,
    max_retries: int = 0,
) -> SyncHttpClient:
    config = ClientConfig.from_env(
        oauth_token_provider=provider,
        base_url="https://api.example.test/api/v2",
        max_retries=max_retries,
    )
    client = SyncHttpClient(config)
    client._client.close()
    client._client = httpx.Client(
        base_url=config.base_url,
        headers=client._default_headers(),
        transport=httpx.MockTransport(handler),
    )
    return client


async def _async_client(
    provider: Any,
    handler: Any,
    *,
    max_retries: int = 0,
) -> AsyncHttpClient:
    config = ClientConfig.from_env(
        oauth_token_provider=provider,
        base_url="https://api.example.test/api/v2",
        max_retries=max_retries,
    )
    client = AsyncHttpClient(config)
    client._client = httpx.AsyncClient(
        base_url=config.base_url,
        headers=client._default_headers(),
        transport=httpx.MockTransport(handler),
    )
    return client


def _assert_secret_not_retained(error: BaseException, secret: str) -> None:
    assert secret not in str(error)
    assert secret not in repr(error)
    assert secret not in repr(error.args)
    assert secret not in repr(getattr(error, "__dict__", {}))
    assert error.__cause__ is None
    assert error.__context__ is None
    traceback = error.__traceback__
    while traceback is not None:
        frame = traceback.tb_frame
        if frame.f_globals.get("__name__") == "videovector._http":
            assert secret not in repr(frame.f_locals)
        traceback = traceback.tb_next


def test_sync_oauth_provider_supplies_fresh_bearer_for_each_wire_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supplied = iter(["access-token-one", "access-token-two"])
    captured: list[str] = []

    def provider() -> str:
        return next(supplied)

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.headers.get("authorization", ""))
        if len(captured) == 1:
            return httpx.Response(503, json={"error": {"message": "retry"}})
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)
    client = _sync_client(provider, handler, max_retries=1)
    try:
        assert client.get("/indexes") == {"ok": True}
    finally:
        client.close()

    assert captured == ["Bearer access-token-one", "Bearer access-token-two"]


@pytest.mark.asyncio
async def test_async_oauth_provider_accepts_async_refresh_callable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supplied = iter(["async-access-one", "async-access-two"])
    captured: list[str] = []

    async def provider() -> str:
        await asyncio.sleep(0)
        return next(supplied)

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.headers.get("authorization", ""))
        if len(captured) == 1:
            return httpx.Response(503, json={"error": {"message": "retry"}})
        return httpx.Response(200, json={"ok": True})

    async def no_sleep(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    client = await _async_client(provider, handler, max_retries=1)
    try:
        assert await client.get("/indexes") == {"ok": True}
    finally:
        await client.close()

    assert captured == ["Bearer async-access-one", "Bearer async-access-two"]


def test_oauth_provider_authenticates_streaming_download() -> None:
    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.headers.get("authorization", ""))
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json", "Content-Length": "2"},
            content=b"{}",
        )

    client = _sync_client(lambda: "stream-access-token", handler)
    try:
        assert b"".join(client.iter_bytes("/exports/export_1/download", max_bytes=2)) == b"{}"
    finally:
        client.close()

    assert captured == ["Bearer stream-access-token"]


@pytest.mark.parametrize(
    "invalid_result",
    [
        None,
        "",
        "Bearer already-prefixed",
        "token with spaces",
        "token\nwith-newline",
        "x" * 16_385,
    ],
)
def test_oauth_provider_rejects_invalid_results_without_sending(
    invalid_result: object,
) -> None:
    requests = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json={"ok": True})

    client = _sync_client(lambda: invalid_result, handler)
    try:
        with pytest.raises(AuthenticationError) as exc_info:
            client.get("/indexes")
    finally:
        client.close()

    assert requests == 0
    assert exc_info.value.error_code == "oauth_token_provider_invalid_result"


def test_oauth_provider_failure_does_not_retain_secret_exception_text() -> None:
    secret = "provider-secret-that-must-not-escape"

    def provider() -> str:
        raise RuntimeError(secret)

    client = _sync_client(
        provider,
        lambda _request: httpx.Response(200, json={"ok": True}),
    )
    try:
        with pytest.raises(AuthenticationError) as exc_info:
            client.get("/indexes")
    finally:
        client.close()

    error = exc_info.value
    assert error.error_code == "oauth_token_provider_failed"
    assert secret not in str(error)
    assert secret not in repr(error)
    assert secret not in repr(error.args)
    assert error.__cause__ is None
    assert error.__context__ is None


def test_invalid_oauth_provider_result_is_absent_from_traceback_locals() -> None:
    secret = "invalid oauth provider secret"
    client = _sync_client(
        lambda: secret,
        lambda _request: httpx.Response(200, json={"ok": True}),
    )
    try:
        with pytest.raises(AuthenticationError) as exc_info:
            client.get("/indexes")
    finally:
        client.close()

    assert exc_info.value.error_code == "oauth_token_provider_invalid_result"
    _assert_secret_not_retained(exc_info.value, secret)


@pytest.mark.asyncio
async def test_async_oauth_provider_failure_does_not_retain_secret_exception_text() -> None:
    secret = "async-provider-secret-that-must-not-escape"

    async def provider() -> str:
        raise RuntimeError(secret)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    client = await _async_client(provider, handler)
    try:
        with pytest.raises(AuthenticationError) as exc_info:
            await client.get("/indexes")
    finally:
        await client.close()

    error = exc_info.value
    assert error.error_code == "oauth_token_provider_failed"
    assert secret not in str(error)
    assert secret not in repr(error)
    assert secret not in repr(error.args)
    assert error.__cause__ is None
    assert error.__context__ is None


def test_sync_client_rejects_async_oauth_provider_result() -> None:
    async def provider() -> str:
        return "async-only-token"

    client = _sync_client(
        provider,
        lambda _request: httpx.Response(200, json={"ok": True}),
    )
    try:
        with pytest.raises(AuthenticationError) as exc_info:
            client.get("/indexes")
    finally:
        client.close()

    assert exc_info.value.error_code == "oauth_token_provider_async_result"


def test_sync_transport_failure_does_not_retain_oauth_request() -> None:
    secret = "sync-transport-oauth-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = _sync_client(lambda: secret, handler)
    try:
        with pytest.raises(VideoVectorConnectionError) as exc_info:
            client.get("/indexes")
    finally:
        client.close()

    _assert_secret_not_retained(exc_info.value, secret)


def test_http_status_failure_does_not_retain_oauth_request() -> None:
    secret = "status-error-oauth-secret"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"message": "Authentication failed"}},
        )

    client = _sync_client(lambda: secret, handler)
    try:
        with pytest.raises(AuthenticationError) as exc_info:
            client.get("/indexes")
    finally:
        client.close()

    _assert_secret_not_retained(exc_info.value, secret)


@pytest.mark.asyncio
async def test_async_transport_failure_does_not_retain_oauth_request() -> None:
    secret = "async-transport-oauth-secret"

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client = await _async_client(lambda: secret, handler)
    try:
        with pytest.raises(VideoVectorTimeoutError) as exc_info:
            await client.get("/indexes")
    finally:
        await client.close()

    _assert_secret_not_retained(exc_info.value, secret)


def test_sync_stream_failure_does_not_retain_oauth_request() -> None:
    secret = "sync-stream-oauth-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = _sync_client(lambda: secret, handler)
    try:
        with pytest.raises(VideoVectorConnectionError) as exc_info:
            list(client.iter_bytes("/exports/export_1/download", max_bytes=8))
    finally:
        client.close()

    _assert_secret_not_retained(exc_info.value, secret)


@pytest.mark.asyncio
async def test_async_stream_failure_does_not_retain_oauth_request() -> None:
    secret = "async-stream-oauth-secret"

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = await _async_client(lambda: secret, handler)
    try:
        with pytest.raises(VideoVectorConnectionError) as exc_info:
            async for _chunk in client.iter_bytes(
                "/exports/export_1/download",
                max_bytes=8,
            ):
                pass
    finally:
        await client.close()

    _assert_secret_not_retained(exc_info.value, secret)


def test_generic_transport_failure_does_not_retain_provider_or_error_secret() -> None:
    oauth_secret = "generic-oauth-secret"
    exception_secret = "generic-handler-secret"

    def handler(_request: httpx.Request) -> httpx.Response:
        raise RuntimeError(exception_secret)

    client = _sync_client(lambda: oauth_secret, handler)
    try:
        with pytest.raises(VideoVectorError) as exc_info:
            client.get("/indexes")
    finally:
        client.close()

    _assert_secret_not_retained(exc_info.value, oauth_secret)
    _assert_secret_not_retained(exc_info.value, exception_secret)


def test_explicit_api_key_mode_never_invokes_oauth_provider() -> None:
    calls = 0

    def provider() -> str:
        nonlocal calls
        calls += 1
        return "ignored-access-token"

    client = VideoVector(
        api_key="vv_test_api_key",
        oauth_token_provider=provider,
        auth_mode="api_key",
    )
    try:
        headers = dict(client._http._client.headers)  # type: ignore[attr-defined]
    finally:
        client.close()

    assert headers.get("x-api-key") == "vv_test_api_key"
    assert "authorization" not in headers
    assert calls == 0


def test_explicit_bearer_mode_never_sends_ambient_api_key_with_provider() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(request.headers)
        return httpx.Response(200, json={"ok": True})

    config = ClientConfig.from_env(
        api_key="vv_test_api_key",
        oauth_token_provider=lambda: "oauth-access-token",
        auth_mode="bearer",
        base_url="https://api.example.test/api/v2",
    )
    client = SyncHttpClient(config)
    client._client.close()
    client._client = httpx.Client(
        base_url=config.base_url,
        headers=client._default_headers(),
        transport=httpx.MockTransport(handler),
    )
    try:
        assert client.get("/indexes") == {"ok": True}
    finally:
        client.close()

    assert captured.get("authorization") == "Bearer oauth-access-token"
    assert "x-api-key" not in captured


def test_oauth_provider_constructor_is_available_on_both_clients() -> None:
    sync_client = VideoVector(oauth_token_provider=lambda: "sync-token")
    async_client = AsyncVideoVector(oauth_token_provider=lambda: "async-token")
    try:
        assert sync_client._config.oauth_token_provider is not None  # type: ignore[attr-defined]
        assert async_client._config.oauth_token_provider is not None  # type: ignore[attr-defined]
    finally:
        sync_client.close()
        asyncio.run(async_client.close())
