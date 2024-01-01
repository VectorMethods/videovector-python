# Examples Guide

Examples in this repository are production-shaped templates. They use real SDK calls and realistic prompt/schema patterns, but all credentials and resource identifiers are read from environment variables.

## Running an Example

```bash
export VIDEO_VECTOR_API_KEY=<VIDEO_VECTOR_API_KEY>
export VIDEO_VECTOR_INDEX_ID=idx_example
python examples/01_quickstart_upload_search.py
```

Some examples require additional values, such as `VIDEO_VECTOR_MEDIA_FILE`, connector credentials, or webhook URLs. Each file declares its required environment variables near the top of `main()`.

## Safety Rules

- Use test or least-privilege credentials when experimenting.
- Use idempotency keys for retryable writes.
- Point `VIDEO_VECTOR_BASE_URL` to the intended deployment before running against production data.
- Review connector scopes before granting import or export access.

