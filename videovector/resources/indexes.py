"""
VideoVector SDK Indexes Resource.

Provides methods for index (collection) management.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional
from uuid import uuid4

from .._pagination import (
    AsyncPage,
    SyncPage,
    _parse_paginated_response,
    _parse_paginated_response_async,
)
from .._types import Index, IndexDeletionResponse, PromptRun, Video

if TYPE_CHECKING:
    from .._http import AsyncHttpClient, SyncHttpClient


def _resolve_index_idempotency_key(idempotency_key: Optional[str]) -> str:
    candidate = (idempotency_key or "").strip()
    if candidate:
        return candidate
    return f"index-create:{uuid4().hex}"


class IndexesResource:
    """
    Synchronous Indexes resource.

    Provides methods for managing indexes (video collections).

    Example:
        client = VideoVector(api_key="<VIDEO_VECTOR_API_KEY>")

        # Create an index
        index = client.indexes.create(name="My Collection")

        # List all indexes
        indexes = client.indexes.list()

        # List videos in an index
        videos = client.indexes.list_videos("idx_123")
        for video in videos.auto_paging_iter():
            print(video.title)
    """

    def __init__(self, client: "SyncHttpClient") -> None:
        self._client = client

    def create(self, *, name: str, idempotency_key: Optional[str] = None) -> Index:
        """
        Create a new index.

        Args:
            name: Index name (1-255 characters)

        Returns:
            Index: Created index object

        Raises:
            ValidationError: If name is invalid
        """
        response = self._client.post(
            "/indexes",
            json={"name": name},
            idempotency_key=_resolve_index_idempotency_key(idempotency_key),
        )
        return Index.model_validate(response)

    def retrieve(self, index_id: str) -> Index:
        """
        Retrieve an index by ID.

        Args:
            index_id: Index ID

        Returns:
            Index: Index object

        Raises:
            NotFoundError: If index doesn't exist
        """
        response = self._client.get(f"/indexes/{index_id}")
        return Index.model_validate(response)

    def list(self, *, include_defaults: bool = True) -> List[Index]:
        """
        List all indexes accessible to the user.

        Args:
            include_defaults: Include shared demo indexes

        Returns:
            List[Index]: List of index objects
        """
        response = self._client.get(
            "/indexes",
            params={"include_defaults": include_defaults},
        )
        return [Index.model_validate(idx) for idx in response]

    def delete(self, index_id: str) -> IndexDeletionResponse:
        """
        Start or resume durable index deletion.

        Args:
            index_id: Index ID to delete

        Returns:
            IndexDeletionResponse: Durable deletion identity and progress

        Raises:
            NotFoundError: If index doesn't exist
            AuthorizationError: If admin scope is required
        """
        response = self._client.delete(f"/indexes/{index_id}")
        return IndexDeletionResponse.model_validate(response)

    def get_deletion(self, index_id: str) -> IndexDeletionResponse:
        """Retrieve durable deletion progress for an index."""

        response = self._client.get(f"/indexes/{index_id}/deletion")
        return IndexDeletionResponse.model_validate(response)

    def list_videos(
        self,
        index_id: str,
        *,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> SyncPage[Video]:
        """
        List videos in an index.

        Args:
            index_id: Index ID
            limit: Number of results per page (1-100)
            cursor: Pagination cursor

        Returns:
            SyncPage[Video]: Paginated videos
        """
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor

        response = self._client.get(f"/indexes/{index_id}/videos", params=params)
        return _parse_paginated_response(
            response=response,
            model=Video,
            client=self._client,
            endpoint=f"/indexes/{index_id}/videos",
            params={"limit": limit},
        )

    def list_prompt_runs(
        self,
        index_id: str,
        *,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> SyncPage[PromptRun]:
        """
        List prompt runs for an index.

        Args:
            index_id: Index ID
            limit: Number of results per page (1-100)
            cursor: Pagination cursor

        Returns:
            SyncPage[PromptRun]: Paginated prompt runs
        """
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor

        response = self._client.get(f"/indexes/{index_id}/prompt-runs", params=params)
        return _parse_paginated_response(
            response=response,
            model=PromptRun,
            client=self._client,
            endpoint=f"/indexes/{index_id}/prompt-runs",
            params={"limit": limit},
        )


class AsyncIndexesResource:
    """
    Asynchronous Indexes resource.

    Provides async methods for managing indexes (video collections).

    Example:
        async with AsyncVideoVector(api_key="<VIDEO_VECTOR_API_KEY>") as client:
            # Create an index
            index = await client.indexes.create(name="My Collection")

            # List videos
            videos = await client.indexes.list_videos("idx_123")
    """

    def __init__(self, client: "AsyncHttpClient") -> None:
        self._client = client

    async def create(self, *, name: str, idempotency_key: Optional[str] = None) -> Index:
        """Create a new index."""
        response = await self._client.post(
            "/indexes",
            json={"name": name},
            idempotency_key=_resolve_index_idempotency_key(idempotency_key),
        )
        return Index.model_validate(response)

    async def retrieve(self, index_id: str) -> Index:
        """Retrieve an index by ID."""
        response = await self._client.get(f"/indexes/{index_id}")
        return Index.model_validate(response)

    async def list(self, *, include_defaults: bool = True) -> List[Index]:
        """List all indexes accessible to the user."""
        response = await self._client.get(
            "/indexes",
            params={"include_defaults": include_defaults},
        )
        return [Index.model_validate(idx) for idx in response]

    async def delete(self, index_id: str) -> IndexDeletionResponse:
        """Start or resume durable index deletion."""
        response = await self._client.delete(f"/indexes/{index_id}")
        return IndexDeletionResponse.model_validate(response)

    async def get_deletion(self, index_id: str) -> IndexDeletionResponse:
        """Retrieve durable deletion progress for an index."""

        response = await self._client.get(f"/indexes/{index_id}/deletion")
        return IndexDeletionResponse.model_validate(response)

    async def list_videos(
        self,
        index_id: str,
        *,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> AsyncPage[Video]:
        """List videos in an index."""
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor

        response = await self._client.get(f"/indexes/{index_id}/videos", params=params)
        return _parse_paginated_response_async(
            response=response,
            model=Video,
            client=self._client,
            endpoint=f"/indexes/{index_id}/videos",
            params={"limit": limit},
        )

    async def list_prompt_runs(
        self,
        index_id: str,
        *,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> AsyncPage[PromptRun]:
        """List prompt runs for an index."""
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor

        response = await self._client.get(f"/indexes/{index_id}/prompt-runs", params=params)
        return _parse_paginated_response_async(
            response=response,
            model=PromptRun,
            client=self._client,
            endpoint=f"/indexes/{index_id}/prompt-runs",
            params={"limit": limit},
        )
