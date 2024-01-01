"""
VideoVector SDK HTTP Client.

Low-level HTTP client with retry logic, authentication, and error handling.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

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
                    time.sleep(2 ** retry_count)
                    continue

                if response.status_code >= 400:
                    try:
                        body = response.json()
                    except Exception:
                        body = {"message": response.text}
                    _raise_for_status(response.status_code, body)

                if response.status_code == 204:
                    return {}

                return response.json()

            except httpx.TimeoutException as e:
                last_exception = TimeoutError(f"Request timed out: {e}")
                if allow_retry and retry_count < self._config.max_retries:
                    retry_count += 1
                    time.sleep(2 ** retry_count)
                    continue
                raise last_exception

            except httpx.ConnectError as e:
                last_exception = ConnectionError(f"Connection failed: {e}")
                if allow_retry and retry_count < self._config.max_retries:
                    retry_count += 1
                    time.sleep(2 ** retry_count)
                    continue
                raise last_exception

            except (RateLimitError, VideoVectorError):
                raise

            except Exception as e:
                last_exception = VideoVectorError(f"Request failed: {e}")
                if allow_retry and retry_count < self._config.max_retries:
                    retry_count += 1
                    time.sleep(2 ** retry_count)
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
                    await asyncio.sleep(2 ** retry_count)
                    continue

                if response.status_code >= 400:
                    try:
                        body = response.json()
                    except Exception:
                        body = {"message": response.text}
                    _raise_for_status(response.status_code, body)

                if response.status_code == 204:
                    return {}

                return response.json()

            except httpx.TimeoutException as e:
                last_exception = TimeoutError(f"Request timed out: {e}")
                if allow_retry and retry_count < self._config.max_retries:
                    retry_count += 1
                    await asyncio.sleep(2 ** retry_count)
                    continue
                raise last_exception

            except httpx.ConnectError as e:
                last_exception = ConnectionError(f"Connection failed: {e}")
                if allow_retry and retry_count < self._config.max_retries:
                    retry_count += 1
                    await asyncio.sleep(2 ** retry_count)
                    continue
                raise last_exception

            except (RateLimitError, VideoVectorError):
                raise

            except Exception as e:
                last_exception = VideoVectorError(f"Request failed: {e}")
                if allow_retry and retry_count < self._config.max_retries:
                    retry_count += 1
                    await asyncio.sleep(2 ** retry_count)
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
    try:
        parsed_body = response.json()
        body = parsed_body if isinstance(parsed_body, dict) else {"message": response.text}
    except Exception:
        body = {"message": response.text or "Rate limit exceeded"}

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
