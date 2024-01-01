from __future__ import annotations

import pytest

from videovector import AsyncVideoVector, VideoVector


def test_sync_client_accepts_explicit_auth_mode_with_dual_credentials() -> None:
    client = VideoVector(
        api_key="vv_test_api_key",
        bearer_token="bearer-token",
        auth_mode="api_key",
    )
    try:
        headers = dict(client._http._client.headers)  # type: ignore[attr-defined]
        assert headers.get("x-api-key") == "vv_test_api_key"
        assert "authorization" not in headers
    finally:
        client.close()


def test_async_client_accepts_explicit_auth_mode_with_dual_credentials() -> None:
    client = AsyncVideoVector(
        api_key="vv_test_api_key",
        bearer_token="bearer-token",
        auth_mode="bearer",
    )
    headers = client._http._default_headers()  # type: ignore[attr-defined]
    assert headers.get("Authorization") == "Bearer bearer-token"
    assert "X-API-Key" not in headers


def test_client_rejects_dual_credentials_without_auth_mode() -> None:
    with pytest.raises(ValueError, match="Provide only one authentication method"):
        VideoVector(api_key="vv_test_api_key", bearer_token="bearer-token")
