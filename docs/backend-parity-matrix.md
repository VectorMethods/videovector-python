# VideoVector Python SDK Backend Parity Matrix

This document maps the Python SDK surface (`videovector`) to backend API endpoints (`/api/v2/*`) and clarifies intentionally unsupported surfaces.

## Scope

- Backend base path: `/api/v2`
- SDK package: `videovector`
- Auth modes supported by SDK:
  - API key (`X-API-Key`)
  - JWT bearer (`Authorization: Bearer ...`)

## Current Resource Coverage

| SDK Method | HTTP | Endpoint | Response Model | Backend Auth Requirement |
|---|---|---|---|---|
| `videos.create` | `POST` | `/videos` | `Video` | `write` (optional `source_connector_id` for a caller-owned private GCS import connector) |
| `videos.upload` | `POST` | `/videos/upload` | `UploadResult` | `write` |
| `videos.retrieve` | `GET` | `/videos/{video_id}` | `Video` | `read` |
| `videos.delete` | `DELETE` | `/videos/{video_id}` | `DeleteResponse` | `admin` |
| `videos.process` | `POST` | `/videos/{video_id}/process` | `ProcessingStartedResponse` | `write` |
| `videos.list_segments` | `GET` | `/videos/{video_id}/segments` | `SyncPage[Segment]`/`AsyncPage[Segment]` | `read` |
| `videos.batch_retrieve` | `POST` | `/videos/batch` | `List[VideoWithDetails]` | `read` |
| `videos.batch_status` | `POST` | `/videos/batch/status` | `List[VideoStatus]` | `read` |
| `videos.batch_segments` | `POST` | `/videos/batch/segments` | `List[VideoSegments]` | `read` |
| `videos.get_signed_url` | `POST` | `/videos/signed-url` | `SignedUrl` | `read` |
| `videos.list_prompt_runs` | `GET` | `/videos/{video_id}/prompt-runs` | `List[PromptRun]` | `read` |
| `indexes.create` | `POST` | `/indexes` | `Index` | `write` |
| `indexes.retrieve` | `GET` | `/indexes/{index_id}` | `Index` | `search` |
| `indexes.list` | `GET` | `/indexes` | `List[Index]` | `search` |
| `indexes.delete` | `DELETE` | `/indexes/{index_id}` | `DeleteResponse` | `admin` |
| `indexes.list_videos` | `GET` | `/indexes/{index_id}/videos` | `SyncPage[Video]`/`AsyncPage[Video]` | `read` |
| `indexes.list_prompt_runs` | `GET` | `/indexes/{index_id}/prompt-runs` | `SyncPage[PromptRun]`/`AsyncPage[PromptRun]` | `read` |
| `prompts.create` | `POST` | `/prompts` | `Prompt` | `write` |
| `prompts.retrieve` | `GET` | `/prompts/{prompt_id}` | `Prompt` | `read` |
| `prompts.list` | `GET` | `/prompts` | `PromptListResponse` | `read` |
| `prompts.update` | `PUT` | `/prompts/{prompt_id}` | `Prompt` | `write` |
| `prompts.delete` | `DELETE` | `/prompts/{prompt_id}` | `DeleteResponse` | `admin` |
| `prompts.test_schema` | `POST` | `/prompts/test-schema` | `TestSchemaResponse` | `write` |
| `prompts.get_usage` | `GET` | `/prompts/{prompt_id}/usage` | `PromptUsageStats` | `read` |
| `prompt_runs.execute` | `POST` | `/prompt-runs/execute` | `PromptRun` | `write` |
| `prompt_runs.estimate` | `POST` | `/prompt-runs/estimate` | `PromptRunCostEstimate` | `read` |
| `prompt_runs.list` | `GET` | `/prompt-runs` | `List[PromptRun]` | `read` |
| `prompt_runs.retrieve` | `GET` | `/prompt-runs/{run_id}` | `PromptRun` | `read` |
| `prompt_runs.list_results` | `GET` | `/prompt-runs/{run_id}/results` | `SyncPage[SegmentRunResult]`/`AsyncPage[SegmentRunResult]` | `read` |
| `prompt_runs.get_video_result` | `GET` | `/prompt-runs/{run_id}/videos/{video_id}/video-result` | `PromptRunVideoResult` | `read` |
| `prompt_runs.get_failed_segments` | `GET` | `/prompt-runs/{run_id}/failed-segments` | `PromptRunFailedSegmentsManifest` | `read` |
| `prompt_runs.retry_segment` | `POST` | `/prompt-runs/{run_id}/videos/{video_id}/segments/{segment_id}/retry` | `PromptRunSegmentRetry` | `write` |
| `prompt_runs.get_segment_retry_status` | `GET` | `/prompt-runs/{run_id}/videos/{video_id}/segments/{segment_id}/retries/{retry_id}` | `PromptRunSegmentRetryStatus` | `read` |
| `prompt_runs.get_llm_calls` | `GET` | `/prompt-runs/{run_id}/llm-calls` | `List[LlmCall]` | `read` |
| `search.text` | `POST` | `/indexes/{index_id}/search` | `List[SearchResult]` | `search` |
| `search.image` | `POST` | `/indexes/{index_id}/image-search` | `List[ImageSearchResult]` | `search` |
| `search.multimodal` | `POST` | `/indexes/{index_id}/multimodal-search` | `List[MultimodalSearchResult]` | `search` |
| `search.filter` | `POST` | `/search/filter/{index_id}` | `FilterSearchResponse` | `search` |
| `search.filter_playground` | `POST` | `/search/filter/playground` | `FilterSearchResponse` | `search` |
| `search.multi_run` | `POST` | `/search/multi-run` | `List[SearchResult]` | `search` |
| `search.playground` | `POST` | `/playground/search` | `List[SearchResult]` | `search` |
| `connectors.create_gcs` | `POST` | `/connectors/gcs` | `Connector` | `write` |
| `connectors.create_s3` | `POST` | `/connectors/s3` | `Connector` | `write` |
| `connectors.create_azure` | `POST` | `/connectors/azure` | `Connector` | `write` |
| `connectors.retrieve` | `GET` | `/connectors/{connector_id}` | `Connector` | `read` |
| `connectors.list` | `GET` | `/connectors` | `List[Connector]` | `read` |
| `connectors.delete` | `DELETE` | `/connectors/{connector_id}` | `DeleteResponse` | `admin` |
| `connectors.test` | `POST` | `/connectors/{connector_id}/test` | `TestConnectionResult` | `write` |
| `connectors.browse` | `POST` | `/connectors/{connector_id}/browse` | `List[CloudFile]` | `read` |
| `import_jobs.create` | `POST` | `/import-jobs` | `ImportJob` | `write` |
| `import_jobs.retrieve` | `GET` | `/import-jobs/{job_id}` | `ImportJob` | `read` |
| `import_jobs.list` | `GET` | `/import-jobs` | `List[ImportJob]` | `read` |
| `import_jobs.cancel` | `POST` | `/import-jobs/{job_id}/cancel` | `ImportJob` | `write` |
| `exports.create_index_export` | `POST` | `/exports/index/{index_id}` | `ExportCreateResult` | `write` |
| `exports.create_prompt_run_export` | `POST` | `/exports/prompt-run/{run_id}` | `ExportCreateResult` | `write` |
| `exports.retrieve` | `GET` | `/exports/{export_id}` | `Export` | `read` |
| `exports.list` | `GET` | `/exports` | `List[Export]` | `read` |
| `exports.download_url` | `POST` | `/exports/{export_id}/download-url` | validated `Optional[str]` bearer capability | `read` |
| `exports.iter_download` / `exports.download` | `GET` | `/exports/{export_id}/download` | bounded byte stream | `read` |
| `webhooks.create` | `POST` | `/webhooks` | `WebhookWithSecret` | `write` |
| `webhooks.retrieve` | `GET` | `/webhooks/{webhook_id}` | `Webhook` | `read` |
| `webhooks.list` | `GET` | `/webhooks` | `List[Webhook]` | `read` |
| `webhooks.update` | `PATCH` | `/webhooks/{webhook_id}` | `Webhook` | `write` |
| `webhooks.delete` | `DELETE` | `/webhooks/{webhook_id}` | `DeleteResponse` | `admin` |
| `webhooks.rotate_secret` | `POST` | `/webhooks/{webhook_id}/rotate-secret` | `RotateSecretResponse` | `write` |
| `webhooks.test` | `POST` | `/webhooks/{webhook_id}/test` | `WebhookTestResponse` | `write` |
| `webhooks.list_deliveries` | `GET` | `/webhooks/{webhook_id}/deliveries` | `List[WebhookDelivery]` | `read` |
| `webhooks.get_delivery` | `GET` | `/webhooks/deliveries/{delivery_id}` | `WebhookDelivery` | `read` |
| `webhooks.retry_delivery` | `POST` | `/webhooks/deliveries/{delivery_id}/retry` | `WebhookDelivery` | `write` |
| `webhooks.list_events` | `GET` | `/webhooks/events` | `List[str]` | Public endpoint |
| `api_keys.create` | `POST` | `/api-keys` | `ApiKeyWithSecret` | JWT required |
| `api_keys.retrieve` | `GET` | `/api-keys/{key_id}` | `ApiKey` | JWT required |
| `api_keys.list` | `GET` | `/api-keys` | `List[ApiKey]` | JWT required |
| `api_keys.delete` | `DELETE` | `/api-keys/{key_id}` | `DeleteResponse` | JWT required |
| `api_keys.revoke` | `POST` | `/api-keys/{key_id}/revoke` | `ApiKey` | JWT required |
| `api_keys.rotate` | `POST` | `/api-keys/{key_id}/rotate` | `ApiKeyWithSecret` | JWT required |
| `videos.list_playground` | `GET` | `/playground/videos` | `SyncPage[Video]`/`AsyncPage[Video]` | `read` |
| `usage.get_current` | `GET` | `/usage` | `CurrentUsage` | `read` |
| `usage.get_history` | `GET` | `/usage/history` | `UsageHistory` | `read` |
| `usage.get_details` | `GET` | `/usage/details` | `List[UsageDetail]` | `read` |
| `usage.get_breakdown` | `GET` | `/usage/breakdown` | `UsageBreakdown` | `read` |
| `usage.get_metric_types` | `GET` | `/usage/metric-types` | `List[UsageMetricTypeInfo]` | Public endpoint |
| `rate_limits.get_status` | `GET` | `/rate-limit/status` | `RateLimitStatus` | authenticated user |
| `rate_limits.refresh` | `POST` | `/rate-limit/refresh` | `RateLimitStatus` | authenticated user |

## Explicitly Unsupported in This SDK

The following backend surfaces are intentionally out of scope for this SDK release:

- Internal operations:
  - `/internal/prompt-run-queue/metrics`
  - `/internal/prompt-run-queue/dead-letter/replay`
- Raw media binary helper endpoints:
  - `/videos/{video_id}/gif`
  - `/videos/segments/{segment_id}/thumbnail`
- Server-sent event stream:
  - `/processing/events/stream`
- MCP-specific endpoints:
  - `/mcp/*`
- Billing endpoints:
  - `/billing/*`
- Indexes are prompt-agnostic containers; prompt selection happens on prompt-run execution.

## Notes

- Endpoint auth requirements are enforced by backend middleware and should be treated as authoritative.
- Some endpoints are authenticated via either API key or JWT bearer, while `/api-keys/*` requires JWT bearer specifically.
- The public `admin` API-key scope means full access within the owning account; it never grants platform-administrator access.
- Omitting `source_connector_id` from `videos.create` preserves the original wire payload and remains the correct call for public GCS objects and server-managed uploads/imports.
