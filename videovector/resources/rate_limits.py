"""
VideoVector SDK Rate Limits Resource.

Provides methods for querying and refreshing per-user rate-limit status.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .._types import RateLimitStatus

if TYPE_CHECKING:
    from .._http import AsyncHttpClient, SyncHttpClient


class RateLimitsResource:
    """Synchronous rate-limits resource."""

    def __init__(self, client: "SyncHttpClient") -> None:
        self._client = client

    def get_status(self) -> RateLimitStatus:
        """Get current rate-limit status."""
        response = self._client.get("/rate-limit/status")
        return RateLimitStatus.model_validate(response)

    def refresh(self) -> RateLimitStatus:
        """Refresh user rate-limit configuration and return current status."""
        response = self._client.post("/rate-limit/refresh")
        return RateLimitStatus.model_validate(response)


class AsyncRateLimitsResource:
    """Asynchronous rate-limits resource."""

    def __init__(self, client: "AsyncHttpClient") -> None:
        self._client = client

    async def get_status(self) -> RateLimitStatus:
        """Get current rate-limit status."""
        response = await self._client.get("/rate-limit/status")
        return RateLimitStatus.model_validate(response)

    async def refresh(self) -> RateLimitStatus:
        """Refresh user rate-limit configuration and return current status."""
        response = await self._client.post("/rate-limit/refresh")
        return RateLimitStatus.model_validate(response)
