"""
VideoVector SDK Webhooks Resource.

Provides methods for webhook configuration and event management.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import uuid4

from .._types import (
    DeleteResponse,
    RotateSecretResponse,
    Webhook,
    WebhookDelivery,
    WebhookTestResponse,
    WebhookWithSecret,
)

if TYPE_CHECKING:
    from .._http import AsyncHttpClient, SyncHttpClient


def _resolve_webhook_idempotency_key(
    operation: str,
    idempotency_key: Optional[str],
) -> str:
    candidate = (idempotency_key or "").strip()
    if candidate:
        return candidate
    return f"webhook-{operation}:{uuid4().hex}"


# Supported webhook events
WEBHOOK_EVENTS = [
    "media.created",
    "media.processing.started",
    "media.processing.completed",
    "media.processing.failed",
    "prompt_run.started",
    "prompt_run.completed",
    "prompt_run.failed",
    "prompt_run.cancelled",
    "prompt_run.partial_completed",
    "prompt_run.progress",
    "export.ready",
    "export.failed",
    "import_job.started",
    "import_job.completed",
    "import_job.failed",
    "import_job.partial_completed",
    "import_job.progress",
]


class WebhooksResource:
    """
    Synchronous Webhooks resource.

    Provides methods for configuring webhooks to receive event notifications.

    Example:
        client = VideoVector(api_key="<VIDEO_VECTOR_API_KEY>")

        # Create a webhook
        webhook = client.webhooks.create(
            name="Processing Notifications",
            url="https://api.example.com/webhooks",
            events=["media.processing.completed", "prompt_run.completed"]
        )

        # Save the secret for signature verification
        webhook_secret = webhook.secret

        # List deliveries
        deliveries = client.webhooks.list_deliveries(webhook.webhook_id)

        # Test the webhook
        result = client.webhooks.test(webhook.webhook_id)
    """

    def __init__(self, client: "SyncHttpClient") -> None:
        self._client = client

    def create(
        self,
        *,
        name: str,
        url: str,
        events: List[str],
        index_ids: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> WebhookWithSecret:
        """
        Create a new webhook.

        Args:
            name: Webhook name (1-100 characters)
            url: Webhook URL (must be HTTPS)
            events: List of events to subscribe to
            index_ids: Limit events to specific indexes (None = all)
            metadata: Custom metadata to include in payloads

        Returns:
            WebhookWithSecret: Created webhook with secret (shown once)

        Raises:
            ValidationError: If parameters are invalid
        """
        body: Dict[str, Any] = {
            "name": name,
            "url": url,
            "events": events,
        }
        if index_ids is not None:
            body["index_ids"] = index_ids
        if metadata is not None:
            body["metadata"] = metadata

        response = self._client.post(
            "/webhooks",
            json=body,
            idempotency_key=_resolve_webhook_idempotency_key("create", idempotency_key),
        )
        return WebhookWithSecret.model_validate(response)

    def retrieve(self, webhook_id: str) -> Webhook:
        """
        Retrieve a webhook by ID.

        Args:
            webhook_id: Webhook ID

        Returns:
            Webhook: Webhook configuration

        Raises:
            NotFoundError: If webhook doesn't exist
        """
        response = self._client.get(f"/webhooks/{webhook_id}")
        return Webhook.model_validate(response)

    def list(self) -> List[Webhook]:
        """
        List all webhooks.

        Returns:
            List[Webhook]: All webhook configurations
        """
        response = self._client.get("/webhooks")
        return [Webhook.model_validate(w) for w in response]

    def update(
        self,
        webhook_id: str,
        *,
        name: Optional[str] = None,
        url: Optional[str] = None,
        events: Optional[List[str]] = None,
        index_ids: Optional[List[str]] = None,
        status: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Webhook:
        """
        Update a webhook configuration.

        Args:
            webhook_id: Webhook ID
            name: New name (1-100 characters)
            url: New URL (must be HTTPS)
            events: New events list
            index_ids: New index filter
            status: New status (active, paused)
            metadata: New metadata

        Returns:
            Webhook: Updated webhook

        Raises:
            NotFoundError: If webhook doesn't exist
        """
        body: Dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if url is not None:
            body["url"] = url
        if events is not None:
            body["events"] = events
        if index_ids is not None:
            body["index_ids"] = index_ids
        if status is not None:
            body["status"] = status
        if metadata is not None:
            body["metadata"] = metadata

        response = self._client.patch(
            f"/webhooks/{webhook_id}",
            json=body,
            idempotency_key=_resolve_webhook_idempotency_key("update", idempotency_key),
        )
        return Webhook.model_validate(response)

    def delete(self, webhook_id: str) -> DeleteResponse:
        """
        Delete a webhook.

        Args:
            webhook_id: Webhook ID

        Returns:
            DeleteResponse: Confirmation message

        Raises:
            NotFoundError: If webhook doesn't exist
        """
        response = self._client.delete(f"/webhooks/{webhook_id}")
        return DeleteResponse.model_validate(response)

    def rotate_secret(self, webhook_id: str) -> RotateSecretResponse:
        """
        Rotate the webhook signing secret.

        Args:
            webhook_id: Webhook ID

        Returns:
            RotateSecretResponse: Contains webhook_id and new_secret

        Raises:
            NotFoundError: If webhook doesn't exist
        """
        response = self._client.post(f"/webhooks/{webhook_id}/rotate-secret")
        return RotateSecretResponse.model_validate(response)

    def test(self, webhook_id: str, *, idempotency_key: Optional[str] = None) -> WebhookTestResponse:
        """
        Send a test event to the webhook.

        Args:
            webhook_id: Webhook ID

        Returns:
            WebhookTestResponse: Contains success flag, status_code, error message

        Raises:
            NotFoundError: If webhook doesn't exist
        """
        response = self._client.post(
            f"/webhooks/{webhook_id}/test",
            idempotency_key=_resolve_webhook_idempotency_key("test", idempotency_key),
        )
        return WebhookTestResponse.model_validate(response)

    def list_deliveries(
        self,
        webhook_id: str,
        *,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[WebhookDelivery]:
        """
        List delivery attempts for a webhook.

        Args:
            webhook_id: Webhook ID
            status: Filter by status (pending, delivered, failed, retrying)
            limit: Number of results (1-100)

        Returns:
            List[WebhookDelivery]: Delivery records
        """
        params: Dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status

        response = self._client.get(f"/webhooks/{webhook_id}/deliveries", params=params)
        return [WebhookDelivery.model_validate(d) for d in response]

    def get_delivery(self, delivery_id: str) -> WebhookDelivery:
        """
        Get details of a specific delivery.

        Args:
            delivery_id: Delivery ID

        Returns:
            WebhookDelivery: Delivery details with payload
        """
        response = self._client.get(f"/webhooks/deliveries/{delivery_id}")
        return WebhookDelivery.model_validate(response)

    def retry_delivery(self, delivery_id: str) -> WebhookDelivery:
        """
        Retry a failed delivery.

        Args:
            delivery_id: Delivery ID

        Returns:
            WebhookDelivery: Updated delivery record
        """
        response = self._client.post(f"/webhooks/deliveries/{delivery_id}/retry")
        return WebhookDelivery.model_validate(response)

    def list_events(self) -> List[str]:
        """
        Get list of all supported webhook events.

        Returns:
            List[str]: Event names
        """
        response = self._client.get("/webhooks/events")
        if isinstance(response, list):
            return [str(event) for event in response]
        raise ValueError("Expected list response when listing webhook events.")


class AsyncWebhooksResource:
    """
    Asynchronous Webhooks resource.

    Provides async methods for webhook management.

    Example:
        async with AsyncVideoVector(api_key="<VIDEO_VECTOR_API_KEY>") as client:
            webhook = await client.webhooks.create(
                name="Processing Notifications",
                url="https://api.example.com/webhooks",
                events=["prompt_run.completed"]
            )
    """

    def __init__(self, client: "AsyncHttpClient") -> None:
        self._client = client

    async def create(
        self,
        *,
        name: str,
        url: str,
        events: List[str],
        index_ids: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> WebhookWithSecret:
        """Create a new webhook."""
        body: Dict[str, Any] = {
            "name": name,
            "url": url,
            "events": events,
        }
        if index_ids is not None:
            body["index_ids"] = index_ids
        if metadata is not None:
            body["metadata"] = metadata

        response = await self._client.post(
            "/webhooks",
            json=body,
            idempotency_key=_resolve_webhook_idempotency_key("create", idempotency_key),
        )
        return WebhookWithSecret.model_validate(response)

    async def retrieve(self, webhook_id: str) -> Webhook:
        """Retrieve a webhook by ID."""
        response = await self._client.get(f"/webhooks/{webhook_id}")
        return Webhook.model_validate(response)

    async def list(self) -> List[Webhook]:
        """List all webhooks."""
        response = await self._client.get("/webhooks")
        return [Webhook.model_validate(w) for w in response]

    async def update(
        self,
        webhook_id: str,
        *,
        name: Optional[str] = None,
        url: Optional[str] = None,
        events: Optional[List[str]] = None,
        index_ids: Optional[List[str]] = None,
        status: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Webhook:
        """Update a webhook configuration."""
        body: Dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if url is not None:
            body["url"] = url
        if events is not None:
            body["events"] = events
        if index_ids is not None:
            body["index_ids"] = index_ids
        if status is not None:
            body["status"] = status
        if metadata is not None:
            body["metadata"] = metadata

        response = await self._client.patch(
            f"/webhooks/{webhook_id}",
            json=body,
            idempotency_key=_resolve_webhook_idempotency_key("update", idempotency_key),
        )
        return Webhook.model_validate(response)

    async def delete(self, webhook_id: str) -> DeleteResponse:
        """Delete a webhook."""
        response = await self._client.delete(f"/webhooks/{webhook_id}")
        return DeleteResponse.model_validate(response)

    async def rotate_secret(self, webhook_id: str) -> RotateSecretResponse:
        """Rotate the webhook signing secret."""
        response = await self._client.post(f"/webhooks/{webhook_id}/rotate-secret")
        return RotateSecretResponse.model_validate(response)

    async def test(self, webhook_id: str, *, idempotency_key: Optional[str] = None) -> WebhookTestResponse:
        """Send a test event to the webhook."""
        response = await self._client.post(
            f"/webhooks/{webhook_id}/test",
            idempotency_key=_resolve_webhook_idempotency_key("test", idempotency_key),
        )
        return WebhookTestResponse.model_validate(response)

    async def list_deliveries(
        self,
        webhook_id: str,
        *,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[WebhookDelivery]:
        """List delivery attempts for a webhook."""
        params: Dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status

        response = await self._client.get(f"/webhooks/{webhook_id}/deliveries", params=params)
        return [WebhookDelivery.model_validate(d) for d in response]

    async def get_delivery(self, delivery_id: str) -> WebhookDelivery:
        """Get details of a specific delivery."""
        response = await self._client.get(f"/webhooks/deliveries/{delivery_id}")
        return WebhookDelivery.model_validate(response)

    async def retry_delivery(self, delivery_id: str) -> WebhookDelivery:
        """Retry a failed delivery."""
        response = await self._client.post(f"/webhooks/deliveries/{delivery_id}/retry")
        return WebhookDelivery.model_validate(response)

    async def list_events(self) -> List[str]:
        """Get list of all supported webhook events."""
        response = await self._client.get("/webhooks/events")
        if isinstance(response, list):
            return [str(event) for event in response]
        raise ValueError("Expected list response when listing webhook events.")
