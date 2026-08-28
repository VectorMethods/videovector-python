# Changelog

## Unreleased

## 1.1.0

- Added synchronous and asynchronous WorkOS OAuth token-provider support while
  preserving API keys and static bearer tokens. Providers are invoked for each
  wire attempt, fail closed before network I/O, and keep refresh, browser login,
  and secure token storage in the host application's OAuth library.
- Removed request credentials from translated transport-error chains, response
  request metadata, and traceback-local header dictionaries before SDK errors
  leave the transport boundary.
- Added the typed synchronous and asynchronous simplified workflow surface for
  upload, prompt definition, processing, stable search pagination, and
  searchable-run polling.
- Changed idempotent multipart request retries to rewind seekable streams rather
  than buffering an entire media upload in memory. Non-seekable streams are sent
  once and are not retried.
- Expanded canonical search-result models so workflow search preserves prompt
  provenance, multimodal scores, preview media, and matched-image fields.
- Added typed, resumable index and video deletion contracts. Synchronous and
  asynchronous `delete(...)` calls now return the durable deletion identity
  and status, and `get_deletion(...)` reads progress until `deleted`.
- Added run-scoped batch segment retrieval through
  `BatchVideoSegmentsTarget` and synchronous/asynchronous
  `videos.batch_segments_for_targets(...)`; `VideoSegments` now exposes the
  resolved `run_id`.
- Added `force_refresh` to synchronous/asynchronous
  `videos.get_signed_url(...)` for explicit bounded-grant rotation.
- Made retry delays understand both `Retry-After` wire formats, clamp to a
  configurable ceiling, and remain cancellation-aware in async clients.
- Rejected reserved custom headers case-insensitively and unified sync/async
  default-header construction.
- Bounded GCS connector credential files to 64 KiB and snapshot them into
  immutable multipart bytes so idempotent retries replay the exact body.
- Fixed immutable-release provenance to attest the checksum-reviewed `uv`
  installer actually used by CI instead of requiring intentionally removed,
  unused `pip`.
- Added an optional `source_connector_id` argument to synchronous and asynchronous
  `videos.create` calls. Existing public and platform-managed GCS calls keep the
  same request payload when the argument is omitted.
- Preserved structured backend quota and LLM-budget error codes, messages,
  request IDs, and details on `RateLimitError` after automatic retries are
  exhausted.
- Preserved canonical GCS source fields on parsed search results alongside
  their signed playback fields.
- Added synchronous and asynchronous authenticated export streaming with a
  backend-aligned 64 MiB local byte ceiling, exact full-response validation,
  no partial-response retry, and atomic path writes.
- Made synchronous and asynchronous `exports.download_url(...)` explicitly
  mint bounded bearer URLs through the authenticated `/download-url` endpoint.
  Export status `download_url` fields now unambiguously represent the
  authenticated `/download` endpoint and never a bearer credential.
- Bound minted export capabilities to the configured HTTPS API origin, exact
  export path, and one bounded token query; bearer response models and malformed
  JSON failures now redact credentials from representations and exceptions.
- Made an explicit constructor credential authoritative so an unrelated
  ambient API key, bearer token, or auth-mode variable cannot switch or poison
  the selected authentication flow.

## 1.0.0

- Initial public VideoVector Python SDK repository.
- Includes typed sync and async clients, resource wrappers, pagination helpers, retries, idempotency support, examples, and release workflows.
