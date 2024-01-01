"""
VideoVector SDK Usage Resource.

Provides methods for usage metering and usage history retrieval.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional, Union

from .._types import CurrentUsage, UsageBreakdown, UsageDetail, UsageHistory, UsageMetricTypeInfo

if TYPE_CHECKING:
    from .._http import AsyncHttpClient, SyncHttpClient


DateInput = Union[datetime, str]


def _to_iso(value: Optional[DateInput]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value


class UsageResource:
    """Synchronous usage resource."""

    def __init__(self, client: "SyncHttpClient") -> None:
        self._client = client

    def get_current(self) -> CurrentUsage:
        """Get current billing-period usage."""
        response = self._client.get("/usage")
        return CurrentUsage.model_validate(response)

    def get_history(
        self,
        *,
        start_date: Optional[DateInput] = None,
        end_date: Optional[DateInput] = None,
        limit: int = 12,
    ) -> UsageHistory:
        """Get usage history by billing period."""
        response = self._client.get(
            "/usage/history",
            params={
                "start_date": _to_iso(start_date),
                "end_date": _to_iso(end_date),
                "limit": limit,
            },
        )
        return UsageHistory.model_validate(response)

    def get_details(
        self,
        *,
        metric_type: Optional[str] = None,
        start_date: Optional[DateInput] = None,
        end_date: Optional[DateInput] = None,
        limit: int = 100,
    ) -> List[UsageDetail]:
        """Get detailed usage events."""
        response = self._client.get(
            "/usage/details",
            params={
                "metric_type": metric_type,
                "start_date": _to_iso(start_date),
                "end_date": _to_iso(end_date),
                "limit": limit,
            },
        )
        return [UsageDetail.model_validate(item) for item in response]

    def get_breakdown(
        self,
        *,
        start_date: Optional[DateInput] = None,
        end_date: Optional[DateInput] = None,
    ) -> UsageBreakdown:
        """Get usage breakdown by metric type."""
        response = self._client.get(
            "/usage/breakdown",
            params={
                "start_date": _to_iso(start_date),
                "end_date": _to_iso(end_date),
            },
        )
        return UsageBreakdown.model_validate(response)

    def get_metric_types(self) -> List[UsageMetricTypeInfo]:
        """Get available usage metric types."""
        response = self._client.get("/usage/metric-types")
        return [UsageMetricTypeInfo.model_validate(item) for item in response]


class AsyncUsageResource:
    """Asynchronous usage resource."""

    def __init__(self, client: "AsyncHttpClient") -> None:
        self._client = client

    async def get_current(self) -> CurrentUsage:
        """Get current billing-period usage."""
        response = await self._client.get("/usage")
        return CurrentUsage.model_validate(response)

    async def get_history(
        self,
        *,
        start_date: Optional[DateInput] = None,
        end_date: Optional[DateInput] = None,
        limit: int = 12,
    ) -> UsageHistory:
        """Get usage history by billing period."""
        response = await self._client.get(
            "/usage/history",
            params={
                "start_date": _to_iso(start_date),
                "end_date": _to_iso(end_date),
                "limit": limit,
            },
        )
        return UsageHistory.model_validate(response)

    async def get_details(
        self,
        *,
        metric_type: Optional[str] = None,
        start_date: Optional[DateInput] = None,
        end_date: Optional[DateInput] = None,
        limit: int = 100,
    ) -> List[UsageDetail]:
        """Get detailed usage events."""
        response = await self._client.get(
            "/usage/details",
            params={
                "metric_type": metric_type,
                "start_date": _to_iso(start_date),
                "end_date": _to_iso(end_date),
                "limit": limit,
            },
        )
        return [UsageDetail.model_validate(item) for item in response]

    async def get_breakdown(
        self,
        *,
        start_date: Optional[DateInput] = None,
        end_date: Optional[DateInput] = None,
    ) -> UsageBreakdown:
        """Get usage breakdown by metric type."""
        response = await self._client.get(
            "/usage/breakdown",
            params={
                "start_date": _to_iso(start_date),
                "end_date": _to_iso(end_date),
            },
        )
        return UsageBreakdown.model_validate(response)

    async def get_metric_types(self) -> List[UsageMetricTypeInfo]:
        """Get available usage metric types."""
        response = await self._client.get("/usage/metric-types")
        return [UsageMetricTypeInfo.model_validate(item) for item in response]
