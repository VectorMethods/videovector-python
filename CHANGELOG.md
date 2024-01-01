# Changelog

## Unreleased

- Added an optional `source_connector_id` argument to synchronous and asynchronous
  `videos.create` calls. Existing public and platform-managed GCS calls keep the
  same request payload when the argument is omitted.
- Preserved structured backend quota and LLM-budget error codes, messages, and
  details on `RateLimitError` after automatic retries are exhausted.

## 1.0.0

- Initial public VideoVector Python SDK repository.
- Includes typed sync and async clients, resource wrappers, pagination helpers, retries, idempotency support, examples, and release workflows.
