# Authentication and Configuration

The SDK supports two first-class authentication choices:

- API keys for unattended server-to-server workloads.
- WorkOS OAuth access tokens when an application acts for a signed-in
  VideoVector account.

Firebase ID tokens remain supported for the small set of Firebase-session-only
routes, including API key administration. Do not send an API key and a bearer
credential together unless the constructor's explicit `auth_mode` selects one.

## API Key Auth

```python
import os

from videovector import VideoVector

client = VideoVector(api_key=os.environ["VIDEO_VECTOR_API_KEY"])
```

API keys remain the recommended option for services, workers, CI jobs, and
other unattended integrations. Their configured API-key scopes continue to be
enforced by the API.

## WorkOS OAuth

Use OAuth when the caller already has a signed-in VideoVector user and actions
should run as that account. WorkOS issues the token; VideoVector validates it
and continues to enforce its own account state, billing, and plan entitlements.
OAuth users receive tenant-account access rather than legacy API-key scopes.
OAuth does not grant platform-admin access or satisfy Firebase-only routes.
The current rate-limit status and refresh routes also require an API key or
Firebase ID token; all other tenant-scoped SDK resources accept WorkOS OAuth.

The public authorization contract is discoverable at:

```text
https://api.vectormethods.com/.well-known/oauth-protected-resource/mcp
```

The canonical OAuth resource is:

```text
https://api.vectormethods.com/mcp
```

### Long-lived clients

Use a maintained OAuth/OIDC client library such as Authlib in the host
application for Authorization Code + PKCE, DCR when applicable, refresh-token
rotation, and secure storage; do not recreate those protocol operations around
the SDK. Pass the SDK a token-provider callable that returns the current raw
access token. The callable is invoked for each outbound attempt so retries do
not reuse a token that the provider has already rotated.

```python
from videovector import VideoVector

def current_access_token() -> str:
    # oauth_adapter is application-owned. Delegate expiry checks, refresh, and
    # storage to the maintained OAuth library behind it.
    return oauth_adapter.current_access_token()

client = VideoVector(oauth_token_provider=current_access_token)
```

`AsyncVideoVector` accepts a synchronous callable for an in-memory token lookup
or an async callable when refresh may perform I/O:

```python
from videovector import AsyncVideoVector

async def current_access_token() -> str:
    return await oauth_adapter.current_access_token()

client = AsyncVideoVector(oauth_token_provider=current_access_token)
```

The token provider must return only the raw RFC 6750 bearer token, without the
`Bearer ` prefix. It owns refresh synchronization and secure refresh-token
storage. Provider failures and malformed results fail before an HTTP request is
sent, and the SDK does not include provider exception text in its errors.
`AuthenticationError.error_code` distinguishes `oauth_token_provider_failed`,
`oauth_token_provider_invalid_result`, and the synchronous client's
`oauth_token_provider_async_result` configuration error.

The SDK intentionally does not own interactive authorization. VideoVector's
flow includes browser consent and a Firebase-authenticated identity handoff;
embedding that flow in a general-purpose server SDK would add browser control,
callback hosting, and refresh-token storage to applications that do not need
them. This boundary also lets applications use established libraries and their
existing session lifecycle.

### Short-lived commands

A raw access token can be supplied directly for a short-lived command:

```python
import os

from videovector import VideoVector

client = VideoVector(bearer_token=os.environ["VIDEO_VECTOR_BEARER_TOKEN"])
```

Static access tokens expire and are not refreshed by the SDK. Do not embed
access or refresh tokens in source code, command history, logs, or persistent
environment files.

## Firebase Session Auth

API key creation, rotation, revocation, and deletion remain Firebase-only. For
those endpoints, pass a current verified Firebase ID token through
`bearer_token`. A WorkOS access token intentionally does not satisfy this
stricter identity boundary.

`client.rate_limits.get_status()` and `client.rate_limits.refresh()` currently
use the backend's legacy authenticated-user dependency. Use an API key or
Firebase ID token for those two calls until that backend boundary is migrated
to tenant OAuth.

## Credential Selection

By default, configure exactly one credential source. A static `bearer_token`
and `oauth_token_provider` cannot be combined. If an integration deliberately
loads an API key and one bearer source, `auth_mode="api_key"` or
`auth_mode="bearer"` establishes deterministic precedence; the unselected
provider is never called.

Explicit constructor credentials are authoritative and ignore unrelated
ambient credential and auth-mode environment variables.

## Environment Variables

- `VIDEO_VECTOR_API_KEY`
- `VIDEO_VECTOR_BEARER_TOKEN`
- `VIDEO_VECTOR_AUTH_MODE`
- `VIDEO_VECTOR_BASE_URL`
- `VIDEO_VECTOR_TIMEOUT`
- `VIDEO_VECTOR_MAX_RETRIES`
- `VIDEO_VECTOR_MAX_RETRY_DELAY`

There is intentionally no environment variable for a token-provider callable.
The default base URL is `https://api.vectormethods.com/api/v2`. Override it with
`VIDEO_VECTOR_BASE_URL` or the `base_url` constructor argument when targeting
another deployment.

## Secret Handling

Do not log full API keys, access tokens, refresh tokens, Firebase ID tokens,
cloud provider credentials, webhook signing secrets, or signed export URLs.
Export status `download_url` values are validated authenticated API endpoints;
only the explicit `client.exports.download_url(...)` mint call returns a
short-lived bearer URL. That mint is accepted only from the configured HTTPS
API origin with the exact export-bound path and token query. Values returned by
API key creation, API key rotation, webhook creation, and webhook secret
rotation should be persisted immediately to your own secret store.
