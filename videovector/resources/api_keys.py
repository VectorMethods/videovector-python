"""
VideoVector SDK API Keys Resource.

Provides methods for API key management.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .._types import ApiKey, ApiKeyWithSecret, DeleteResponse

if TYPE_CHECKING:
    from .._http import AsyncHttpClient, SyncHttpClient


class ApiKeysResource:
    """
    Synchronous API Keys resource.

    Provides methods for managing API keys for programmatic access.

    Note: API key management requires JWT authentication (web login).
    API keys cannot create or manage other API keys.

    Example:
        # Using JWT authentication
        client = VideoVector(api_key="jwt_token_here")

        # Create an API key with read scope
        key = client.api_keys.create(
            name="Production Read Key",
            scopes=["read", "search"],
            expires_in_days=90
        )

        # Store the key securely - it's only shown once
        api_key = key.key  # <VIDEO_VECTOR_API_KEY>

        # Later, list all keys (masked)
        keys = client.api_keys.list()

        # Rotate a compromised key
        new_key = client.api_keys.rotate(key.key_id)
    """

    def __init__(self, client: "SyncHttpClient") -> None:
        self._client = client

    def create(
        self,
        *,
        name: str,
        scopes: Optional[List[str]] = None,
        expires_in_days: Optional[int] = None,
    ) -> ApiKeyWithSecret:
        """
        Create a new API key.

        Args:
            name: Key name (1-100 characters)
            scopes: Permission scopes (search, read, write, admin)
                Default: ["read"]
            expires_in_days: Days until expiration (1-365)
                None = never expires

        Returns:
            ApiKeyWithSecret: Created key with full key value (shown once)

        Raises:
            ValidationError: If parameters are invalid
            AuthorizationError: If not using JWT authentication
        """
        body: Dict[str, Any] = {"name": name}
        if scopes is not None:
            body["scopes"] = scopes
        if expires_in_days is not None:
            body["expires_in_days"] = expires_in_days

        response = self._client.post("/api-keys", json=body)
        return ApiKeyWithSecret.model_validate(response)

    def retrieve(self, key_id: str) -> ApiKey:
        """
        Retrieve an API key by ID.

        Args:
            key_id: API key ID

        Returns:
            ApiKey: Key details (masked)

        Raises:
            NotFoundError: If key doesn't exist
        """
        response = self._client.get(f"/api-keys/{key_id}")
        return ApiKey.model_validate(response)

    def list(self) -> List[ApiKey]:
        """
        List all API keys.

        Returns:
            List[ApiKey]: All API keys (masked)
        """
        response = self._client.get("/api-keys")
        return [ApiKey.model_validate(k) for k in response]

    def delete(self, key_id: str) -> DeleteResponse:
        """
        Delete an API key.

        Args:
            key_id: API key ID

        Returns:
            DeleteResponse: Confirmation message

        Raises:
            NotFoundError: If key doesn't exist
        """
        response = self._client.delete(f"/api-keys/{key_id}")
        return DeleteResponse.model_validate(response)

    def revoke(self, key_id: str) -> ApiKey:
        """
        Revoke an API key (soft delete).

        The key remains visible but becomes inactive.

        Args:
            key_id: API key ID

        Returns:
            ApiKey: Revoked key

        Raises:
            NotFoundError: If key doesn't exist
        """
        response = self._client.post(f"/api-keys/{key_id}/revoke")
        return ApiKey.model_validate(response)

    def rotate(self, key_id: str) -> ApiKeyWithSecret:
        """
        Rotate an API key.

        Creates a new key and revokes the old one.

        Args:
            key_id: API key ID to rotate

        Returns:
            ApiKeyWithSecret: New key (old key is revoked)

        Raises:
            NotFoundError: If key doesn't exist
        """
        response = self._client.post(f"/api-keys/{key_id}/rotate")
        # The response contains old_key_id and new_key
        return ApiKeyWithSecret.model_validate(response.get("new_key", response))


class AsyncApiKeysResource:
    """
    Asynchronous API Keys resource.

    Provides async methods for API key management.

    Example:
        async with AsyncVideoVector(api_key="jwt_token") as client:
            key = await client.api_keys.create(
                name="Production Key",
                scopes=["read", "search"]
            )
    """

    def __init__(self, client: "AsyncHttpClient") -> None:
        self._client = client

    async def create(
        self,
        *,
        name: str,
        scopes: Optional[List[str]] = None,
        expires_in_days: Optional[int] = None,
    ) -> ApiKeyWithSecret:
        """Create a new API key."""
        body: Dict[str, Any] = {"name": name}
        if scopes is not None:
            body["scopes"] = scopes
        if expires_in_days is not None:
            body["expires_in_days"] = expires_in_days

        response = await self._client.post("/api-keys", json=body)
        return ApiKeyWithSecret.model_validate(response)

    async def retrieve(self, key_id: str) -> ApiKey:
        """Retrieve an API key by ID."""
        response = await self._client.get(f"/api-keys/{key_id}")
        return ApiKey.model_validate(response)

    async def list(self) -> List[ApiKey]:
        """List all API keys."""
        response = await self._client.get("/api-keys")
        return [ApiKey.model_validate(k) for k in response]

    async def delete(self, key_id: str) -> DeleteResponse:
        """Delete an API key."""
        response = await self._client.delete(f"/api-keys/{key_id}")
        return DeleteResponse.model_validate(response)

    async def revoke(self, key_id: str) -> ApiKey:
        """Revoke an API key."""
        response = await self._client.post(f"/api-keys/{key_id}/revoke")
        return ApiKey.model_validate(response)

    async def rotate(self, key_id: str) -> ApiKeyWithSecret:
        """Rotate an API key."""
        response = await self._client.post(f"/api-keys/{key_id}/rotate")
        return ApiKeyWithSecret.model_validate(response.get("new_key", response))
