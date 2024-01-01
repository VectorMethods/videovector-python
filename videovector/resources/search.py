"""
VideoVector SDK Search Resource.

Provides methods for text, image, multimodal, and filter-based search.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional

from .._types import (
    FilterCondition,
    FilterSearchResponse,
    ImageSearchResult,
    MultimodalSearchResult,
    SearchResult,
)

if TYPE_CHECKING:
    from .._http import AsyncHttpClient, SyncHttpClient


def _build_filter_search_body(
    *,
    conditions: List[FilterCondition],
    page_size: int,
    cursor: Optional[str] = None,
    start_after: Optional[str] = None,
    run_ids: Optional[List[str]] = None,
    index_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "conditions": conditions,
        "page_size": page_size,
    }
    normalized_cursor = cursor or start_after
    if normalized_cursor:
        body["cursor"] = normalized_cursor
    if run_ids:
        body["run_ids"] = run_ids
    if index_ids:
        body["index_ids"] = index_ids
    return body


class SearchResource:
    """
    Synchronous Search resource.

    Provides methods for semantic search across indexed video segments.

    Example:
        client = VideoVector(api_key="<VIDEO_VECTOR_API_KEY>")

        # Text search
        results = client.search.text(
            index_id="idx_123",
            query="person walking in park",
            top_k=10
        )

        # Image search
        with open("query_image.jpg", "rb") as f:
            import base64
            image_data = base64.b64encode(f.read()).decode()

        results = client.search.image(
            index_id="idx_123",
            image_data=image_data,
            top_k=10
        )

        # Multimodal search (text + image)
        results = client.search.multimodal(
            index_id="idx_123",
            text_query="red car",
            image_data=image_data,
            text_weight=0.7,
            image_weight=0.3
        )

        # Filter search
        results = client.search.filter(
            index_id="idx_123",
            conditions=[
                {"field": "category", "operator": "eq", "value": "sports", "type": "string"}
            ]
        )
    """

    def __init__(self, client: "SyncHttpClient") -> None:
        self._client = client

    def text(
        self,
        index_id: str,
        *,
        query: str,
        top_k: int = 30,
        search_fields: Optional[List[str]] = None,
        run_ids: Optional[List[str]] = None,
        index_ids: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        """
        Perform semantic text search.

        Args:
            index_id: Primary index ID to search
            query: Search query text
            top_k: Number of results to return (1-100)
            search_fields: Limit search to specific metadata fields
            run_ids: Filter results to specific prompt runs
            index_ids: Additional indexes to search (overrides path param)

        Returns:
            List[SearchResult]: Ranked search results

        Raises:
            NotFoundError: If index doesn't exist
        """
        body: Dict[str, Any] = {
            "query": query,
            "top_k": top_k,
        }
        if search_fields:
            body["search_fields"] = search_fields
        if run_ids:
            body["run_ids"] = run_ids
        if index_ids:
            body["index_ids"] = index_ids

        response = self._client.post(f"/indexes/{index_id}/search", json=body)
        return [SearchResult.model_validate(r) for r in response]

    def image(
        self,
        index_id: str,
        *,
        image_data: str,
        top_k: int = 20,
        run_ids: Optional[List[str]] = None,
        index_ids: Optional[List[str]] = None,
    ) -> List[ImageSearchResult]:
        """
        Perform image similarity search.

        Args:
            index_id: Primary index ID to search
            image_data: Base64-encoded image data
            top_k: Number of results to return (1-100)
            run_ids: Filter results to specific prompt runs
            index_ids: Additional indexes to search

        Returns:
            List[ImageSearchResult]: Ranked image search results

        Raises:
            NotFoundError: If index doesn't exist
            ValidationError: If image data is invalid
        """
        body: Dict[str, Any] = {
            "image_data": image_data,
            "top_k": top_k,
        }
        if run_ids:
            body["run_ids"] = run_ids
        if index_ids:
            body["index_ids"] = index_ids

        response = self._client.post(f"/indexes/{index_id}/image-search", json=body)
        return [ImageSearchResult.model_validate(r) for r in response]

    def multimodal(
        self,
        index_id: str,
        *,
        text_query: Optional[str] = None,
        image_data: Optional[str] = None,
        top_k: int = 20,
        text_weight: float = 0.5,
        image_weight: float = 0.5,
        search_fields: Optional[List[str]] = None,
        run_ids: Optional[List[str]] = None,
        index_ids: Optional[List[str]] = None,
    ) -> List[MultimodalSearchResult]:
        """
        Perform multimodal search combining text and image.

        Uses Reciprocal Rank Fusion (RRF) to combine results.

        Args:
            index_id: Primary index ID to search
            text_query: Text query (required if no image_data)
            image_data: Base64-encoded image (required if no text_query)
            top_k: Number of results to return (1-100)
            text_weight: Weight for text results (0.0-1.0)
            image_weight: Weight for image results (0.0-1.0)
            search_fields: Limit text search to specific fields
            run_ids: Filter results to specific prompt runs
            index_ids: Additional indexes to search

        Returns:
            List[MultimodalSearchResult]: Fused search results

        Raises:
            ValidationError: If neither text_query nor image_data provided
        """
        body: Dict[str, Any] = {
            "top_k": top_k,
            "text_weight": text_weight,
            "image_weight": image_weight,
        }
        if text_query:
            body["text_query"] = text_query
        if image_data:
            body["image_data"] = image_data
        if search_fields:
            body["search_fields"] = search_fields
        if run_ids:
            body["run_ids"] = run_ids
        if index_ids:
            body["index_ids"] = index_ids

        response = self._client.post(f"/indexes/{index_id}/multimodal-search", json=body)
        return [MultimodalSearchResult.model_validate(r) for r in response]

    def filter(
        self,
        index_id: str,
        *,
        conditions: List[FilterCondition],
        page_size: int = 50,
        cursor: Optional[str] = None,
        start_after: Optional[str] = None,
        run_ids: Optional[List[str]] = None,
        index_ids: Optional[List[str]] = None,
    ) -> FilterSearchResponse:
        """
        Perform filter-based search on segment metadata.

        Args:
            index_id: Index ID to search
            conditions: Filter conditions (1-5 conditions)
                Each condition: {field, operator, value, type, fuzzyMatch?}
                Operators may use the backend canonical filter operators or legacy aliases.
            page_size: Number of results per page (1-100)
            cursor: Pagination cursor
            start_after: Legacy pagination cursor alias
            run_ids: Filter to specific prompt runs
            index_ids: Additional indexes to search

        Returns:
            FilterSearchResponse: Contains results list, next_page_token, total_shown

        Raises:
            ValidationError: If conditions are invalid
        """
        body = _build_filter_search_body(
            conditions=conditions,
            page_size=page_size,
            cursor=cursor,
            start_after=start_after,
            run_ids=run_ids,
            index_ids=index_ids,
        )
        response = self._client.post(f"/search/filter/{index_id}", json=body)
        return FilterSearchResponse.model_validate(response)

    def filter_playground(
        self,
        *,
        conditions: List[FilterCondition],
        page_size: int = 50,
        cursor: Optional[str] = None,
        start_after: Optional[str] = None,
        run_ids: Optional[List[str]] = None,
        index_ids: Optional[List[str]] = None,
    ) -> FilterSearchResponse:
        """
        Perform filter-based search in the user's playground.

        Args:
            conditions: Filter conditions (1-5 conditions)
            page_size: Number of results per page (1-100)
            cursor: Pagination cursor
            start_after: Legacy pagination cursor alias
            run_ids: Filter to specific prompt runs
            index_ids: Optional explicit index IDs

        Returns:
            FilterSearchResponse: Filter results
        """
        body = _build_filter_search_body(
            conditions=conditions,
            page_size=page_size,
            cursor=cursor,
            start_after=start_after,
            run_ids=run_ids,
            index_ids=index_ids,
        )
        response = self._client.post("/search/filter/playground", json=body)
        return FilterSearchResponse.model_validate(response)

    def multi_run(
        self,
        *,
        query: str,
        run_ids: Optional[List[str]] = None,
        index_id: Optional[str] = None,
        aggregation: Literal["best", "all", "weighted"] = "best",
        top_k: int = 5,
    ) -> List[SearchResult]:
        """
        Search across multiple prompt runs.

        Args:
            query: Search query text
            run_ids: Specific run IDs to search
            index_id: Index ID (used if run_ids not provided)
            aggregation: How to aggregate results
                - best: Best result per segment
                - all: All results
                - weighted: Weighted by run recency
            top_k: Number of results per run (1-50)

        Returns:
            List[SearchResult]: Aggregated search results
        """
        body: Dict[str, Any] = {
            "query": query,
            "aggregation": aggregation,
            "top_k": top_k,
        }
        if run_ids:
            body["run_ids"] = run_ids
        if index_id:
            body["index_id"] = index_id

        response = self._client.post("/search/multi-run", json=body)
        return [SearchResult.model_validate(r) for r in response]

    def playground(
        self,
        *,
        query: str,
        top_k: int = 30,
        run_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        Search in the user's playground.

        Args:
            query: Search query text
            top_k: Number of results (1-100)
            run_id: Filter to specific prompt run

        Returns:
            List[SearchResult]: Search results from playground
        """
        body: Dict[str, Any] = {
            "query": query,
            "top_k": top_k,
        }

        params = {}
        if run_id:
            params["run_id"] = run_id

        response = self._client.post("/playground/search", json=body, params=params)
        return [SearchResult.model_validate(r) for r in response]


class AsyncSearchResource:
    """
    Asynchronous Search resource.

    Provides async methods for semantic search across indexed video segments.

    Example:
        async with AsyncVideoVector(api_key="<VIDEO_VECTOR_API_KEY>") as client:
            results = await client.search.text(
                index_id="idx_123",
                query="person walking in park"
            )
    """

    def __init__(self, client: "AsyncHttpClient") -> None:
        self._client = client

    async def text(
        self,
        index_id: str,
        *,
        query: str,
        top_k: int = 30,
        search_fields: Optional[List[str]] = None,
        run_ids: Optional[List[str]] = None,
        index_ids: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        """Perform semantic text search."""
        body: Dict[str, Any] = {
            "query": query,
            "top_k": top_k,
        }
        if search_fields:
            body["search_fields"] = search_fields
        if run_ids:
            body["run_ids"] = run_ids
        if index_ids:
            body["index_ids"] = index_ids

        response = await self._client.post(f"/indexes/{index_id}/search", json=body)
        return [SearchResult.model_validate(r) for r in response]

    async def image(
        self,
        index_id: str,
        *,
        image_data: str,
        top_k: int = 20,
        run_ids: Optional[List[str]] = None,
        index_ids: Optional[List[str]] = None,
    ) -> List[ImageSearchResult]:
        """Perform image similarity search."""
        body: Dict[str, Any] = {
            "image_data": image_data,
            "top_k": top_k,
        }
        if run_ids:
            body["run_ids"] = run_ids
        if index_ids:
            body["index_ids"] = index_ids

        response = await self._client.post(f"/indexes/{index_id}/image-search", json=body)
        return [ImageSearchResult.model_validate(r) for r in response]

    async def multimodal(
        self,
        index_id: str,
        *,
        text_query: Optional[str] = None,
        image_data: Optional[str] = None,
        top_k: int = 20,
        text_weight: float = 0.5,
        image_weight: float = 0.5,
        search_fields: Optional[List[str]] = None,
        run_ids: Optional[List[str]] = None,
        index_ids: Optional[List[str]] = None,
    ) -> List[MultimodalSearchResult]:
        """Perform multimodal search combining text and image."""
        body: Dict[str, Any] = {
            "top_k": top_k,
            "text_weight": text_weight,
            "image_weight": image_weight,
        }
        if text_query:
            body["text_query"] = text_query
        if image_data:
            body["image_data"] = image_data
        if search_fields:
            body["search_fields"] = search_fields
        if run_ids:
            body["run_ids"] = run_ids
        if index_ids:
            body["index_ids"] = index_ids

        response = await self._client.post(f"/indexes/{index_id}/multimodal-search", json=body)
        return [MultimodalSearchResult.model_validate(r) for r in response]

    async def filter(
        self,
        index_id: str,
        *,
        conditions: List[FilterCondition],
        page_size: int = 50,
        cursor: Optional[str] = None,
        start_after: Optional[str] = None,
        run_ids: Optional[List[str]] = None,
        index_ids: Optional[List[str]] = None,
    ) -> FilterSearchResponse:
        """Perform filter-based search on segment metadata."""
        body = _build_filter_search_body(
            conditions=conditions,
            page_size=page_size,
            cursor=cursor,
            start_after=start_after,
            run_ids=run_ids,
            index_ids=index_ids,
        )
        response = await self._client.post(f"/search/filter/{index_id}", json=body)
        return FilterSearchResponse.model_validate(response)

    async def filter_playground(
        self,
        *,
        conditions: List[FilterCondition],
        page_size: int = 50,
        cursor: Optional[str] = None,
        start_after: Optional[str] = None,
        run_ids: Optional[List[str]] = None,
        index_ids: Optional[List[str]] = None,
    ) -> FilterSearchResponse:
        """Perform filter-based search in the user's playground."""
        body = _build_filter_search_body(
            conditions=conditions,
            page_size=page_size,
            cursor=cursor,
            start_after=start_after,
            run_ids=run_ids,
            index_ids=index_ids,
        )
        response = await self._client.post("/search/filter/playground", json=body)
        return FilterSearchResponse.model_validate(response)

    async def multi_run(
        self,
        *,
        query: str,
        run_ids: Optional[List[str]] = None,
        index_id: Optional[str] = None,
        aggregation: Literal["best", "all", "weighted"] = "best",
        top_k: int = 5,
    ) -> List[SearchResult]:
        """Search across multiple prompt runs."""
        body: Dict[str, Any] = {
            "query": query,
            "aggregation": aggregation,
            "top_k": top_k,
        }
        if run_ids:
            body["run_ids"] = run_ids
        if index_id:
            body["index_id"] = index_id

        response = await self._client.post("/search/multi-run", json=body)
        return [SearchResult.model_validate(r) for r in response]

    async def playground(
        self,
        *,
        query: str,
        top_k: int = 30,
        run_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """Search in the user's playground."""
        body: Dict[str, Any] = {
            "query": query,
            "top_k": top_k,
        }

        params = {}
        if run_id:
            params["run_id"] = run_id

        response = await self._client.post("/playground/search", json=body, params=params)
        return [SearchResult.model_validate(r) for r in response]
