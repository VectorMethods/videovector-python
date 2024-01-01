"""
VideoVector SDK Pagination.

Provides cursor-based pagination iterators for sync and async contexts.
"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Generic,
    Iterator,
    List,
    Optional,
    Type,
    TypeVar,
)

from pydantic import BaseModel

if TYPE_CHECKING:
    from ._http import AsyncHttpClient, SyncHttpClient


T = TypeVar("T", bound=BaseModel)


class SyncPage(Generic[T]):
    """
    Synchronous paginated response.

    Provides iteration over items and automatic pagination.

    Example:
        page = client.videos.list(index_id="idx_123", limit=10)
        for video in page:
            print(video.title)

        # Or iterate through all pages
        for video in page.auto_paging_iter():
            print(video.title)
    """

    def __init__(
        self,
        data: List[T],
        model: Type[T],
        client: "SyncHttpClient",
        endpoint: str,
        params: dict[str, Any],
        has_more: bool = False,
        next_cursor: Optional[str] = None,
    ) -> None:
        self._data = data
        self._model = model
        self._client = client
        self._endpoint = endpoint
        self._params = params
        self._has_more = has_more
        self._next_cursor = next_cursor

    @property
    def data(self) -> List[T]:
        """Items in the current page."""
        return self._data

    @property
    def has_more(self) -> bool:
        """Whether more pages are available."""
        return self._has_more

    @property
    def next_cursor(self) -> Optional[str]:
        """Cursor for the next page, if available."""
        return self._next_cursor

    def __iter__(self) -> Iterator[T]:
        """Iterate over items in the current page only."""
        return iter(self._data)

    def __len__(self) -> int:
        """Number of items in the current page."""
        return len(self._data)

    def __getitem__(self, index: int) -> T:
        """Get item by index from current page."""
        return self._data[index]

    def next_page(self) -> Optional["SyncPage[T]"]:
        """Fetch the next page if available."""
        if not self._has_more or not self._next_cursor:
            return None

        params = {**self._params, "cursor": self._next_cursor}
        response = self._client.get(self._endpoint, params=params)

        return _parse_paginated_response(
            response=response,
            model=self._model,
            client=self._client,
            endpoint=self._endpoint,
            params=self._params,
        )

    def auto_paging_iter(self) -> Iterator[T]:
        """
        Iterate through all items across all pages.

        Automatically fetches subsequent pages as needed.
        """
        page: Optional[SyncPage[T]] = self
        while page is not None:
            for item in page.data:
                yield item
            page = page.next_page()


class AsyncPage(Generic[T]):
    """
    Asynchronous paginated response.

    Provides async iteration over items and automatic pagination.

    Example:
        page = await client.videos.list(index_id="idx_123", limit=10)
        async for video in page:
            print(video.title)

        # Or iterate through all pages
        async for video in page.auto_paging_iter():
            print(video.title)
    """

    def __init__(
        self,
        data: List[T],
        model: Type[T],
        client: "AsyncHttpClient",
        endpoint: str,
        params: dict[str, Any],
        has_more: bool = False,
        next_cursor: Optional[str] = None,
    ) -> None:
        self._data = data
        self._model = model
        self._client = client
        self._endpoint = endpoint
        self._params = params
        self._has_more = has_more
        self._next_cursor = next_cursor

    @property
    def data(self) -> List[T]:
        """Items in the current page."""
        return self._data

    @property
    def has_more(self) -> bool:
        """Whether more pages are available."""
        return self._has_more

    @property
    def next_cursor(self) -> Optional[str]:
        """Cursor for the next page, if available."""
        return self._next_cursor

    def __iter__(self) -> Iterator[T]:
        """Iterate over items in the current page only (sync)."""
        return iter(self._data)

    def __aiter__(self) -> AsyncIterator[T]:
        """Async iterate over items in the current page."""
        return self._async_iter()

    async def _async_iter(self) -> AsyncIterator[T]:
        for item in self._data:
            yield item

    def __len__(self) -> int:
        """Number of items in the current page."""
        return len(self._data)

    def __getitem__(self, index: int) -> T:
        """Get item by index from current page."""
        return self._data[index]

    async def next_page(self) -> Optional["AsyncPage[T]"]:
        """Fetch the next page if available."""
        if not self._has_more or not self._next_cursor:
            return None

        params = {**self._params, "cursor": self._next_cursor}
        response = await self._client.get(self._endpoint, params=params)

        return _parse_paginated_response_async(
            response=response,
            model=self._model,
            client=self._client,
            endpoint=self._endpoint,
            params=self._params,
        )

    async def auto_paging_iter(self) -> AsyncIterator[T]:
        """
        Async iterate through all items across all pages.

        Automatically fetches subsequent pages as needed.
        """
        page: Optional[AsyncPage[T]] = self
        while page is not None:
            for item in page.data:
                yield item
            page = await page.next_page()


def _parse_paginated_response(
    response: dict[str, Any],
    model: Type[T],
    client: "SyncHttpClient",
    endpoint: str,
    params: dict[str, Any],
) -> SyncPage[T]:
    """Parse API response into a SyncPage."""
    data_raw = response.get("data", [])
    pagination = response.get("pagination", {})

    items = [model.model_validate(item) for item in data_raw]

    return SyncPage(
        data=items,
        model=model,
        client=client,
        endpoint=endpoint,
        params=params,
        has_more=pagination.get("has_more", False),
        next_cursor=pagination.get("next_cursor"),
    )


def _parse_paginated_response_async(
    response: dict[str, Any],
    model: Type[T],
    client: "AsyncHttpClient",
    endpoint: str,
    params: dict[str, Any],
) -> AsyncPage[T]:
    """Parse API response into an AsyncPage."""
    data_raw = response.get("data", [])
    pagination = response.get("pagination", {})

    items = [model.model_validate(item) for item in data_raw]

    return AsyncPage(
        data=items,
        model=model,
        client=client,
        endpoint=endpoint,
        params=params,
        has_more=pagination.get("has_more", False),
        next_cursor=pagination.get("next_cursor"),
    )
