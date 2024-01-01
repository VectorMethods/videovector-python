"""
VideoVector SDK Configuration.

Handles API key, base URL, timeout, and retry configuration.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal, Optional, Union, cast

AuthMode = Literal["api_key", "bearer"]
OAuthTokenProvider = Callable[[], str]
AsyncOAuthTokenProvider = Callable[[], Union[str, Awaitable[str]]]

DEFAULT_BASE_URL = "https://api.vectormethods.com/api/v2"
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_MAX_RETRY_DELAY = 300
RESERVED_CUSTOM_HEADERS = frozenset(
    {
        "accept",
        "authorization",
        "content-length",
        "content-type",
        "cookie",
        "host",
        "idempotency-key",
        "set-cookie",
        "transfer-encoding",
        "user-agent",
        "x-api-key",
        "x-idempotency-key",
    }
)


@dataclass
class ClientConfig:
    """Configuration for the VideoVector client."""

    api_key: Optional[str] = None
    bearer_token: Optional[str] = None
    base_url: str = DEFAULT_BASE_URL
    timeout: float = DEFAULT_TIMEOUT
    max_retries: int = DEFAULT_MAX_RETRIES
    max_retry_delay: int = DEFAULT_MAX_RETRY_DELAY
    custom_headers: dict[str, str] = field(default_factory=dict)
    auth_mode: Optional[AuthMode] = None
    oauth_token_provider: Optional[AsyncOAuthTokenProvider] = None

    def __post_init__(self) -> None:
        """Validate configuration values."""
        has_oauth_token_provider = self.oauth_token_provider is not None
        if self.oauth_token_provider is not None and not callable(self.oauth_token_provider):
            raise ValueError("oauth_token_provider must be callable.")

        if self.bearer_token and has_oauth_token_provider:
            raise ValueError(
                "Provide only one bearer credential source; set bearer_token or "
                "oauth_token_provider, not both."
            )

        if self.auth_mode is not None and self.auth_mode not in {"api_key", "bearer"}:
            raise ValueError("auth_mode must be either 'api_key' or 'bearer'.")

        if self.auth_mode == "api_key" and not self.api_key:
            raise ValueError("auth_mode='api_key' requires api_key to be set.")
        if self.auth_mode == "bearer" and not self.bearer_token and not has_oauth_token_provider:
            raise ValueError(
                "auth_mode='bearer' requires bearer_token or oauth_token_provider to be set."
            )

        if self.auth_mode is None:
            if self.api_key and (self.bearer_token or has_oauth_token_provider):
                raise ValueError(
                    "Provide only one authentication method; set api_key, bearer_token, or "
                    "oauth_token_provider."
                )
            if not self.api_key and not self.bearer_token and not has_oauth_token_provider:
                raise ValueError(
                    "Authentication is required. Provide api_key, bearer_token, or "
                    "oauth_token_provider."
                )

        if self.timeout <= 0:
            raise ValueError("timeout must be greater than 0.")
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0.")
        if self.max_retry_delay <= 0:
            raise ValueError("max_retry_delay must be greater than 0.")

        reserved = sorted(
            name for name in self.custom_headers if name.strip().lower() in RESERVED_CUSTOM_HEADERS
        )
        if reserved:
            raise ValueError(
                "custom_headers cannot override reserved headers: " + ", ".join(reserved)
            )

    @classmethod
    def from_env(
        cls,
        api_key: Optional[str] = None,
        bearer_token: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        max_retry_delay: Optional[int] = None,
        auth_mode: Optional[AuthMode] = None,
        custom_headers: Optional[dict[str, str]] = None,
        oauth_token_provider: Optional[AsyncOAuthTokenProvider] = None,
    ) -> "ClientConfig":
        """
        Create configuration from environment variables with optional overrides.

        Environment variables:
            VIDEO_VECTOR_API_KEY: API key for authentication
            VIDEO_VECTOR_BEARER_TOKEN: Static bearer token for authentication
            VIDEO_VECTOR_BASE_URL: Base URL for API (default: DEFAULT_BASE_URL)
            VIDEO_VECTOR_TIMEOUT: Request timeout in seconds (default: 60)
            VIDEO_VECTOR_MAX_RETRIES: Maximum retry attempts (default: 3)
            VIDEO_VECTOR_MAX_RETRY_DELAY: Maximum retry wait in seconds (default: 300)
        """
        explicit_credentials = (
            api_key is not None or bearer_token is not None or oauth_token_provider is not None
        )
        resolved_auth_mode_raw: Optional[str]
        if explicit_credentials:
            # Explicit constructor credentials are one coherent authentication
            # choice. Do not combine them with an unrelated ambient credential
            # or auth mode from the process environment.
            resolved_api_key = api_key
            resolved_bearer_token = bearer_token
            resolved_oauth_token_provider = oauth_token_provider
            resolved_auth_mode_raw = auth_mode
        else:
            resolved_api_key = os.environ.get("VIDEO_VECTOR_API_KEY")
            resolved_bearer_token = os.environ.get("VIDEO_VECTOR_BEARER_TOKEN")
            resolved_oauth_token_provider = None
            resolved_auth_mode_raw = auth_mode or os.environ.get("VIDEO_VECTOR_AUTH_MODE")
        if resolved_auth_mode_raw not in (None, "api_key", "bearer"):
            raise ValueError(
                "VIDEO_VECTOR_AUTH_MODE must be either 'api_key' or 'bearer' when set."
            )
        resolved_auth_mode = (
            cast(AuthMode, resolved_auth_mode_raw) if resolved_auth_mode_raw is not None else None
        )

        resolved_base_url = base_url or os.environ.get("VIDEO_VECTOR_BASE_URL") or DEFAULT_BASE_URL

        resolved_timeout = timeout
        if resolved_timeout is None:
            env_timeout = os.environ.get("VIDEO_VECTOR_TIMEOUT")
            resolved_timeout = float(env_timeout) if env_timeout else DEFAULT_TIMEOUT

        resolved_max_retries = max_retries
        if resolved_max_retries is None:
            env_retries = os.environ.get("VIDEO_VECTOR_MAX_RETRIES")
            resolved_max_retries = int(env_retries) if env_retries else DEFAULT_MAX_RETRIES

        resolved_max_retry_delay = max_retry_delay
        if resolved_max_retry_delay is None:
            env_max_retry_delay = os.environ.get("VIDEO_VECTOR_MAX_RETRY_DELAY")
            resolved_max_retry_delay = (
                int(env_max_retry_delay) if env_max_retry_delay else DEFAULT_MAX_RETRY_DELAY
            )

        return cls(
            api_key=resolved_api_key,
            bearer_token=resolved_bearer_token,
            oauth_token_provider=resolved_oauth_token_provider,
            base_url=resolved_base_url.rstrip("/"),
            timeout=resolved_timeout,
            max_retries=resolved_max_retries,
            max_retry_delay=resolved_max_retry_delay,
            auth_mode=resolved_auth_mode,
            custom_headers=custom_headers or {},
        )
