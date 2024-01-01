from pathlib import Path

import pytest

from videovector._config import DEFAULT_BASE_URL, ClientConfig

CANONICAL_BASE_URL = "https://api.vectormethods.com/api/v2"
LEGACY_RAW_STAGE_BASE_URL = "https://playground-" + "api-stg-" + "udk7d32fva-uc.a.run.app/api/v2"


def test_config_accepts_api_key() -> None:
    cfg = ClientConfig.from_env(api_key="vv_test_api_key")
    assert cfg.api_key == "vv_test_api_key"
    assert cfg.bearer_token is None


def test_config_accepts_bearer_token() -> None:
    cfg = ClientConfig.from_env(bearer_token="bearer-token-test")
    assert cfg.bearer_token == "bearer-token-test"
    assert cfg.api_key is None


def test_config_accepts_oauth_token_provider() -> None:
    def provider() -> str:
        return "oauth-access-token"

    cfg = ClientConfig.from_env(oauth_token_provider=provider)
    assert cfg.oauth_token_provider is provider
    assert cfg.api_key is None
    assert cfg.bearer_token is None


def test_client_config_preserves_existing_positional_field_order() -> None:
    cfg = ClientConfig(
        "vv_test_api_key",
        None,
        "https://api.example.test/api/v2",
        45.0,
        2,
        120,
        {"X-Trace-Context": "trace-1"},
        "api_key",
    )

    assert cfg.base_url == "https://api.example.test/api/v2"
    assert cfg.timeout == 45.0
    assert cfg.oauth_token_provider is None


def test_from_env_preserves_existing_positional_argument_order() -> None:
    cfg = ClientConfig.from_env(
        "vv_test_api_key",
        None,
        "https://api.example.test/api/v2",
        45.0,
        2,
        120,
        "api_key",
        {"X-Trace-Context": "trace-1"},
    )

    assert cfg.base_url == "https://api.example.test/api/v2"
    assert cfg.timeout == 45.0
    assert cfg.oauth_token_provider is None


def test_config_uses_bearer_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIDEO_VECTOR_BEARER_TOKEN", "env-bearer")
    cfg = ClientConfig.from_env()
    assert cfg.bearer_token == "env-bearer"


def test_legacy_env_prefix_is_not_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    legacy_api_key_env = "VIDEO_" + "SEARCH_API_KEY"
    monkeypatch.setenv(legacy_api_key_env, "legacy-token")
    with pytest.raises(ValueError, match="Authentication is required"):
        ClientConfig.from_env()


def test_config_requires_auth() -> None:
    with pytest.raises(ValueError, match="Authentication is required"):
        ClientConfig.from_env()


def test_config_rejects_both_auth_modes() -> None:
    with pytest.raises(ValueError, match="Provide only one authentication method"):
        ClientConfig.from_env(api_key="vv_test_api_key", bearer_token="<VIDEO_VECTOR_BEARER_TOKEN>")


def test_config_rejects_static_bearer_and_oauth_provider() -> None:
    with pytest.raises(ValueError, match="only one bearer credential source"):
        ClientConfig.from_env(
            bearer_token="static-access-token",
            oauth_token_provider=lambda: "dynamic-access-token",
            auth_mode="bearer",
        )


def test_config_rejects_api_key_and_oauth_provider_without_auth_mode() -> None:
    with pytest.raises(ValueError, match="Provide only one authentication method"):
        ClientConfig.from_env(
            api_key="vv_test_api_key",
            oauth_token_provider=lambda: "oauth-access-token",
        )


def test_config_env_auth_mode_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIDEO_VECTOR_API_KEY", "vv_test_api_key")
    monkeypatch.setenv("VIDEO_VECTOR_AUTH_MODE", "invalid")
    with pytest.raises(ValueError, match="VIDEO_VECTOR_AUTH_MODE"):
        ClientConfig.from_env()


def test_config_allows_both_credentials_with_explicit_auth_mode() -> None:
    cfg = ClientConfig.from_env(
        api_key="vv_test_api_key",
        bearer_token="bearer-token-test",
        auth_mode="bearer",
    )
    assert cfg.auth_mode == "bearer"
    assert cfg.api_key == "vv_test_api_key"
    assert cfg.bearer_token == "bearer-token-test"


def test_explicit_oauth_provider_ignores_ambient_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIDEO_VECTOR_API_KEY", "ambient-api-key")
    monkeypatch.setenv("VIDEO_VECTOR_BEARER_TOKEN", "ambient-bearer")
    monkeypatch.setenv("VIDEO_VECTOR_AUTH_MODE", "api_key")

    def provider() -> str:
        return "oauth-access-token"

    cfg = ClientConfig.from_env(oauth_token_provider=provider)

    assert cfg.api_key is None
    assert cfg.bearer_token is None
    assert cfg.oauth_token_provider is provider
    assert cfg.auth_mode is None


def test_config_uses_verified_default_base_url() -> None:
    cfg = ClientConfig.from_env(api_key="vv_test_api_key")
    assert cfg.base_url == DEFAULT_BASE_URL
    assert DEFAULT_BASE_URL == CANONICAL_BASE_URL


def test_legacy_raw_stage_url_is_absent_from_repo_text() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    ignored_parts = {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
    }
    offenders: list[str] = []

    for path in repo_root.rglob("*"):
        if not path.is_file() or ignored_parts.intersection(path.parts):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if LEGACY_RAW_STAGE_BASE_URL in content:
            offenders.append(str(path.relative_to(repo_root)))

    assert offenders == []
