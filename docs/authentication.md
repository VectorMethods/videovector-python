# Authentication and Configuration

The SDK supports API key auth for server-to-server workflows and JWT bearer auth for endpoints that require a user session, such as API key management.

## API Key Auth

```python
import os

from videovector import VideoVector

client = VideoVector(api_key=os.environ["VIDEO_VECTOR_API_KEY"])
```

## Bearer Auth

```python
import os

from videovector import VideoVector

client = VideoVector(bearer_token=os.environ["VIDEO_VECTOR_BEARER_TOKEN"])
```

## Environment Variables

- `VIDEO_VECTOR_API_KEY`
- `VIDEO_VECTOR_BEARER_TOKEN`
- `VIDEO_VECTOR_AUTH_MODE`
- `VIDEO_VECTOR_BASE_URL`
- `VIDEO_VECTOR_TIMEOUT`
- `VIDEO_VECTOR_MAX_RETRIES`

The default base URL is `https://api.vectormethods.com/api/v2`. Override it with `VIDEO_VECTOR_BASE_URL` or the `base_url` constructor argument when targeting another deployment.

## Secret Handling

Do not log full API keys, bearer tokens, cloud provider credentials, webhook signing secrets, or signed export URLs. Values returned by API key creation, API key rotation, webhook creation, and webhook secret rotation should be persisted immediately to your own secret store.
