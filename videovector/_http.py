"""
VideoVector SDK HTTP Client.

Low-level HTTP client with retry logic, authentication, and error handling.
"""

from __future__ import annotations

import time
from typing import Any, AsyncIterator, Dict, Iterator, Optional

import httpx

from ._config import ClientConfig
from ._exceptions import (
    ConnectionError,
    RateLimitError,
    TimeoutError,
    VideoVectorError,
    _raise_for_status,
)
from ._version import __version__


class SyncHttpClient:
    """Synchronous HTTP client for VideoVector API."""

    def __init__(self, config: ClientConfig) -> None:
        self._config = config
        self._client = httpx.Client(
            base_url=config.base_url,
            timeout=httpx.Timeout(config.timeout),
            headers=self._default_headers(),
        )

    @property
    def base_url(self) -> str:
        """Configured API base URL used to validate security-sensitive responses."""
        return self._config.base_url

    def _default_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": f"videovector-python/{__version__}",
        }
        if self._config.auth_mode == "bearer" and self._config.bearer_token:
            headers["Authorization"] = f"Bearer {self._config.bearer_token}"
        elif self._config.auth_mode == "api_key" and self._config.api_key:
            headers["X-API-Key"] = self._config.api_key
        elif self._config.bearer_token:
            headers["Authorization"] = f"Bearer {self._config.bearer_token}"
        elif self._config.api_key:
            headers["X-API-Key"] = self._config.api_key

        custom_headers = {
            key: value
            for key, value in self._config.custom_headers.items()
            if key.lower() != "content-type"
        }
        headers.update(custom_headers)
        return headers

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        """Execute HTTP request with retry logic."""
        normalized_method = method.upper()
        allow_retry = _should_retry_request(normalized_method, idempotency_key)

        request_headers = {}
        if headers:
            request_headers.update(headers)
        if idempotency_key:
            request_headers["Idempotency-Key"] = idempotency_key

        # Remove Content-Type for multipart uploads so httpx can set boundary.
        if files:
            request_headers = {
                key: value
                for key, value in request_headers.items()
                if key.lower() != "content-type"
            }

        last_exception: Optional[Exception] = None
        retry_count = 0

        while retry_count <= self._config.max_retries:
            try:
                response = self._client.request(
                    method=method,
                    url=endpoint,
                    params=_clean_params(params),
                    json=json,
                    data=data,
                    files=files,
                    headers=request_headers if request_headers else None,
                )

                if response.status_code == 429:
                    retry_after = _get_retry_after(response)
                    if allow_retry and retry_count < self._config.max_retries:
                        time.sleep(retry_after)
                        retry_count += 1
                        continue
                    _raise_rate_limit_response(response, retry_after=retry_after)

                if (
                    allow_retry
                    and response.status_code >= 500
                    and retry_count < self._config.max_retries
                ):
                    retry_count += 1
                    time.sleep(2**retry_count)
                    continue

                if response.status_code >= 400:
                    body = _decode_error_body(response)
                    _raise_for_status(response.status_code, body)

                if response.status_code == 204:
                    return {}

                return _decode_json_response(response)

            except httpx.TimeoutException as e:
                last_exception = TimeoutError(f"Request timed out: {e}")
                if allow_retry and retry_count < self._config.max_retries:
                    retry_count += 1
                    time.sleep(2**retry_count)
                    continue
                raise last_exception

            except httpx.ConnectError as e:
                last_exception = ConnectionError(f"Connection failed: {e}")
                if allow_retry and retry_count < self._config.max_retries:
                    retry_count += 1
                    time.sleep(2**retry_count)
                    continue
                raise last_exception

            except (RateLimitError, VideoVectorError):
                raise

            except Exception as e:
                last_exception = VideoVectorError(f"Request failed: {e}")
                if allow_retry and retry_count < self._config.max_retries:
                    retry_count += 1
                    time.sleep(2**retry_count)
                    continue
                raise last_exception

        if last_exception:
            raise last_exception
        raise VideoVectorError("Request failed after max retries")

    def get(
        self,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """Execute GET request."""
        return self._request("GET", endpoint, params=params, headers=headers)

    def iter_bytes(
        self,
        endpoint: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        chunk_size: int = 1024 * 1024,
        max_bytes: int,
    ) -> Iterator[bytes]:
        """Stream a response body exactly once without JSON decoding or retries."""
        _validate_stream_limits(chunk_size=chunk_size, max_bytes=max_bytes)
        stream_headers = _identity_encoded_download_headers(headers)

        try:
            with self._client.stream(
                method="GET",
                url=endpoint,
                headers=stream_headers,
            ) as response:
                if response.status_code != 200:
                    response.read()
                    if response.status_code < 400:
                        raise VideoVectorError(
                            "Download did not return a complete response",
                            status_code=response.status_code,
                            error_code="unexpected_download_status",
                        )
                    _raise_stream_error(response)
                expected_length = _validate_download_response_headers(
                    response,
                    max_bytes=max_bytes,
                )

                total = 0
                for chunk in response.iter_bytes(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        raise VideoVectorError(
                            "Download exceeded the configured byte limit",
                            error_code="download_size_limit_exceeded",
                            details={"max_bytes": max_bytes},
                        )
                    yield chunk
                _validate_streamed_length(
                    expected_length=expected_length,
                    actual_length=total,
                )
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"Download timed out: {exc}") from exc
        except httpx.ConnectError as exc:
            raise ConnectionError(f"Download connection failed: {exc}") from exc
        except (RateLimitError, VideoVectorError):
            raise
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Download failed: {exc}") from exc

    def post(
        self,
        endpoint: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        """Execute POST request."""
        return self._request(
            "POST",
            endpoint,
            json=json,
            data=data,
            files=files,
            params=params,
            headers=headers,
            idempotency_key=idempotency_key,
        )

    def put(
        self,
        endpoint: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        """Execute PUT request."""
        return self._request(
            "PUT",
            endpoint,
            json=json,
            params=params,
            headers=headers,
            idempotency_key=idempotency_key,
        )

    def patch(
        self,
        endpoint: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        """Execute PATCH request."""
        return self._request(
            "PATCH",
            endpoint,
            json=json,
            params=params,
            headers=headers,
            idempotency_key=idempotency_key,
        )

    def delete(
        self,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """Execute DELETE request."""
        return self._request("DELETE", endpoint, params=params, headers=headers)

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()


class AsyncHttpClient:
    """Asynchronous HTTP client for VideoVector API."""

    def __init__(self, config: ClientConfig) -> None:
        self._config = config
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def base_url(self) -> str:
        """Configured API base URL used to validate security-sensitive responses."""
        return self._config.base_url

    def _default_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": f"videovector-python/{__version__}",
        }
        if self._config.auth_mode == "bearer" and self._config.bearer_token:
            headers["Authorization"] = f"Bearer {self._config.bearer_token}"
        elif self._config.auth_mode == "api_key" and self._config.api_key:
            headers["X-API-Key"] = self._config.api_key
        elif self._config.bearer_token:
            headers["Authorization"] = f"Bearer {self._config.bearer_token}"
        elif self._config.api_key:
            headers["X-API-Key"] = self._config.api_key

        custom_headers = {
            key: value
            for key, value in self._config.custom_headers.items()
            if key.lower() != "content-type"
        }
        headers.update(custom_headers)
        return headers

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._config.base_url,
                timeout=httpx.Timeout(self._config.timeout),
                headers=self._default_headers(),
            )
        return self._client

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        """Execute HTTP request with retry logic."""
        import asyncio

        normalized_method = method.upper()
        allow_retry = _should_retry_request(normalized_method, idempotency_key)

        client = await self._ensure_client()

        request_headers = {}
        if headers:
            request_headers.update(headers)
        if idempotency_key:
            request_headers["Idempotency-Key"] = idempotency_key

        if files:
            request_headers = {
                key: value
                for key, value in request_headers.items()
                if key.lower() != "content-type"
            }

        last_exception: Optional[Exception] = None
        retry_count = 0

        while retry_count <= self._config.max_retries:
            try:
                response = await client.request(
                    method=method,
                    url=endpoint,
                    params=_clean_params(params),
                    json=json,
                    data=data,
                    files=files,
                    headers=request_headers if request_headers else None,
                )

                if response.status_code == 429:
                    retry_after = _get_retry_after(response)
                    if allow_retry and retry_count < self._config.max_retries:
                        await asyncio.sleep(retry_after)
                        retry_count += 1
                        continue
                    _raise_rate_limit_response(response, retry_after=retry_after)

                if (
                    allow_retry
                    and response.status_code >= 500
                    and retry_count < self._config.max_retries
                ):
                    retry_count += 1
                    await asyncio.sleep(2**retry_count)
                    continue

                if response.status_code >= 400:
                    body = _decode_error_body(response)
                    _raise_for_status(response.status_code, body)

                if response.status_code == 204:
                    return {}

                return _decode_json_response(response)

            except httpx.TimeoutException as e:
                last_exception = TimeoutError(f"Request timed out: {e}")
                if allow_retry and retry_count < self._config.max_retries:
                    retry_count += 1
                    await asyncio.sleep(2**retry_count)
                    continue
                raise last_exception

            except httpx.ConnectError as e:
                last_exception = ConnectionError(f"Connection failed: {e}")
                if allow_retry and retry_count < self._config.max_retries:
                    retry_count += 1
                    await asyncio.sleep(2**retry_count)
                    continue
                raise last_exception

            except (RateLimitError, VideoVectorError):
                raise

            except Exception as e:
                last_exception = VideoVectorError(f"Request failed: {e}")
                if allow_retry and retry_count < self._config.max_retries:
                    retry_count += 1
                    await asyncio.sleep(2**retry_count)
                    continue
                raise last_exception

        if last_exception:
            raise last_exception
        raise VideoVectorError("Request failed after max retries")

    async def get(
        self,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """Execute GET request."""
        return await self._request("GET", endpoint, params=params, headers=headers)

    async def iter_bytes(
        self,
        endpoint: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        chunk_size: int = 1024 * 1024,
        max_bytes: int,
    ) -> AsyncIterator[bytes]:
        """Stream a response body exactly once without JSON decoding or retries."""
        _validate_stream_limits(chunk_size=chunk_size, max_bytes=max_bytes)
        client = await self._ensure_client()
        stream_headers = _identity_encoded_download_headers(headers)

        try:
            async with client.stream(
                method="GET",
                url=endpoint,
                headers=stream_headers,
            ) as response:
                if response.status_code != 200:
                    await response.aread()
                    if response.status_code < 400:
                        raise VideoVectorError(
                            "Download did not return a complete response",
                            status_code=response.status_code,
                            error_code="unexpected_download_status",
                        )
                    _raise_stream_error(response)
                expected_length = _validate_download_response_headers(
                    response,
                    max_bytes=max_bytes,
                )

                total = 0
                async for chunk in response.aiter_bytes(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        raise VideoVectorError(
                            "Download exceeded the configured byte limit",
                            error_code="download_size_limit_exceeded",
                            details={"max_bytes": max_bytes},
                        )
                    yield chunk
                _validate_streamed_length(
                    expected_length=expected_length,
                    actual_length=total,
                )
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"Download timed out: {exc}") from exc
        except httpx.ConnectError as exc:
            raise ConnectionError(f"Download connection failed: {exc}") from exc
        except (RateLimitError, VideoVectorError):
            raise
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Download failed: {exc}") from exc

    async def post(
        self,
        endpoint: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        """Execute POST request."""
        return await self._request(
            "POST",
            endpoint,
            json=json,
            data=data,
            files=files,
            params=params,
            headers=headers,
            idempotency_key=idempotency_key,
        )

    async def put(
        self,
        endpoint: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        """Execute PUT request."""
        return await self._request(
            "PUT",
            endpoint,
            json=json,
            params=params,
            headers=headers,
            idempotency_key=idempotency_key,
        )

    async def patch(
        self,
        endpoint: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        """Execute PATCH request."""
        return await self._request(
            "PATCH",
            endpoint,
            json=json,
            params=params,
            headers=headers,
            idempotency_key=idempotency_key,
        )

    async def delete(
        self,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """Execute DELETE request."""
        return await self._request("DELETE", endpoint, params=params, headers=headers)

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "AsyncHttpClient":
        await self._ensure_client()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()


def _raise_rate_limit_response(response: httpx.Response, *, retry_after: int) -> None:
    """Preserve the API's structured 429 contract on the typed SDK error."""
    body = _decode_error_body(response, default_message="Rate limit exceeded")

    try:
        _raise_for_status(429, body)
    except RateLimitError as error:
        error.retry_after = retry_after
        raise

    # Defensive fallback if the exception mapper ever changes its 429 branch.
    raise RateLimitError(
        "Rate limit exceeded",
        status_code=429,
        retry_after=retry_after,
    )


def _identity_encoded_download_headers(
    headers: Optional[Dict[str, str]],
) -> Dict[str, str]:
    """Require an undecoded response so Content-Length remains authoritative."""
    stream_headers = {
        name: value for name, value in (headers or {}).items() if name.lower() != "accept-encoding"
    }
    stream_headers["Accept-Encoding"] = "identity"
    return stream_headers


def _validate_stream_limits(*, chunk_size: int, max_bytes: int) -> None:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    if max_bytes <= 0:
        raise ValueError("max_bytes must be greater than zero")


def _validate_download_response_headers(
    response: httpx.Response,
    *,
    max_bytes: int,
) -> int:
    content_type = response.headers.get("content-type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise VideoVectorError(
            "Download returned an unexpected content type",
            error_code="unexpected_download_content_type",
            details={"content_type": content_type or None},
        )
    content_encoding = response.headers.get("content-encoding", "").strip().lower()
    if content_encoding not in {"", "identity"}:
        raise VideoVectorError(
            "Download returned an unexpected content encoding",
            error_code="unexpected_download_content_encoding",
            details={"content_encoding": content_encoding},
        )

    raw_content_length = response.headers.get("content-length")
    if raw_content_length is None:
        raise VideoVectorError(
            "Download response did not declare its byte length",
            error_code="missing_download_content_length",
        )
    try:
        content_length = int(raw_content_length)
    except (TypeError, ValueError) as exc:
        raise VideoVectorError(
            "Download returned an invalid Content-Length",
            error_code="invalid_download_content_length",
        ) from exc
    if content_length <= 0:
        raise VideoVectorError(
            "Download returned an invalid Content-Length",
            error_code="invalid_download_content_length",
        )
    if content_length > max_bytes:
        raise VideoVectorError(
            "Download exceeds the configured byte limit",
            error_code="download_size_limit_exceeded",
            details={"content_length": content_length, "max_bytes": max_bytes},
        )
    return content_length


def _validate_streamed_length(
    *,
    expected_length: int,
    actual_length: int,
) -> None:
    if actual_length != expected_length:
        raise VideoVectorError(
            "Download body length did not match the declared response length",
            error_code="download_incomplete",
            details={
                "expected_bytes": expected_length,
                "received_bytes": actual_length,
            },
        )


def _raise_stream_error(response: httpx.Response) -> None:
    if response.status_code == 429:
        _raise_rate_limit_response(
            response,
            retry_after=_get_retry_after(response),
        )
    body = _decode_error_body(
        response,
        default_message="Download request failed",
    )
    _raise_for_status(response.status_code, body)


_INVALID_JSON = object()


def _try_decode_json(response: httpx.Response) -> Any:
    """Decode JSON without retaining decoder exceptions or their raw document."""
    decoded: Any = _INVALID_JSON
    try:
        decoded = response.json()
    except Exception:
        # JSONDecodeError retains its source document on ``.doc``. Never chain or
        # re-raise it because successful API responses may contain credentials.
        pass
    return decoded


def _decode_json_response(response: httpx.Response) -> Any:
    """Decode a successful API response through a credential-safe boundary."""
    decoded = _try_decode_json(response)
    if decoded is _INVALID_JSON:
        raise VideoVectorError(
            "API returned an invalid JSON response",
            status_code=502,
            error_code="invalid_json_response",
        ) from None
    return decoded


def _decode_error_body(
    response: httpx.Response,
    *,
    default_message: str = "API request failed",
) -> Dict[str, Any]:
    """Return structured errors without copying arbitrary response text."""
    decoded = _try_decode_json(response)
    if isinstance(decoded, dict):
        return decoded
    return {"message": default_message}


def _clean_params(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Remove None values from params dict."""
    if params is None:
        return None
    return {k: v for k, v in params.items() if v is not None}


def _get_retry_after(response: httpx.Response) -> int:
    """Extract retry-after value from response headers."""
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return int(retry_after)
        except ValueError:
            pass
    return 60  # Default to 60 seconds


def _should_retry_request(method: str, idempotency_key: Optional[str]) -> bool:
    """Return whether a request is safe to retry automatically."""
    if idempotency_key:
        return True
    return method in {"GET", "HEAD", "OPTIONS", "PUT", "DELETE"}
