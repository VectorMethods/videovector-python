# VideoVector Python SDK

Official Python SDK for the VideoVector API.

This repository is the public source of truth for the Python package, SDK documentation, examples, tests, and release workflow. It does not contain backend, MCP, frontend, deployment, or internal operations code.

## Installation

```bash
pip install videovector
```

For local development from this repository:

```bash
pip install -e ".[dev]"
```

## Quickstart

```python
import os

from videovector import VideoVector

with VideoVector(api_key=os.environ["VIDEO_VECTOR_API_KEY"]) as client:
    upload = client.workflow.upload(
        file="/path/to/video.mp4",
        index_name="Field Review Clips",
    )

    prompt = client.workflow.define(
        "Extract products, sentiment, and visible brand names"
    )
    run = client.workflow.process(
        prompt_id=prompt.prompt_id,
        video_ids=[upload.video.video_id],
    )
    client.workflow.wait_until_searchable(run.run.run_id)

    results = client.workflow.search(
        query="employee restocking shelves near checkout",
        video_ids=[upload.video.video_id],
        limit=10,
    )

    for result in results:
        print(result.video_id, result.start_time, result.similarity_score)
```

## Configuration

The SDK reads credentials and operational settings from constructor arguments or environment variables.

| Setting | Environment variable | Notes |
|---|---|---|
| API key | `VIDEO_VECTOR_API_KEY` | Recommended for server-to-server workflow calls. |
| Static bearer token | `VIDEO_VECTOR_BEARER_TOKEN` | A short-lived WorkOS OAuth access token or Firebase ID token. Prefer a provider for long-lived OAuth clients. |
| OAuth token provider | Constructor only | Callable that obtains a current WorkOS access token for each HTTP attempt. |
| Auth mode | `VIDEO_VECTOR_AUTH_MODE` | Optional; use `api_key` or `bearer` when an API key and one bearer source are both configured. |
| Base URL | `VIDEO_VECTOR_BASE_URL` | Defaults to `https://api.vectormethods.com/api/v2`. |
| Timeout | `VIDEO_VECTOR_TIMEOUT` | Seconds; default is `60`. |
| Retries | `VIDEO_VECTOR_MAX_RETRIES` | Default is `3`. |
| Maximum retry delay | `VIDEO_VECTOR_MAX_RETRY_DELAY` | Seconds; default is `300`. Applies to exponential backoff and both `Retry-After` formats. |

Explicit constructor arguments override environment values:

```python
from videovector import VideoVector

client = VideoVector(
    api_key="<VIDEO_VECTOR_API_KEY>",
    base_url="https://api.vectormethods.com/api/v2",
    timeout=90,
    max_retries=5,
    max_retry_delay=120,
    custom_headers={"X-Trace-Context": "request-group-1"},
)
```

Configure one auth mode at a time. If an API key and one bearer source are both
present, set `auth_mode` or `VIDEO_VECTOR_AUTH_MODE`. A static bearer token and
an OAuth token provider are mutually exclusive because they represent the same
wire credential.
Custom headers cannot override authentication, content framing, user agent,
idempotency, or other SDK-owned headers.

### WorkOS OAuth

OAuth is appropriate when an application acts for a signed-in VideoVector user.
The SDK accepts an externally managed WorkOS access token, but deliberately does
not open a browser, run Firebase login, perform DCR/PKCE, or persist refresh
tokens. Keep that lifecycle in the host application's established OAuth/OIDC
library and secure credential store.

For a long-lived synchronous client, pass a callable that returns a current raw
access token. The SDK invokes it once for every wire attempt, including retries:

```python
from videovector import VideoVector

# Application-owned adapter around Authlib (or another maintained OAuth
# library). This is not an SDK or Authlib method: the adapter must refresh
# before expiry and return only the raw token, without the "Bearer " prefix.
def current_access_token() -> str:
    return oauth_adapter.current_access_token()

client = VideoVector(oauth_token_provider=current_access_token)
```

The async client accepts either a non-blocking synchronous callable or an async
callable:

```python
from videovector import AsyncVideoVector

async def current_access_token() -> str:
    return await oauth_adapter.current_access_token()

client = AsyncVideoVector(oauth_token_provider=current_access_token)
```

The authorization server and resource are discoverable from
`https://api.vectormethods.com/.well-known/oauth-protected-resource/mcp`.
Production access tokens are issued for the canonical resource
`https://api.vectormethods.com/mcp` and are accepted on tenant-scoped SDK
operations. OAuth represents the signed-in account and is not restricted by
legacy API-key scopes; existing VideoVector billing, plan entitlements, and
account state remain authoritative. Platform-admin and Firebase-session-only
operations remain excluded. In particular, `client.api_keys` requires a
verified Firebase ID token, while the current `client.rate_limits` backend
routes require an API key or Firebase ID token rather than a WorkOS access
token.

## Resource Overview

- `client.workflow`: simplified upload, prompt definition, processing, stable search pagination, and searchable-run polling.
- `client.videos`: upload, retrieve, process, segments, batch helpers, and playground media.
- `client.indexes`: index CRUD, paginated index videos, and prompt-run history.
- `client.prompts`: prompt CRUD, schema validation, usage, video-level synthesis, and semantic indexing config.
- `client.prompt_runs`: estimate, execute, poll, retrieve results, inspect failures, retry failed segments, and inspect LLM calls.
- `client.search`: text, image, multimodal, filter, multi-run, and playground search.
- `client.connectors`: GCS, S3, and Azure connector creation, testing, browsing, and deletion.
- `client.import_jobs`: bulk import from configured connectors.
- `client.exports`: index and prompt-run metadata exports with bounded authenticated streaming.
- `client.webhooks`: webhook CRUD, delivery inspection, retries, event discovery, and secret rotation.
- `client.api_keys`: API key CRUD, rotate, revoke, and delete with a verified
  Firebase ID token (WorkOS OAuth is intentionally not accepted here).
- `client.usage`: usage metrics, history, details, and breakdowns.
- `client.rate_limits`: rate-limit status and refresh with an API key or
  Firebase ID token; the current backend routes do not accept WorkOS OAuth.

Endpoint-by-endpoint coverage is documented in [docs/backend-parity-matrix.md](docs/backend-parity-matrix.md).

Fetch segments for exact prompt runs without mixing results from a newer run:

```python
from videovector import BatchVideoSegmentsTarget

responses = client.videos.batch_segments_for_targets(
    [
        BatchVideoSegmentsTarget(video_id="video_123", run_id="run_123"),
        BatchVideoSegmentsTarget(video_id="video_456"),
    ]
)
for response in responses:
    print(response.video_id, response.run_id, len(response.segments))
```

`videos.batch_segments(video_ids)` remains available for legacy unscoped
lookups. If a bounded media grant has been exhausted after a failed load,
request explicit rotation with
`videos.get_signed_url(gcs_uri, force_refresh=True)`.

Completed first-party exports can be streamed to disk without buffering the
file or retrying a partially delivered response:

```python
export = client.exports.wait_for_completion("export_123")
client.exports.download(export.export_id, "metadata.json")
```

Use `iter_download` when your application needs to process chunks directly.
Connector-delivered exports remain in the configured destination.

Export status models expose an authenticated `/download` endpoint in
`export.download_url`; that field is not a bearer credential. When a browser or
another bounded client specifically needs a short-lived bearer URL, mint one
explicitly and avoid logging or persisting it:

```python
bounded_url = client.exports.download_url(export.export_id)
```

The SDK accepts this capability only from the configured HTTPS API origin and
only when its path, export ID, query shape, and bounded token match the backend
contract. The returned string is intentionally unwrapped for the caller, so it
must still be handled like a credential.

## Pagination

Paginated endpoints return `SyncPage[T]` or `AsyncPage[T]`.

```python
page = client.indexes.list_videos("idx_archive", limit=50)
for video in page.auto_paging_iter():
    print(video.video_id)
```

```python
from videovector import AsyncVideoVector

async with AsyncVideoVector(api_key="<VIDEO_VECTOR_API_KEY>") as client:
    page = await client.videos.list_playground(limit=25)
    async for video in page.auto_paging_iter():
        print(video.video_id)
```

## Error Handling

SDK exceptions map to API status classes:

- `AuthenticationError` for `401`
- `AuthorizationError` for `403`
- `NotFoundError` for `404`
- `ValidationError` for validation and other non-specialized `4xx` responses
- `RateLimitError` for `429`, including `retry_after` when provided
- `ConflictError` for `409`
- `ExternalServiceError` for `5xx`
- `TimeoutError`, `ConnectionError`, and `VideoVectorError` for transport or generic SDK failures

```python
import os

from videovector import RateLimitError, ValidationError, VideoVector

try:
    with VideoVector(api_key=os.environ["VIDEO_VECTOR_API_KEY"]) as client:
        client.search.text(index_id="idx_archive", query="")
except ValidationError as exc:
    print(exc.error_code, exc.message)
except RateLimitError as exc:
    print("retry after", exc.retry_after)
```

## Retry and Idempotency

Automatic retries are enabled for:

- idempotent methods: `GET`, `HEAD`, `OPTIONS`, `PUT`, and `DELETE`
- any request that includes an explicit `idempotency_key`

The SDK accepts `Retry-After` as either delay-seconds or an HTTP date and
clamps the wait to `max_retry_delay`. Async waits propagate cancellation
immediately. Idempotent multipart retries replay one pre-encoded body rather
than rereading a file object.

For non-idempotent operations, pass an idempotency key when retrying is safe:

```python
run = client.prompt_runs.execute(
    prompt_id="prompt_scene_review",
    target={"type": "index", "index_id": "idx_archive"},
    idempotency_key="scene-review-2026-05-07",
)
```

## Examples

The [examples](examples) directory contains runnable, environment-driven examples for common and advanced workflows:

- quickstart upload/search
- sync and async client usage
- custom prompt and schema design
- video-level synthesis
- text, image, multimodal, and filter search
- GCS, S3, and Azure connectors
- run-scoped batch segment retrieval and bounded playback grants
- import jobs, exports, webhooks, idempotency, failed-segment recovery, usage, and rate limits

Examples intentionally use placeholders and environment variables. Do not hardcode credentials in application code.

## Development

Use the reviewed `uv==0.11.29` installer recorded in
`scripts/install_reviewed_uv.sh`.

```bash
uv pip install --python "$(command -v python)" --require-hashes -r requirements-dev.lock
uv pip install --python "$(command -v python)" --no-deps --no-build-isolation -e .
ruff check videovector tests examples
mypy videovector
pytest -q tests
python -m build --no-isolation
python -m twine check dist/*
```

Optional local secret scan:

```bash
gitleaks detect --source . --no-git --redact
```

## Unsupported Surfaces

This SDK intentionally does not wrap:

- internal operations endpoints
- billing endpoints
- MCP endpoints
- raw binary preview helpers such as GIF and thumbnail routes
- server-sent processing event streams

Use the REST API directly for unsupported public helper routes, and use the separate MCP package for MCP-specific workflows.

## License

MIT. See [LICENSE](LICENSE).
