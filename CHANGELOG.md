# Changelog

## 1.1.0

- Added an optional `source_connector_id` argument to synchronous and asynchronous
  `videos.create` calls. Existing public and platform-managed GCS calls keep the
  same request payload when the argument is omitted.
- Preserved structured backend quota and LLM-budget error codes, messages, and
  details on `RateLimitError` after automatic retries are exhausted.
- Added synchronous and asynchronous authenticated export streaming with a
  backend-aligned 64 MiB local byte ceiling, exact full-response validation,
  no partial-response retry, and atomic path writes.
- Made an explicit constructor credential authoritative so an unrelated
  ambient API key, bearer token, or auth-mode variable cannot switch or poison
  the selected authentication flow.

## 1.0.0

- Initial public VideoVector Python SDK repository.
- Includes typed sync and async clients, resource wrappers, pagination helpers, retries, idempotency support, examples, and release workflows.
