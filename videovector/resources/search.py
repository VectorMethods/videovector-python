"""
VideoVector SDK Search Resource.

Provides methods for text, image, multimodal, and filter-based search.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Mapping, Optional, Tuple, cast

from .._types import (
    FilterCondition,
    FilterOperator,
    FilterSearchResponse,
    FilterValueType,
    ImageSearchResult,
    MultimodalSearchResult,
    SearchResult,
)

if TYPE_CHECKING:
    from .._http import AsyncHttpClient, SyncHttpClient


_MAX_FILTER_CONDITIONS = 4
_FILTER_CONDITION_KEYS = {"field", "operator", "value", "type"}
_FILTER_OPERATORS_BY_TYPE: Dict[str, Tuple[str, ...]] = {
    "string": (
        "equals",
        "contains",
        "starts_with",
        "ends_with",
        "is_empty",
        "is_not_empty",
    ),
    "integer": ("equals", "greater_than", "greater_equal", "less_than", "less_equal"),
    "number": ("equals", "greater_than", "greater_equal", "less_than", "less_equal"),
    "boolean": ("equals",),
    "array": (
        "item_equals",
        "item_contains",
        "length_equals",
        "length_greater",
        "length_less",
        "is_empty",
        "is_not_empty",
    ),
}
_VALUELESS_FILTER_OPERATORS = {"is_empty", "is_not_empty"}
_ARRAY_LENGTH_FILTER_OPERATORS = {"length_equals", "length_greater", "length_less"}


def _is_json_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_json_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _has_filter_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _validate_filter_value_type(value_type: str, operator: str, value: Any, index: int) -> None:
    prefix = f"Condition {index + 1}"
    if value_type == "string":
        if not isinstance(value, str):
            raise ValueError(f"{prefix}: value for type 'string' must be a string")
        return

    if value_type == "integer":
        if not _is_json_integer(value):
            raise ValueError(f"{prefix}: value for type 'integer' must be an integer")
        return

    if value_type == "number":
        if not _is_json_number(value):
            raise ValueError(f"{prefix}: value for type 'number' must be a finite number")
        return

    if value_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{prefix}: value for type 'boolean' must be a boolean")
        return

    if value_type == "array":
        if operator in _ARRAY_LENGTH_FILTER_OPERATORS:
            if not _is_json_integer(value) or value < 0:
                raise ValueError(
                    f"{prefix}: value for array length operators must be a non-negative integer"
                )
            return
        if operator == "item_contains" and not isinstance(value, str):
            raise ValueError(f"{prefix}: value for operator 'item_contains' must be a string")
        if operator == "item_equals" and (
            value is None or isinstance(value, (list, dict)) or not isinstance(value, (str, int, float, bool))
        ):
            raise ValueError(
                f"{prefix}: value for operator 'item_equals' must be a string, number, or boolean"
            )
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"{prefix}: value for operator '{operator}' must be finite")


def _validate_filter_condition(condition: object, index: int) -> FilterCondition:
    if not isinstance(condition, Mapping):
        raise ValueError(f"Condition {index + 1}: must be an object")

    unknown_keys = set(condition) - _FILTER_CONDITION_KEYS
    if unknown_keys:
        formatted_keys = ", ".join(sorted(str(key) for key in unknown_keys))
        raise ValueError(f"Condition {index + 1}: unsupported fields: {formatted_keys}")

    field = condition.get("field")
    if not isinstance(field, str) or not field.strip():
        raise ValueError(f"Condition {index + 1}: field is required and must be a non-empty string")

    operator = condition.get("operator")
    if not isinstance(operator, str) or not operator:
        raise ValueError(f"Condition {index + 1}: operator is required and must be a string")

    value_type = condition.get("type")
    if not isinstance(value_type, str) or not value_type:
        raise ValueError(f"Condition {index + 1}: type is required and must be a string")

    operators = _FILTER_OPERATORS_BY_TYPE.get(value_type)
    if operators is None:
        supported_types = ", ".join(_FILTER_OPERATORS_BY_TYPE)
        raise ValueError(
            f"Condition {index + 1}: unsupported filter type '{value_type}'. "
            f"Supported types: {supported_types}"
        )
    if operator not in operators:
        supported_operators = ", ".join(operators)
        raise ValueError(
            f"Condition {index + 1}: unsupported operator '{operator}' for type '{value_type}'. "
            f"Supported operators: {supported_operators}"
        )

    validated_operator = cast(FilterOperator, operator)
    validated_type = cast(FilterValueType, value_type)

    if operator in _VALUELESS_FILTER_OPERATORS:
        if "value" in condition:
            raise ValueError(f"Condition {index + 1}: operator '{operator}' does not accept a value")
        return {"field": field.strip(), "operator": validated_operator, "type": validated_type}

    if not _has_filter_value(condition.get("value")):
        raise ValueError(f"Condition {index + 1}: operator '{operator}' requires a value")
    _validate_filter_value_type(value_type, operator, condition["value"], index)

    return {
        "field": field.strip(),
        "operator": validated_operator,
        "value": condition["value"],
        "type": validated_type,
    }


def _validate_filter_conditions(conditions: List[FilterCondition]) -> List[FilterCondition]:
    if not isinstance(conditions, list):
        raise ValueError("conditions must be a list")
    if not conditions or len(conditions) > _MAX_FILTER_CONDITIONS:
        raise ValueError(f"conditions must contain 1-{_MAX_FILTER_CONDITIONS} items")
    return [_validate_filter_condition(condition, index) for index, condition in enumerate(conditions)]


def _build_filter_search_body(
    *,
    conditions: List[FilterCondition],
    page_size: int,
    cursor: Optional[str] = None,
    run_ids: Optional[List[str]] = None,
    index_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    validated_conditions = _validate_filter_conditions(conditions)
    body: Dict[str, Any] = {
        "conditions": validated_conditions,
        "page_size": page_size,
    }
    if cursor:
        body["cursor"] = cursor
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
                {"field": "category", "operator": "equals", "value": "sports", "type": "string"}
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
        run_ids: Optional[List[str]] = None,
        index_ids: Optional[List[str]] = None,
    ) -> FilterSearchResponse:
        """
        Perform filter-based search on segment metadata.

        Args:
            index_id: Index ID to search
            conditions: Filter conditions (1-4 conditions)
                Each condition must use canonical field, operator, and type keys.
                Value-bearing operators require value; is_empty and is_not_empty reject value.
            page_size: Number of results per page (1-100)
            cursor: Pagination cursor
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
        run_ids: Optional[List[str]] = None,
        index_ids: Optional[List[str]] = None,
    ) -> FilterSearchResponse:
        """
        Perform filter-based search in the user's playground.

        Args:
            conditions: Filter conditions (1-4 conditions)
                Value-bearing operators require value; is_empty and is_not_empty reject value.
            page_size: Number of results per page (1-100)
            cursor: Pagination cursor
            run_ids: Filter to specific prompt runs
            index_ids: Optional explicit index IDs

        Returns:
            FilterSearchResponse: Filter results
        """
        body = _build_filter_search_body(
            conditions=conditions,
            page_size=page_size,
            cursor=cursor,
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
        run_ids: Optional[List[str]] = None,
        index_ids: Optional[List[str]] = None,
    ) -> FilterSearchResponse:
        """Perform filter-based search on segment metadata."""
        body = _build_filter_search_body(
            conditions=conditions,
            page_size=page_size,
            cursor=cursor,
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
        run_ids: Optional[List[str]] = None,
        index_ids: Optional[List[str]] = None,
    ) -> FilterSearchResponse:
        """Perform filter-based search in the user's playground."""
        body = _build_filter_search_body(
            conditions=conditions,
            page_size=page_size,
            cursor=cursor,
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
