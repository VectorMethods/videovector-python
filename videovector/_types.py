"""
VideoVector SDK Type Definitions.

Provides Pydantic models and TypedDicts for request/response typing.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, TypedDict, Union

from pydantic import BaseModel, Field, model_validator

# =============================================================================
# Enums
# =============================================================================


class ProcessingStatus(str, Enum):
    NOT_PROCESSED = "not_processed"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class PromptRunStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    COMPLETED_WITH_FAILURES = "completed_with_failures"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WebhookStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"


class ImportJobStatus(str, Enum):
    PENDING = "pending"
    SCANNING = "scanning"
    IMPORTING = "importing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SegmentationType(str, Enum):
    SMART = "smart"
    FIXED = "fixed"
    CONTENT_AWARE = "content_aware"


class ProcessingModel(str, Enum):
    GEMINI_3_PRO_PREVIEW = "gemini-3-pro-preview"
    GEMINI_2_5_PRO = "gemini-2.5-pro"
    GEMINI_2_5_FLASH = "gemini-2.5-flash"
    GEMINI_2_5_FLASH_LITE = "gemini-2.5-flash-lite"


class ApiKeyScope(str, Enum):
    """Tenant API-key scopes.

    ``ADMIN`` grants full access within the owning account only; it never grants
    VideoVector platform-administrator privileges.
    """

    SEARCH = "search"
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


class ConnectorProvider(str, Enum):
    """Cloud storage provider types."""

    GCS = "gcs"
    S3 = "s3"
    AZURE = "azure"


class ConnectorStatus(str, Enum):
    """Connector connection status."""

    ACTIVE = "active"
    TESTING = "testing"
    FAILED = "failed"
    DISABLED = "disabled"


class ConnectorImportMode(str, Enum):
    """Connector import dedupe behavior."""

    ALL = "all"
    NEW_ONLY = "new_only"


class ExportStatus(str, Enum):
    """Export job status."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ExportType(str, Enum):
    """Export target type."""

    INDEX = "index"
    PROMPT_RUN = "prompt_run"


# =============================================================================
# Response Models
# =============================================================================


class SegmentRunProcessingStatus(BaseModel):
    """Per-segment processing state inside a specific prompt run."""

    segment_id: str
    video_id: Optional[str] = None
    status: str
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    updated_at: Optional[str] = None
    error_message: Optional[str] = None
    failure_stage: Optional[str] = None
    attempt_id: Optional[str] = None


class VideoLevelProcessingStatus(BaseModel):
    """Inline video/audio-level synthesis progress inside a video status snapshot."""

    status: str
    result_available: bool = False
    successful_segment_count: int = 0
    failed_segment_count: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    updated_at: Optional[str] = None
    error_message: Optional[str] = None
    attempt_id: Optional[str] = None


class PromptRunStopState(BaseModel):
    """Stop-request lifecycle for a prompt run."""

    requested_at: Optional[str] = None
    requested_by: Optional[str] = None
    mode: Optional[str] = None
    observed_at: Optional[str] = None
    completed_at: Optional[str] = None


class PromptRunProcessingStatus(BaseModel):
    """Per-run processing summary and segment status snapshot for a video."""

    run_id: str
    prompt_id: Optional[str] = None
    status: str
    total_segments: int
    pending_segments: int
    processing_segments: int
    successful_segments: int
    failed_segments: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    attempt_id: Optional[str] = None
    video_level: Optional[VideoLevelProcessingStatus] = None
    segments: List[SegmentRunProcessingStatus] = Field(default_factory=list)


class MarkerInfo(BaseModel):
    """Marker metadata attached to prompts, runs, or extracted fields."""

    marker_id: Optional[str] = None
    color: Optional[str] = None
    note: Optional[str] = None
    updated_at: Optional[str] = None


class MatchedFieldInstance(BaseModel):
    """Exact matched field instance inside nested/list metadata."""

    field_path: str
    field_display_label: Optional[str] = None
    field_instance_key: str
    field_instance_path: str
    field_instance_display_label: Optional[str] = None
    score: float
    value_preview: str = ""


class Video(BaseModel):
    """Video resource representation."""

    video_id: str
    title: str
    video_uri: str
    status: str
    processing_status: Optional[List[PromptRunProcessingStatus]] = None
    created_at: str
    updated_at: Optional[str] = None
    metadata_keys: Optional[List[str]] = None
    media_type: str = "video"
    marker: MarkerInfo = Field(default_factory=MarkerInfo)


class VideoWithDetails(Video):
    """Video with additional details like thumbnails."""

    gif_data: Optional[str] = None
    first_thumbnail: Optional[str] = None


class Segment(BaseModel):
    """Video segment representation."""

    segment_id: str
    video_id: str
    start_time: float
    end_time: float
    gcs_uri: Optional[str] = None
    thumbnail_gcs_uri: Optional[str] = None
    gif_gcs_uri: Optional[str] = None
    thumbnail_uri: Optional[str] = None
    gif_uri: Optional[str] = None
    processed: bool = False
    processing_failed: bool = False
    segment_status: str = "pending"
    failure_stage: Optional[str] = None
    failure_message: Optional[str] = None
    attempt_id: Optional[str] = None
    status_source: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    metadata_text: Optional[str] = None
    created_at: Optional[str] = None
    processed_at: Optional[str] = None
    error_message: Optional[str] = None
    processing_warning: Optional[str] = None
    thumbnail_data: Optional[str] = None
    thumbnail_available: bool = False
    gif_data: Optional[str] = None
    gif_available: bool = False
    from_run_id: Optional[str] = None
    marker: MarkerInfo = Field(default_factory=MarkerInfo)
    metadata_markers: Dict[str, MarkerInfo] = Field(default_factory=dict)
    field_extraction_succeeded: Optional[bool] = None
    transcription_succeeded: Optional[bool] = None
    image_embedding_succeeded: Optional[bool] = None
    field_extraction_error: Optional[str] = None
    transcription_error: Optional[str] = None
    image_embedding_error: Optional[str] = None


class Index(BaseModel):
    """Index resource representation."""

    index_id: str
    name: str
    user_id: str
    created_at: str
    description: Optional[str] = None
    sort_order: Optional[int] = None
    is_default: bool = False


class PromptVideoLevelConfig(BaseModel):
    """Video/audio-level synthesis configuration attached to a prompt."""

    instructions_text: str
    included_segment_fields: List[str]
    json_schema: Dict[str, Any]


class PromptSemanticIndexingConfig(BaseModel):
    """Prompt-level controls for semantic indexing of output leaves."""

    disabled_segment_fields: List[str] = Field(default_factory=list)
    disabled_video_level_fields: List[str] = Field(default_factory=list)


class Prompt(BaseModel):
    """Prompt resource representation."""

    prompt_id: str
    user_id: str
    name: str
    description: str
    prompt_text: str
    json_schema: Dict[str, Any]
    video_level: Optional[PromptVideoLevelConfig] = None
    semantic_indexing: PromptSemanticIndexingConfig = Field(
        default_factory=PromptSemanticIndexingConfig
    )
    is_active: bool = True
    created_at: str


class PromptRun(BaseModel):
    """Prompt run (execution) representation."""

    run_id: str
    prompt_id: str
    prompt_name: str
    prompt_type: str
    executed_at: str
    executed_by: str
    status: str
    run_context: Dict[str, Any]
    total_videos: int = 0
    completed_videos: int = 0
    failed_videos: int = 0
    total_audios: int = 0
    completed_audios: int = 0
    failed_audios: int = 0
    partial_audios: int = 0
    cancelled_audios: int = 0
    total_images: int = 0
    completed_images: int = 0
    failed_images: int = 0
    partial_images: int = 0
    cancelled_images: int = 0
    partial_videos: int = 0
    cancelled_videos: int = 0
    total_segments: int = 0
    completed_segments: int = 0
    field_extraction_failures: int = 0
    transcription_failures: int = 0
    image_embedding_failures: int = 0
    field_extraction_succeeded: Optional[bool] = None
    transcription_succeeded: Optional[bool] = None
    image_embedding_succeeded: Optional[bool] = None
    error_message: Optional[str] = None
    video_segmentation_type: str = "smart"
    audio_segmentation_type: str = "content_aware"
    image_segmentation_type: str = "image"
    video_segment_duration: Optional[int] = None
    audio_segment_duration: Optional[int] = None
    created_new_segments: bool = False
    processing_model: Optional[str] = None
    total_video_seconds: float = 0.0
    enable_transcription: bool = True
    enable_image_embedding: bool = True
    video_level_enabled: bool = False
    video_level_total_items: int = 0
    video_level_completed_items: int = 0
    video_level_failed_items: int = 0
    video_level_partial_items: int = 0
    stop_state: PromptRunStopState = Field(default_factory=PromptRunStopState)
    billing_estimated_mt: float = 0.0
    billing_actual_mt: float = 0.0
    billing_status: Optional[str] = None
    billing_error: Optional[str] = None
    marker: MarkerInfo = Field(default_factory=MarkerInfo)


class SegmentRunResult(BaseModel):
    """Segment-level result from a prompt run."""

    result_type: Literal["segment"] = "segment"
    result_id: Optional[str] = None
    segment_id: str
    video_id: Optional[str] = None
    run_id: str
    prompt_id: str
    prompt_run_id: Optional[str] = None
    video_name: Optional[str] = None
    source_index_id: Optional[str] = None
    executed_at: str
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    segment_uri: Optional[str] = None
    gcs_uri: Optional[str] = None
    thumbnail_uri: Optional[str] = None
    thumbnail_gcs_uri: Optional[str] = None
    gif_uri: Optional[str] = None
    gif_gcs_uri: Optional[str] = None
    thumbnail_available: bool = False
    gif_available: bool = False
    metadata: Dict[str, Any]
    metadata_text: str
    processing_warning: Optional[str] = None
    schema_used: Optional[str] = None
    field_extraction_succeeded: bool = True
    transcription_succeeded: Optional[bool] = None
    image_embedding_succeeded: Optional[bool] = None
    field_extraction_error: Optional[str] = None
    transcription_error: Optional[str] = None
    image_embedding_error: Optional[str] = None
    marker: MarkerInfo = Field(default_factory=MarkerInfo)
    extracted_metadata_markers: Dict[str, MarkerInfo] = Field(default_factory=dict)
    metadata_markers: Dict[str, MarkerInfo] = Field(default_factory=dict)


class PromptRunVideoResult(BaseModel):
    """Video/audio-level synthesis result for a single media item in a run."""

    result_type: Literal["video"] = "video"
    result_id: Optional[str] = None
    run_id: str
    prompt_id: str
    prompt_run_id: Optional[str] = None
    video_id: str
    video_name: Optional[str] = None
    source_index_id: Optional[str] = None
    executed_at: str
    status: str
    metadata: Dict[str, Any]
    metadata_text: str
    raw_llm_response: Optional[str] = None
    processing_warning: Optional[str] = None
    schema_used: Optional[str] = None
    successful_segment_count: int = 0
    failed_segment_count: int = 0
    omitted_segment_ids: List[str] = Field(default_factory=list)
    template_fields: List[str] = Field(default_factory=list)
    source_fingerprint: Optional[str] = None
    rendered_prompt_char_count: int = 0
    llm_attempted: bool = False
    attempt_id: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    segment_uri: Optional[str] = None
    gcs_uri: Optional[str] = None
    thumbnail_uri: Optional[str] = None
    thumbnail_gcs_uri: Optional[str] = None
    gif_uri: Optional[str] = None
    gif_gcs_uri: Optional[str] = None
    thumbnail_available: bool = False
    gif_available: bool = False
    preview_segment_id: Optional[str] = None
    preview_start_time: Optional[float] = None
    preview_end_time: Optional[float] = None
    preview_segment_uri: Optional[str] = None
    preview_thumbnail_uri: Optional[str] = None
    preview_gif_uri: Optional[str] = None
    marker: MarkerInfo = Field(default_factory=MarkerInfo)


class PromptRunFailureOperationCounts(BaseModel):
    """Failure counts grouped by operation type."""

    field_extraction: int = 0
    transcription: int = 0
    image_embedding: int = 0
    processing: int = 0


class PromptRunFailedSegment(BaseModel):
    """Failed segment details for a prompt run."""

    segment_id: str
    failed_operations: List[str] = Field(default_factory=list)
    field_extraction_error: Optional[str] = None
    transcription_error: Optional[str] = None
    image_embedding_error: Optional[str] = None
    failure_stage: Optional[str] = None
    failure_message: Optional[str] = None
    failure_code: Optional[str] = None
    retryable: Optional[bool] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    projection_only: bool = False


class PromptRunFailedVideo(BaseModel):
    """Failed segment summary for one video inside a run."""

    video_id: str
    failed_segments: int = 0
    operation_counts: PromptRunFailureOperationCounts = Field(
        default_factory=PromptRunFailureOperationCounts
    )
    segments: List[PromptRunFailedSegment] = Field(default_factory=list)


class PromptRunFailedSegmentsManifest(BaseModel):
    """Run-level failed segment manifest."""

    run_id: str
    status: str
    videos_with_failures: int = 0
    failed_segments: int = 0
    operation_counts: PromptRunFailureOperationCounts = Field(
        default_factory=PromptRunFailureOperationCounts
    )
    videos: List[PromptRunFailedVideo] = Field(default_factory=list)


class PromptRunSegmentRetry(BaseModel):
    """Async retry dispatch result for a failed prompt-run segment."""

    run_id: str
    retry_id: str
    status: str
    message: str
    idempotency_key: Optional[str] = None
    video_id: str
    segment_id: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    billing_estimated_mt: float = 0.0
    billing_actual_mt: float = 0.0
    billing_status: Optional[str] = None
    billing_error: Optional[str] = None


class PromptRunSegmentRetryStatus(BaseModel):
    """Status snapshot for a previously dispatched segment retry."""

    run_id: str
    retry_id: str
    status: str
    video_id: str
    segment_id: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    billing_estimated_mt: float = 0.0
    billing_actual_mt: float = 0.0
    billing_status: Optional[str] = None
    billing_error: Optional[str] = None
    field_extraction_succeeded: Optional[bool] = None
    transcription_succeeded: Optional[bool] = None
    image_embedding_succeeded: Optional[bool] = None


class LlmCall(BaseModel):
    """Record of an LLM invocation during prompt execution.

    Used for debugging and understanding extraction details.
    """

    llm_call_id: str
    prompt_run_id: Optional[str] = None
    prompt_id: Optional[str] = None
    video_id: Optional[str] = None
    segment_id: Optional[str] = None
    user_id: str
    model: str
    purpose: str
    status: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    video_seconds: float
    segment_start_time: Optional[float] = None
    segment_end_time: Optional[float] = None
    prompt_text: Optional[str] = None
    response_text: Optional[str] = None
    schema_used: Optional[str] = None
    invoked_at: str
    completed_at: Optional[str] = None
    created_at: Optional[str] = None  # Backward-compat alias for older payloads
    duration_ms: Optional[int] = None  # Optional convenience field
    error_message: Optional[str] = None


class SearchResult(BaseModel):
    """Text/multimodal search result."""

    result_type: Literal["segment", "video"] = "segment"
    result_id: str
    video_id: str
    video_uri: Optional[str] = None
    video_name: Optional[str] = None
    segment_id: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    preview_segment_id: Optional[str] = None
    preview_start_time: Optional[float] = None
    preview_end_time: Optional[float] = None
    preview_segment_uri: Optional[str] = None
    preview_thumbnail_uri: Optional[str] = None
    preview_gif_uri: Optional[str] = None
    text_content: str
    content_preview: str = ""
    metadata_text: Optional[str] = None
    similarity_score: Optional[float] = None
    reranked_score: Optional[float] = None
    segment_uri: Optional[str] = None
    gcs_uri: Optional[str] = None
    thumbnail_gcs_uri: Optional[str] = None
    gif_gcs_uri: Optional[str] = None
    thumbnail_uri: Optional[str] = None
    thumbnail_data: Optional[str] = None
    thumbnail_available: bool = False
    gif_uri: Optional[str] = None
    gif_data: Optional[str] = None
    gif_available: bool = False
    media_type: Optional[Literal["video", "audio", "image"]] = None
    metadata: Optional[Dict[str, Any]] = None
    extracted_metadata: Optional[Dict[str, Any]] = None
    field_scores: Optional[Dict[str, float]] = None
    field_instance_scores: Optional[Dict[str, float]] = None
    matched_field_paths: Optional[List[str]] = None
    matched_field_instances: Optional[List[MatchedFieldInstance]] = None
    run_id: Optional[str] = None
    source_run_id: Optional[str] = None
    prompt_run_id: Optional[str] = None
    raw_llm_response: Optional[str] = None
    source_index_id: Optional[str] = None
    marker: MarkerInfo = Field(default_factory=MarkerInfo)
    extracted_metadata_markers: Dict[str, MarkerInfo] = Field(default_factory=dict)


class ImageSearchResult(SearchResult):
    """Image similarity search result."""

    matched_image_uri: Optional[str] = None
    matched_image_timestamp: Optional[float] = None
    matched_image_score: Optional[float] = None
    shot_timestamp: Optional[float] = None


class MultimodalSearchResult(SearchResult):
    """Multimodal (text + image) search result with fusion scores."""

    fused_score: float
    text_score: Optional[float] = None
    image_score: Optional[float] = None
    text_rank: Optional[int] = None
    image_rank: Optional[int] = None
    match_type: str  # "both", "text_only", "image_only"
    matched_image_uri: Optional[str] = None
    matched_image_timestamp: Optional[float] = None
    matched_image_score: Optional[float] = None
    shot_timestamp: Optional[float] = None


class Webhook(BaseModel):
    """Webhook configuration."""

    webhook_id: str
    name: str
    url: str
    events: List[str]
    index_ids: Optional[List[str]] = None
    status: str
    failure_count: int = 0
    last_failure_at: Optional[str] = None
    last_success_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class WebhookWithSecret(Webhook):
    """Webhook with secret (returned on create)."""

    secret: str


class WebhookDelivery(BaseModel):
    """Webhook delivery attempt record."""

    delivery_id: str
    webhook_id: str
    event_type: str
    status: str
    attempts: int = 0
    last_attempt_at: Optional[str] = None
    next_retry_at: Optional[str] = None
    response_status_code: Optional[int] = None
    response_body: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None


class ImportJobProgress(BaseModel):
    """Import job progress tracking."""

    total_files: int = 0
    imported: int = 0
    failed: int = 0
    skipped: int = 0
    bytes_transferred: int = 0
    current_file: Optional[str] = None


class ImportJob(BaseModel):
    """Import job representation."""

    job_id: str
    connector_id: str
    target_index_id: str
    source_prefix: str
    file_pattern: str = "*"
    recursive: bool = True
    status: str
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
    progress: ImportJobProgress
    video_ids: List[str] = Field(default_factory=list)
    failed_files: List[Dict[str, str]] = Field(default_factory=list)
    skipped_files: List[Dict[str, str]] = Field(default_factory=list)


class ApiKey(BaseModel):
    """API key representation (masked)."""

    key_id: str
    key_prefix: str
    name: str
    scopes: List[str]
    created_at: Optional[str] = None
    last_used_at: Optional[str] = None
    revoked_at: Optional[str] = None
    expires_at: Optional[str] = None
    is_active: bool = True


class ApiKeyWithSecret(ApiKey):
    """API key with full key (returned on create)."""

    key: str


class SignedUrl(BaseModel):
    """Signed URL for GCS access."""

    signed_url: str
    expires_at: str


class UploadResult(BaseModel):
    """Result of video upload."""

    video_id: str
    title: str
    video_uri: str
    status: str
    message: str
    media_type: str = "video"


# =============================================================================
# Connector Models
# =============================================================================


class Connector(BaseModel):
    """Cloud storage connector representation."""

    connector_id: str
    name: str
    provider: str
    status: str
    scopes: List[str] = Field(default_factory=lambda: ["import"])
    import_mode: str = ConnectorImportMode.ALL.value
    export_base_path: Optional[str] = None
    bucket: Optional[str] = None
    region: Optional[str] = None
    storage_account: Optional[str] = None
    container: Optional[str] = None
    gcp_project_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_tested_at: Optional[str] = None
    last_test_result: Optional[str] = None
    last_test_error: Optional[str] = None


class CloudFile(BaseModel):
    """File in cloud storage (from browse)."""

    path: str
    name: str
    size_bytes: int
    last_modified: str
    content_type: Optional[str] = None
    extension: str


class TestConnectionResult(BaseModel):
    """Result of connector test."""

    success: bool
    error_message: Optional[str] = None


# =============================================================================
# Export Models
# =============================================================================


class Export(BaseModel):
    """Metadata export job representation."""

    export_id: str
    user_id: Optional[str] = None
    export_type: str
    target_id: str
    status: str
    created_at: Optional[str] = None
    gcs_uri: Optional[str] = None
    download_url: Optional[str] = None
    file_size_bytes: Optional[int] = None
    error_message: Optional[str] = None
    export_params: Optional[Dict[str, Any]] = None
    destination_type: Optional[str] = None
    destination_connector_id: Optional[str] = None
    destination_base_path: Optional[str] = None
    destination_subpath: Optional[str] = None
    destination_uri: Optional[str] = None


class ExportCreateResult(BaseModel):
    """Result of export creation."""

    export_id: str
    status: str


# =============================================================================
# Pagination
# =============================================================================


class PaginationMeta(BaseModel):
    """Pagination metadata."""

    limit: int
    has_more: bool
    next_cursor: Optional[str] = None


# =============================================================================
# Request TypedDicts
# =============================================================================


class ExecutePromptTarget(TypedDict, total=False):
    """Target specification for prompt execution."""

    type: Literal["index", "videos", "playground"]
    index_id: Optional[str]
    video_ids: Optional[List[str]]


class PromptVideoLevelConfigInput(TypedDict):
    """Input payload for prompt video-level synthesis settings."""

    instructions_text: str
    included_segment_fields: List[str]
    json_schema: Dict[str, Any]


class PromptSemanticIndexingConfigInput(TypedDict, total=False):
    """Input payload for prompt-level semantic indexing settings."""

    disabled_segment_fields: List[str]
    disabled_video_level_fields: List[str]


FilterOperator = Literal[
    "contains",
    "ends_with",
    "equals",
    "greater_equal",
    "greater_than",
    "is_empty",
    "is_not_empty",
    "item_contains",
    "item_equals",
    "length_equals",
    "length_greater",
    "length_less",
    "less_equal",
    "less_than",
    "starts_with",
]
FilterValueType = Literal["string", "integer", "number", "boolean", "array"]


class FilterCondition(TypedDict, total=False):
    """Filter condition for filter search."""

    field: str
    operator: FilterOperator
    value: Any
    type: FilterValueType


# =============================================================================
# Operation Response Models
# =============================================================================


class DeleteResponse(BaseModel):
    """Response for delete operations."""

    message: str


class ProcessingStartedResponse(BaseModel):
    """Response when video processing is started."""

    message: str


# =============================================================================
# Prompt Response Models
# =============================================================================


class PromptListResponse(BaseModel):
    """Response for listing prompts."""

    prompts: List[Prompt]
    total_count: int
    active_count: int


class TestSchemaResponse(BaseModel):
    """Response for JSON schema validation test."""

    valid: bool
    validated_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    message: str


class PromptUsageStats(BaseModel):
    """Usage statistics for a prompt."""

    prompt_id: str
    name: str
    is_active: bool
    is_in_use: bool
    created_at: str
    schema_properties_count: int


class PromptRunCostEstimate(BaseModel):
    """Estimated billing cost for a prompt run."""

    estimated_mt: float
    breakdown: Dict[str, Any]
    sufficient_balance: bool
    current_balance_mt: float


# =============================================================================
# Search Response Models
# =============================================================================


class FilterSearchResponse(BaseModel):
    """Response for filter-based search."""

    results: List[SearchResult] = Field(default_factory=list)
    next_page_token: Optional[str] = None
    total_shown: int = 0
    data: List[SearchResult] = Field(default_factory=list)
    pagination: Optional[PaginationMeta] = None

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_and_paginated_shapes(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        results = normalized.get("results")
        if results is None:
            results = normalized.get("data") or []
            normalized["results"] = results

        if normalized.get("data") is None:
            normalized["data"] = results

        pagination = normalized.get("pagination")
        if pagination is None:
            pagination = {
                "limit": len(results),
                "has_more": bool(normalized.get("next_page_token")),
                "next_cursor": normalized.get("next_page_token"),
            }
            normalized["pagination"] = pagination

        if normalized.get("next_page_token") is None:
            normalized["next_page_token"] = pagination.get("next_cursor")

        if not normalized.get("total_shown"):
            normalized["total_shown"] = len(results)

        return normalized


# =============================================================================
# Usage & Rate Limits
# =============================================================================


class UsageTotals(BaseModel):
    """Usage totals for a period."""

    total_tokens: int
    total_searches: int
    total_storage_bytes: Optional[int] = None
    total_videos_uploaded: Optional[int] = None
    total_videos_processed: Optional[int] = None
    total_segments_created: Optional[int] = None


class CurrentUsage(BaseModel):
    """Current usage for the active billing period."""

    user_id: str
    period_start: str
    period_end: str
    metrics: Dict[str, float]
    model_usage: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    auth_usage: Dict[str, Dict[str, Union[str, float]]] = Field(default_factory=dict)
    totals: UsageTotals


class UsageHistoryItem(BaseModel):
    """Usage snapshot for one historical period."""

    summary_id: str
    period_start: str
    period_end: str
    metrics: Dict[str, float]
    model_usage: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    auth_usage: Dict[str, Dict[str, Union[str, float]]] = Field(default_factory=dict)
    totals: Dict[str, int]


class UsageHistory(BaseModel):
    """Historical usage across periods."""

    user_id: str
    periods: List[UsageHistoryItem]


class UsageDetail(BaseModel):
    """Fine-grained usage event."""

    event_id: str
    metric_type: str
    value: float
    unit: str
    timestamp: str
    metadata: Optional[Dict[str, Any]] = None


class UsageBreakdown(BaseModel):
    """Usage roll-up by metric type."""

    user_id: str
    period_start: str
    period_end: str
    breakdown: Dict[str, float]
    totals: UsageTotals


class UsageMetricTypeInfo(BaseModel):
    """Metadata for a trackable usage metric type."""

    type: str
    description: str
    unit: str


class RateLimitCategoryStatus(BaseModel):
    """Rate limit counters for one endpoint category."""

    minute_used: int
    minute_limit: int
    minute_remaining: int
    hour_used: int
    hour_limit: int
    hour_remaining: int
    reset_at: int


class RateLimitStatus(BaseModel):
    """Rate limit status across categories for an authenticated user."""

    user_id: str
    plan_id: str
    categories: Dict[str, RateLimitCategoryStatus]


# =============================================================================
# Webhook Response Models
# =============================================================================


class WebhookTestResponse(BaseModel):
    """Response from webhook test."""

    success: bool
    status_code: Optional[int] = None
    error: Optional[str] = None


class RotateSecretResponse(BaseModel):
    """Response from webhook secret rotation."""

    webhook_id: str
    new_secret: str


# =============================================================================
# Video Batch Response Models
# =============================================================================


class VideoStatus(BaseModel):
    """Video status for batch operations."""

    video_id: str
    status: str
    processing_status: Optional[List[PromptRunProcessingStatus]] = None


class VideoSegments(BaseModel):
    """Video with its segments for batch operations."""

    video_id: str
    segments: List[Segment]
