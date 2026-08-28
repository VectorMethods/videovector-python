"""
VideoVector SDK Exceptions.

Provides typed exceptions matching API error codes for precise error handling.
"""

from __future__ import annotations

from typing import Any, Optional


class VideoVectorError(Exception):
    """Base exception for all VideoVector SDK errors."""

    message: str
    status_code: Optional[int]
    error_code: Optional[str]
    details: Optional[dict[str, Any]]
    request_id: Optional[str]

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        error_code: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        request_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.details = details or {}
        self.request_id = request_id

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"message={self.message!r}, "
            f"status_code={self.status_code}, "
            f"error_code={self.error_code!r}, "
            f"request_id={self.request_id!r})"
        )


class AuthenticationError(VideoVectorError):
    """Raised when an API key or bearer credential is invalid, missing, or expired."""

    pass


class AuthorizationError(VideoVectorError):
    """Raised when the API key lacks required scope for the operation."""

    pass


class NotFoundError(VideoVectorError):
    """Raised when a requested resource does not exist."""

    pass


class ValidationError(VideoVectorError):
    """Raised when request parameters fail validation."""

    pass


class RateLimitError(VideoVectorError):
    """Raised when rate limit is exceeded."""

    retry_after: Optional[int]

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        error_code: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        retry_after: Optional[int] = None,
        request_id: Optional[str] = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            error_code=error_code,
            details=details,
            request_id=request_id,
        )
        self.retry_after = retry_after


class ConflictError(VideoVectorError):
    """Raised when resource already exists or state conflict occurs."""

    pass


class ProcessingError(VideoVectorError):
    """Raised when video/media processing fails."""

    pass


class ExternalServiceError(VideoVectorError):
    """Raised when an external service (GCS, Pinecone, etc.) fails."""

    pass


class ConnectionError(VideoVectorError):
    """Raised when connection to the API fails."""

    pass


class TimeoutError(VideoVectorError):
    """Raised when request times out."""

    pass


class IdempotencyError(VideoVectorError):
    """Raised when idempotency key conflicts occur."""

    pass


def _raise_for_status(status_code: int, body: dict[str, Any]) -> None:
    """Raise appropriate exception based on status code and response body."""
    error_data = body.get("error", body)
    message = error_data.get("message", "Unknown error")
    error_code = error_data.get("error_code") or error_data.get("code")
    details = error_data.get("details", {})
    raw_request_id = error_data.get("request_id")
    request_id = raw_request_id if isinstance(raw_request_id, str) else None

    kwargs = {
        "status_code": status_code,
        "error_code": error_code,
        "details": details,
        "request_id": request_id,
    }

    if status_code == 401:
        raise AuthenticationError(message, **kwargs)
    elif status_code == 403:
        raise AuthorizationError(message, **kwargs)
    elif status_code == 404:
        raise NotFoundError(message, **kwargs)
    elif status_code == 409:
        raise ConflictError(message, **kwargs)
    elif status_code == 422:
        if "idempotency" in (error_code or "").lower():
            raise IdempotencyError(message, **kwargs)
        raise ValidationError(message, **kwargs)
    elif status_code == 429:
        retry_after = None
        if "retry_after" in error_data:
            retry_after = error_data["retry_after"]
        raise RateLimitError(message, retry_after=retry_after, **kwargs)
    elif status_code >= 500:
        raise ExternalServiceError(message, **kwargs)
    elif status_code >= 400:
        raise ValidationError(message, **kwargs)
    else:
        raise VideoVectorError(message, **kwargs)
