"""
VideoVector Python SDK.

A production-ready SDK for the VideoVector video understanding API.

Quick Start:
    from videovector import VideoVector

    # Initialize client
    client = VideoVector(api_key="<VIDEO_VECTOR_API_KEY>")

    # Create an index
    index = client.indexes.create(name="My Videos")

    # Upload a video
    video = client.videos.upload(
        file="/path/to/video.mp4",
        title="Product Demo",
        index_id=index.index_id
    )

    # Create a custom prompt with schema
    prompt = client.prompts.create(
        name="Product Analysis",
        prompt_text="Analyze this video segment and extract product details...",
        json_schema={
            "type": "object",
            "properties": {
                "products": {"type": "array", "items": {"type": "string"}},
                "actions": {"type": "array", "items": {"type": "string"}},
                "sentiment": {"type": "string", "enum": ["positive", "negative", "neutral"]}
            },
            "required": ["products"]
        }
    )

    # Execute the prompt on the index
    run = client.prompt_runs.execute(
        prompt_id=prompt.prompt_id,
        target={"type": "index", "index_id": index.index_id}
    )

    # Wait for completion
    run = client.prompt_runs.wait_for_completion(run.run_id)

    # Search for content
    results = client.search.text(
        index_id=index.index_id,
        query="product demonstration"
    )

    for result in results:
        print(f"Found at {result.start_time}s: {result.text_content}")

Async Usage:
    from videovector import AsyncVideoVector

    async with AsyncVideoVector(api_key="<VIDEO_VECTOR_API_KEY>") as client:
        results = await client.search.text(
            index_id="idx_123",
            query="person walking"
        )

Environment Variables:
    VIDEO_VECTOR_API_KEY: API key for authentication
    VIDEO_VECTOR_BEARER_TOKEN: Static OAuth access token or Firebase ID token
    VIDEO_VECTOR_AUTH_MODE: Explicit auth mode when both credentials exist (api_key or bearer)
    VIDEO_VECTOR_BASE_URL: Base URL (default: videovector._config.DEFAULT_BASE_URL)
    VIDEO_VECTOR_TIMEOUT: Request timeout in seconds (default: 60)
    VIDEO_VECTOR_MAX_RETRIES: Max retry attempts (default: 3)
    VIDEO_VECTOR_MAX_RETRY_DELAY: Max retry wait in seconds (default: 300)

Long-lived OAuth clients should pass oauth_token_provider to VideoVector or
AsyncVideoVector so an established OAuth session can refresh outside the SDK.
"""

from ._client import AsyncVideoVector, VideoVector
from ._config import AsyncOAuthTokenProvider, ClientConfig, OAuthTokenProvider
from ._exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    ConnectionError,
    ExternalServiceError,
    IdempotencyError,
    NotFoundError,
    ProcessingError,
    RateLimitError,
    TimeoutError,
    ValidationError,
    VideoVectorError,
)
from ._pagination import AsyncPage, SyncPage
from ._types import (
    ApiKey,
    ApiKeyScope,
    ApiKeyWithSecret,
    BatchVideoSegmentsTarget,
    CloudFile,
    Connector,
    ConnectorImportMode,
    ConnectorProvider,
    ConnectorStatus,
    CurrentUsage,
    DeleteResponse,
    ExecutePromptTarget,
    Export,
    ExportCreateResult,
    ExportDownloadUrlResult,
    ExportStatus,
    ExportType,
    FilterCondition,
    FilterSearchResponse,
    ImageSearchResult,
    ImportJob,
    ImportJobProgress,
    ImportJobStatus,
    Index,
    IndexDeletionResponse,
    LlmCall,
    MarkerInfo,
    MatchedFieldInstance,
    MultimodalSearchResult,
    ProcessingModel,
    ProcessingStartedResponse,
    ProcessingStatus,
    Prompt,
    PromptListResponse,
    PromptRun,
    PromptRunCostEstimate,
    PromptRunFailedSegment,
    PromptRunFailedSegmentsManifest,
    PromptRunFailedVideo,
    PromptRunFailureOperationCounts,
    PromptRunProcessingStatus,
    PromptRunSegmentRetry,
    PromptRunSegmentRetryStatus,
    PromptRunStatus,
    PromptRunVideoResult,
    PromptUsageStats,
    PromptVideoLevelConfig,
    RateLimitCategoryStatus,
    RateLimitStatus,
    RotateSecretResponse,
    SearchResult,
    Segment,
    SegmentationType,
    SegmentRunProcessingStatus,
    SegmentRunResult,
    SignedUrl,
    TestConnectionResult,
    TestSchemaResponse,
    UploadResult,
    UsageBreakdown,
    UsageDetail,
    UsageHistory,
    UsageHistoryItem,
    UsageMetricTypeInfo,
    UsageTotals,
    Video,
    VideoDeletionResponse,
    VideoLevelProcessingStatus,
    VideoSegments,
    VideoStatus,
    VideoWithDetails,
    Webhook,
    WebhookDelivery,
    WebhookStatus,
    WebhookTestResponse,
    WebhookWithSecret,
    WorkflowDefineResponse,
    WorkflowDestination,
    WorkflowPagination,
    WorkflowProcessResponse,
    WorkflowPromptDefinition,
    WorkflowSearchResponse,
    WorkflowUploadResponse,
)
from ._version import __version__

__all__ = [
    # Version
    "__version__",
    # Clients
    "VideoVector",
    "AsyncVideoVector",
    # Configuration
    "ClientConfig",
    "OAuthTokenProvider",
    "AsyncOAuthTokenProvider",
    # Exceptions
    "VideoVectorError",
    "AuthenticationError",
    "AuthorizationError",
    "NotFoundError",
    "ValidationError",
    "RateLimitError",
    "ConflictError",
    "ProcessingError",
    "ExternalServiceError",
    "ConnectionError",
    "TimeoutError",
    "IdempotencyError",
    # Pagination
    "SyncPage",
    "AsyncPage",
    # Types - Core
    "Video",
    "VideoWithDetails",
    "VideoStatus",
    "VideoSegments",
    "BatchVideoSegmentsTarget",
    "Segment",
    "Index",
    "Prompt",
    "PromptVideoLevelConfig",
    "PromptRun",
    "PromptRunVideoResult",
    "PromptRunFailedSegment",
    "PromptRunFailedVideo",
    "PromptRunFailedSegmentsManifest",
    "PromptRunFailureOperationCounts",
    "PromptRunSegmentRetry",
    "PromptRunSegmentRetryStatus",
    "PromptRunCostEstimate",
    "PromptRunProcessingStatus",
    "SegmentRunResult",
    "LlmCall",
    "MarkerInfo",
    "SegmentRunProcessingStatus",
    "VideoLevelProcessingStatus",
    # Types - Search
    "MatchedFieldInstance",
    "SearchResult",
    "ImageSearchResult",
    "MultimodalSearchResult",
    "FilterSearchResponse",
    "WorkflowSearchResponse",
    "WorkflowPagination",
    # Types - Connectors
    "Connector",
    "CloudFile",
    "TestConnectionResult",
    # Types - Import
    "ImportJob",
    "ImportJobProgress",
    # Types - Exports
    "Export",
    "ExportCreateResult",
    "ExportDownloadUrlResult",
    # Types - Webhooks
    "Webhook",
    "WebhookWithSecret",
    "WebhookDelivery",
    "WebhookTestResponse",
    "RotateSecretResponse",
    # Types - API Keys
    "ApiKey",
    "ApiKeyWithSecret",
    # Types - Utilities
    "SignedUrl",
    "UploadResult",
    "WorkflowUploadResponse",
    "WorkflowDestination",
    "WorkflowPromptDefinition",
    "WorkflowDefineResponse",
    "WorkflowProcessResponse",
    "DeleteResponse",
    "IndexDeletionResponse",
    "VideoDeletionResponse",
    "ProcessingStartedResponse",
    # Types - Prompts
    "PromptListResponse",
    "TestSchemaResponse",
    "PromptUsageStats",
    # Types - Usage / Rate limits
    "UsageTotals",
    "CurrentUsage",
    "UsageHistoryItem",
    "UsageHistory",
    "UsageDetail",
    "UsageBreakdown",
    "UsageMetricTypeInfo",
    "RateLimitCategoryStatus",
    "RateLimitStatus",
    # Types - Request Helpers
    "ExecutePromptTarget",
    "FilterCondition",
    # Enums
    "ProcessingStatus",
    "PromptRunStatus",
    "WebhookStatus",
    "ImportJobStatus",
    "SegmentationType",
    "ProcessingModel",
    "ApiKeyScope",
    "ConnectorImportMode",
    "ConnectorProvider",
    "ConnectorStatus",
    "ExportStatus",
    "ExportType",
]
