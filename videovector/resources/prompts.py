"""
VideoVector SDK Prompts Resource.

Provides methods for custom prompt and schema management.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional, Union
from uuid import uuid4

from .._types import (
    DeleteResponse,
    Prompt,
    PromptListResponse,
    PromptSemanticIndexingConfig,
    PromptSemanticIndexingConfigInput,
    PromptUsageStats,
    PromptVideoLevelConfig,
    PromptVideoLevelConfigInput,
    TestSchemaResponse,
)

if TYPE_CHECKING:
    from .._http import AsyncHttpClient, SyncHttpClient


def _normalize_video_level(
    video_level: Optional[Union[PromptVideoLevelConfig, PromptVideoLevelConfigInput, Dict[str, Any]]]
) -> Optional[Dict[str, Any]]:
    if video_level is None:
        return None
    if isinstance(video_level, PromptVideoLevelConfig):
        return video_level.model_dump()
    return dict(video_level)


def _normalize_semantic_indexing(
    semantic_indexing: Optional[
        Union[PromptSemanticIndexingConfig, PromptSemanticIndexingConfigInput, Dict[str, Any]]
    ]
) -> Optional[Dict[str, Any]]:
    if semantic_indexing is None:
        return None
    if isinstance(semantic_indexing, PromptSemanticIndexingConfig):
        return semantic_indexing.model_dump()
    return dict(semantic_indexing)


def _resolve_prompt_idempotency_key(operation: str, idempotency_key: Optional[str]) -> str:
    candidate = (idempotency_key or "").strip()
    if candidate:
        return candidate
    return f"prompt-{operation}:{uuid4().hex}"


class PromptsResource:
    """
    Synchronous Prompts resource.

    Provides methods for managing custom prompts with JSON schemas
    for structured metadata extraction from videos.

    Example:
        client = VideoVector(api_key="<VIDEO_VECTOR_API_KEY>")

        # Create a prompt with JSON schema
        prompt = client.prompts.create(
            name="Action Detection",
            prompt_text="Analyze this video segment and extract...",
            json_schema={
                "type": "object",
                "properties": {
                    "actions": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "main_subject": {"type": "string"}
                },
                "required": ["actions"]
            }
        )

        # Test a schema
        result = client.prompts.test_schema(
            json_schema={"type": "object", "properties": {"name": {"type": "string"}}},
            sample_data={"name": "test"}
        )
    """

    def __init__(self, client: "SyncHttpClient") -> None:
        self._client = client

    def create(
        self,
        *,
        name: str,
        prompt_text: str,
        json_schema: Dict[str, Any],
        description: str = "",
        video_level: Optional[
            Union[PromptVideoLevelConfig, PromptVideoLevelConfigInput, Dict[str, Any]]
        ] = None,
        semantic_indexing: Optional[
            Union[PromptSemanticIndexingConfig, PromptSemanticIndexingConfigInput, Dict[str, Any]]
        ] = None,
        idempotency_key: Optional[str] = None,
    ) -> Prompt:
        """
        Create a new prompt with JSON schema.

        Args:
            name: Prompt name (3-100 characters)
            prompt_text: Prompt text for LLM (10-5000 characters)
            json_schema: JSON Schema for structured output
            description: Optional description (max 500 characters)
            video_level: Optional video/audio-level synthesis configuration
            semantic_indexing: Optional prompt-level semantic indexing configuration
            idempotency_key: Optional key for idempotent prompt creation

        Returns:
            Prompt: Created prompt object

        Raises:
            ValidationError: If parameters are invalid
        """
        body: Dict[str, Any] = {
            "name": name,
            "description": description,
            "prompt_text": prompt_text,
            "json_schema": json_schema,
        }
        normalized_video_level = _normalize_video_level(video_level)
        if normalized_video_level is not None:
            body["video_level"] = normalized_video_level
        normalized_semantic_indexing = _normalize_semantic_indexing(semantic_indexing)
        if normalized_semantic_indexing is not None:
            body["semantic_indexing"] = normalized_semantic_indexing

        response = self._client.post(
            "/prompts",
            json=body,
            idempotency_key=_resolve_prompt_idempotency_key("create", idempotency_key),
        )
        return Prompt.model_validate(response)

    def retrieve(self, prompt_id: str) -> Prompt:
        """
        Retrieve a prompt by ID.

        Args:
            prompt_id: Prompt ID

        Returns:
            Prompt: Prompt object

        Raises:
            NotFoundError: If prompt doesn't exist
        """
        response = self._client.get(f"/prompts/{prompt_id}")
        return Prompt.model_validate(response)

    def list(
        self,
        *,
        active_only: bool = True,
        include_defaults: bool = True,
    ) -> PromptListResponse:
        """
        List all prompts accessible to the user.

        Args:
            active_only: Only return active prompts
            include_defaults: Include system default prompts

        Returns:
            PromptListResponse: Contains prompts list, total_count, active_count
        """
        response = self._client.get(
            "/prompts",
            params={
                "active_only": active_only,
                "include_defaults": include_defaults,
            },
        )
        return PromptListResponse.model_validate(response)

    def update(
        self,
        prompt_id: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        prompt_text: Optional[str] = None,
        json_schema: Optional[Dict[str, Any]] = None,
        video_level: Optional[
            Union[PromptVideoLevelConfig, PromptVideoLevelConfigInput, Dict[str, Any]]
        ] = None,
        semantic_indexing: Optional[
            Union[PromptSemanticIndexingConfig, PromptSemanticIndexingConfigInput, Dict[str, Any]]
        ] = None,
        clear_video_level: bool = False,
        idempotency_key: Optional[str] = None,
    ) -> Prompt:
        """
        Update a prompt definition.

        Args:
            prompt_id: Prompt ID
            name: New name (3-100 characters)
            description: New description (max 500 characters)
            prompt_text: New prompt text
            json_schema: New segment extraction schema
            video_level: Replacement video/audio-level synthesis config
            semantic_indexing: Replacement prompt-level semantic indexing config
            clear_video_level: Remove any existing video-level config
            idempotency_key: Optional key for idempotent prompt updates

        Returns:
            Prompt: Updated prompt object
        """
        body: Dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if prompt_text is not None:
            body["prompt_text"] = prompt_text
        if json_schema is not None:
            body["json_schema"] = json_schema
        if video_level is not None:
            body["video_level"] = _normalize_video_level(video_level)
        if semantic_indexing is not None:
            body["semantic_indexing"] = _normalize_semantic_indexing(semantic_indexing)
        if clear_video_level:
            body["clear_video_level"] = True

        response = self._client.put(
            f"/prompts/{prompt_id}",
            json=body,
            idempotency_key=_resolve_prompt_idempotency_key("update", idempotency_key),
        )
        return Prompt.model_validate(response)

    def delete(self, prompt_id: str, *, force: bool = False) -> DeleteResponse:
        """
        Delete a prompt.

        Args:
            prompt_id: Prompt ID
            force: Force delete even if in use

        Returns:
            DeleteResponse: Confirmation message

        Raises:
            NotFoundError: If prompt doesn't exist
            AuthorizationError: If admin scope is required
        """
        response = self._client.delete(
            f"/prompts/{prompt_id}",
            params={"force": force} if force else None,
        )
        return DeleteResponse.model_validate(response)

    def test_schema(
        self,
        *,
        json_schema: Dict[str, Any],
        sample_data: Dict[str, Any],
    ) -> TestSchemaResponse:
        """
        Test a JSON schema against sample data.

        Args:
            json_schema: JSON Schema to test
            sample_data: Sample data to validate

        Returns:
            TestSchemaResponse: Validation result with valid flag, validated_data, error, message
        """
        response = self._client.post(
            "/prompts/test-schema",
            json={
                "json_schema": json_schema,
                "sample_data": sample_data,
            },
        )
        return TestSchemaResponse.model_validate(response)

    def get_usage(self, prompt_id: str) -> PromptUsageStats:
        """
        Get usage statistics for a prompt.

        Args:
            prompt_id: Prompt ID

        Returns:
            PromptUsageStats: Usage statistics including is_in_use, schema_properties_count
        """
        response = self._client.get(f"/prompts/{prompt_id}/usage")
        return PromptUsageStats.model_validate(response)


class AsyncPromptsResource:
    """
    Asynchronous Prompts resource.

    Provides async methods for managing custom prompts.

    Example:
        async with AsyncVideoVector(api_key="<VIDEO_VECTOR_API_KEY>") as client:
            prompt = await client.prompts.create(
                name="Action Detection",
                prompt_text="Analyze this video...",
                json_schema={"type": "object", "properties": {...}}
            )
    """

    def __init__(self, client: "AsyncHttpClient") -> None:
        self._client = client

    async def create(
        self,
        *,
        name: str,
        prompt_text: str,
        json_schema: Dict[str, Any],
        description: str = "",
        video_level: Optional[
            Union[PromptVideoLevelConfig, PromptVideoLevelConfigInput, Dict[str, Any]]
        ] = None,
        semantic_indexing: Optional[
            Union[PromptSemanticIndexingConfig, PromptSemanticIndexingConfigInput, Dict[str, Any]]
        ] = None,
        idempotency_key: Optional[str] = None,
    ) -> Prompt:
        """Create a new prompt with JSON schema."""
        body: Dict[str, Any] = {
            "name": name,
            "description": description,
            "prompt_text": prompt_text,
            "json_schema": json_schema,
        }
        normalized_video_level = _normalize_video_level(video_level)
        if normalized_video_level is not None:
            body["video_level"] = normalized_video_level
        normalized_semantic_indexing = _normalize_semantic_indexing(semantic_indexing)
        if normalized_semantic_indexing is not None:
            body["semantic_indexing"] = normalized_semantic_indexing

        response = await self._client.post(
            "/prompts",
            json=body,
            idempotency_key=_resolve_prompt_idempotency_key("create", idempotency_key),
        )
        return Prompt.model_validate(response)

    async def retrieve(self, prompt_id: str) -> Prompt:
        """Retrieve a prompt by ID."""
        response = await self._client.get(f"/prompts/{prompt_id}")
        return Prompt.model_validate(response)

    async def list(
        self,
        *,
        active_only: bool = True,
        include_defaults: bool = True,
    ) -> PromptListResponse:
        """List all prompts accessible to the user."""
        response = await self._client.get(
            "/prompts",
            params={
                "active_only": active_only,
                "include_defaults": include_defaults,
            },
        )
        return PromptListResponse.model_validate(response)

    async def update(
        self,
        prompt_id: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        prompt_text: Optional[str] = None,
        json_schema: Optional[Dict[str, Any]] = None,
        video_level: Optional[
            Union[PromptVideoLevelConfig, PromptVideoLevelConfigInput, Dict[str, Any]]
        ] = None,
        semantic_indexing: Optional[
            Union[PromptSemanticIndexingConfig, PromptSemanticIndexingConfigInput, Dict[str, Any]]
        ] = None,
        clear_video_level: bool = False,
        idempotency_key: Optional[str] = None,
    ) -> Prompt:
        """Update a prompt definition."""
        body: Dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if prompt_text is not None:
            body["prompt_text"] = prompt_text
        if json_schema is not None:
            body["json_schema"] = json_schema
        if video_level is not None:
            body["video_level"] = _normalize_video_level(video_level)
        if semantic_indexing is not None:
            body["semantic_indexing"] = _normalize_semantic_indexing(semantic_indexing)
        if clear_video_level:
            body["clear_video_level"] = True

        response = await self._client.put(
            f"/prompts/{prompt_id}",
            json=body,
            idempotency_key=_resolve_prompt_idempotency_key("update", idempotency_key),
        )
        return Prompt.model_validate(response)

    async def delete(self, prompt_id: str, *, force: bool = False) -> DeleteResponse:
        """Delete a prompt."""
        response = await self._client.delete(
            f"/prompts/{prompt_id}",
            params={"force": force} if force else None,
        )
        return DeleteResponse.model_validate(response)

    async def test_schema(
        self,
        *,
        json_schema: Dict[str, Any],
        sample_data: Dict[str, Any],
    ) -> TestSchemaResponse:
        """Test a JSON schema against sample data."""
        response = await self._client.post(
            "/prompts/test-schema",
            json={
                "json_schema": json_schema,
                "sample_data": sample_data,
            },
        )
        return TestSchemaResponse.model_validate(response)

    async def get_usage(self, prompt_id: str) -> PromptUsageStats:
        """Get usage statistics for a prompt."""
        response = await self._client.get(f"/prompts/{prompt_id}/usage")
        return PromptUsageStats.model_validate(response)
