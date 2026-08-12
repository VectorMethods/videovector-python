"""
VideoVector SDK Client.

Main entry point for the VideoVector Python SDK.
"""

from __future__ import annotations

from typing import Optional

from ._config import AuthMode, ClientConfig
from ._http import AsyncHttpClient, SyncHttpClient
from .resources import (
    ApiKeysResource,
    AsyncApiKeysResource,
    AsyncConnectorsResource,
    AsyncExportsResource,
    AsyncImportJobsResource,
    AsyncIndexesResource,
    AsyncPromptRunsResource,
    AsyncPromptsResource,
    AsyncRateLimitsResource,
    AsyncSearchResource,
    AsyncUsageResource,
    AsyncVideosResource,
    AsyncWebhooksResource,
    AsyncWorkflowResource,
    ConnectorsResource,
    ExportsResource,
    ImportJobsResource,
    IndexesResource,
    PromptRunsResource,
    PromptsResource,
    RateLimitsResource,
    SearchResource,
    UsageResource,
    VideosResource,
    WebhooksResource,
    WorkflowResource,
)


class VideoVector:
    """
    Synchronous VideoVector client.

    The main entry point for interacting with the VideoVector API.

    Example:
        from videovector import VideoVector

        # Initialize with API key
        client = VideoVector(api_key="<VIDEO_VECTOR_API_KEY>")

        # Or use environment variable VIDEO_VECTOR_API_KEY
        client = VideoVector()

        # Upload and process a video
        video = client.videos.upload(
            file="/path/to/video.mp4",
            title="My Video",
            index_id="idx_123"
        )

        # Execute a prompt on an index
        run = client.prompt_runs.execute(
            prompt_id="prompt_123",
            target={"type": "index", "index_id": "idx_123"}
        )

        # Wait for completion
        run = client.prompt_runs.wait_for_completion(run.run_id)

        # Search
        results = client.search.text(
            index_id="idx_123",
            query="person walking"
        )

        # Clean up
        client.close()

    Args:
        api_key: API key for authentication.
            Can also be set via VIDEO_VECTOR_API_KEY environment variable.
        bearer_token: JWT bearer token for authentication.
            Can also be set via VIDEO_VECTOR_BEARER_TOKEN environment variable.
        auth_mode: Explicit auth mode when both auth credentials are present.
            Valid values: "api_key" or "bearer".
            Can also be set via VIDEO_VECTOR_AUTH_MODE environment variable.
        base_url: Base URL for the API.
            Default: videovector._config.DEFAULT_BASE_URL
        timeout: Request timeout in seconds. Default: 60
        max_retries: Maximum retry attempts for failed requests. Default: 3

    Attributes:
        videos: Video management operations
        indexes: Index (collection) management
        prompts: Custom prompt management
        prompt_runs: Prompt execution and results
        search: Search operations (text, image, multimodal)
        usage: Usage metering endpoints
        rate_limits: Rate-limit status endpoints
        connectors: Cloud storage connector management
        import_jobs: Bulk import from cloud storage
        exports: Metadata export operations
        webhooks: Webhook configuration
        api_keys: API key management
        workflow: Simplified upload, prompt definition, processing, and search
    """

    videos: VideosResource
    indexes: IndexesResource
    prompts: PromptsResource
    prompt_runs: PromptRunsResource
    search: SearchResource
    usage: UsageResource
    rate_limits: RateLimitsResource
    connectors: ConnectorsResource
    import_jobs: ImportJobsResource
    exports: ExportsResource
    webhooks: WebhooksResource
    api_keys: ApiKeysResource
    workflow: WorkflowResource

    def __init__(
        self,
        api_key: Optional[str] = None,
        bearer_token: Optional[str] = None,
        *,
        auth_mode: Optional[AuthMode] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        max_retry_delay: Optional[int] = None,
        custom_headers: Optional[dict[str, str]] = None,
    ) -> None:
        self._config = ClientConfig.from_env(
            api_key=api_key,
            bearer_token=bearer_token,
            auth_mode=auth_mode,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            max_retry_delay=max_retry_delay,
            custom_headers=custom_headers,
        )
        self._http = SyncHttpClient(self._config)

        # Initialize resources
        self.videos = VideosResource(self._http)
        self.indexes = IndexesResource(self._http)
        self.prompts = PromptsResource(self._http)
        self.prompt_runs = PromptRunsResource(self._http)
        self.search = SearchResource(self._http)
        self.usage = UsageResource(self._http)
        self.rate_limits = RateLimitsResource(self._http)
        self.connectors = ConnectorsResource(self._http)
        self.import_jobs = ImportJobsResource(self._http)
        self.exports = ExportsResource(self._http)
        self.webhooks = WebhooksResource(self._http)
        self.api_keys = ApiKeysResource(self._http)
        self.workflow = WorkflowResource(self._http)

    def close(self) -> None:
        """Close the HTTP client and release resources."""
        self._http.close()

    def __enter__(self) -> "VideoVector":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class AsyncVideoVector:
    """
    Asynchronous VideoVector client.

    The async entry point for interacting with the VideoVector API.

    Example:
        from videovector import AsyncVideoVector

        async with AsyncVideoVector(api_key="<VIDEO_VECTOR_API_KEY>") as client:
            # Upload and process a video
            video = await client.videos.upload(
                file="/path/to/video.mp4",
                title="My Video",
                index_id="idx_123"
            )

            # Execute a prompt on an index
            run = await client.prompt_runs.execute(
                prompt_id="prompt_123",
                target={"type": "index", "index_id": "idx_123"}
            )

            # Wait for completion
            run = await client.prompt_runs.wait_for_completion(run.run_id)

            # Search
            results = await client.search.text(
                index_id="idx_123",
                query="person walking"
            )

    Args:
        api_key: API key for authentication.
            Can also be set via VIDEO_VECTOR_API_KEY environment variable.
        bearer_token: JWT bearer token for authentication.
            Can also be set via VIDEO_VECTOR_BEARER_TOKEN environment variable.
        auth_mode: Explicit auth mode when both auth credentials are present.
            Valid values: "api_key" or "bearer".
            Can also be set via VIDEO_VECTOR_AUTH_MODE environment variable.
        base_url: Base URL for the API.
            Default: videovector._config.DEFAULT_BASE_URL
        timeout: Request timeout in seconds. Default: 60
        max_retries: Maximum retry attempts for failed requests. Default: 3

    Attributes:
        videos: Video management operations
        indexes: Index (collection) management
        prompts: Custom prompt management
        prompt_runs: Prompt execution and results
        search: Search operations (text, image, multimodal)
        usage: Usage metering endpoints
        rate_limits: Rate-limit status endpoints
        connectors: Cloud storage connector management
        import_jobs: Bulk import from cloud storage
        exports: Metadata export operations
        webhooks: Webhook configuration
        api_keys: API key management
        workflow: Simplified upload, prompt definition, processing, and search
    """

    videos: AsyncVideosResource
    indexes: AsyncIndexesResource
    prompts: AsyncPromptsResource
    prompt_runs: AsyncPromptRunsResource
    search: AsyncSearchResource
    usage: AsyncUsageResource
    rate_limits: AsyncRateLimitsResource
    connectors: AsyncConnectorsResource
    import_jobs: AsyncImportJobsResource
    exports: AsyncExportsResource
    webhooks: AsyncWebhooksResource
    api_keys: AsyncApiKeysResource
    workflow: AsyncWorkflowResource

    def __init__(
        self,
        api_key: Optional[str] = None,
        bearer_token: Optional[str] = None,
        *,
        auth_mode: Optional[AuthMode] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        max_retry_delay: Optional[int] = None,
        custom_headers: Optional[dict[str, str]] = None,
    ) -> None:
        self._config = ClientConfig.from_env(
            api_key=api_key,
            bearer_token=bearer_token,
            auth_mode=auth_mode,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            max_retry_delay=max_retry_delay,
            custom_headers=custom_headers,
        )
        self._http = AsyncHttpClient(self._config)

        # Initialize resources
        self.videos = AsyncVideosResource(self._http)
        self.indexes = AsyncIndexesResource(self._http)
        self.prompts = AsyncPromptsResource(self._http)
        self.prompt_runs = AsyncPromptRunsResource(self._http)
        self.search = AsyncSearchResource(self._http)
        self.usage = AsyncUsageResource(self._http)
        self.rate_limits = AsyncRateLimitsResource(self._http)
        self.connectors = AsyncConnectorsResource(self._http)
        self.import_jobs = AsyncImportJobsResource(self._http)
        self.exports = AsyncExportsResource(self._http)
        self.webhooks = AsyncWebhooksResource(self._http)
        self.api_keys = AsyncApiKeysResource(self._http)
        self.workflow = AsyncWorkflowResource(self._http)

    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        await self._http.close()

    async def __aenter__(self) -> "AsyncVideoVector":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
