"""
VideoVector SDK Import Jobs Resource.

Provides methods for bulk importing videos from cloud storage.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional
from uuid import uuid4

from .._types import ImportJob

if TYPE_CHECKING:
    from .._http import AsyncHttpClient, SyncHttpClient


def _resolve_import_job_idempotency_key(
    operation: str,
    idempotency_key: Optional[str],
) -> str:
    """Ensure import job write requests can be retried safely."""
    candidate = (idempotency_key or "").strip()
    if candidate:
        return candidate
    return f"import-job-{operation}:{uuid4().hex}"


class ImportJobsResource:
    """
    Synchronous Import Jobs resource.

    Provides methods for creating and managing bulk import jobs
    from cloud storage (GCS, S3, Azure).

    Example:
        client = VideoVector(api_key="<VIDEO_VECTOR_API_KEY>")

        # Create an import job from a GCS bucket
        job = client.import_jobs.create(
            connector_id="conn_123",
            index_id="idx_456",
            source_prefix="videos/2024/",
            file_pattern="*.mp4",
            recursive=True
        )

        # Poll for completion
        job = client.import_jobs.wait_for_completion(job.job_id)

        # List all jobs
        jobs = client.import_jobs.list()
    """

    def __init__(self, client: "SyncHttpClient") -> None:
        self._client = client

    def create(
        self,
        *,
        connector_id: str,
        index_id: str,
        source_prefix: str = "",
        file_pattern: str = "*",
        recursive: bool = True,
        idempotency_key: Optional[str] = None,
    ) -> ImportJob:
        """
        Create a new import job.

        Args:
            connector_id: Cloud connector ID (GCS, S3, or Azure)
            index_id: Target index for imported videos
            source_prefix: Path prefix to filter files (e.g., "videos/2024/")
            file_pattern: Glob pattern for files (e.g., "*.mp4")
            recursive: Whether to scan subdirectories
            idempotency_key: Optional key for idempotent requests

        Returns:
            ImportJob: Created import job with status

        Raises:
            NotFoundError: If connector or index doesn't exist
            ValidationError: If parameters are invalid
        """
        response = self._client.post(
            "/import-jobs",
            json={
                "connector_id": connector_id,
                "index_id": index_id,
                "source_prefix": source_prefix,
                "file_pattern": file_pattern,
                "recursive": recursive,
            },
            idempotency_key=_resolve_import_job_idempotency_key("create", idempotency_key),
        )
        return ImportJob.model_validate(response)

    def retrieve(self, job_id: str) -> ImportJob:
        """
        Retrieve an import job by ID.

        Args:
            job_id: Import job ID

        Returns:
            ImportJob: Import job with current status and progress

        Raises:
            NotFoundError: If job doesn't exist
        """
        response = self._client.get(f"/import-jobs/{job_id}")
        return ImportJob.model_validate(response)

    def list(self, *, status: Optional[str] = None) -> List[ImportJob]:
        """
        List all import jobs.

        Args:
            status: Optional filter by status (PENDING, SCANNING, IMPORTING, etc.)

        Returns:
            List[ImportJob]: Import jobs
        """
        params = {}
        if status:
            params["status"] = status

        response = self._client.get("/import-jobs", params=params)
        return [ImportJob.model_validate(job) for job in response]

    def cancel(self, job_id: str, *, idempotency_key: Optional[str] = None) -> ImportJob:
        """
        Cancel a running import job.

        Args:
            job_id: Import job ID to cancel

        Returns:
            ImportJob: Cancelled import job

        Raises:
            NotFoundError: If job doesn't exist
            ValidationError: If job cannot be cancelled
        """
        response = self._client.post(
            f"/import-jobs/{job_id}/cancel",
            idempotency_key=_resolve_import_job_idempotency_key("cancel", idempotency_key),
        )
        return ImportJob.model_validate(response)

    def wait_for_completion(
        self,
        job_id: str,
        *,
        poll_interval: float = 10.0,
        timeout: Optional[float] = None,
    ) -> ImportJob:
        """
        Poll until an import job completes.

        Args:
            job_id: Import job ID
            poll_interval: Seconds between polls (default 10)
            timeout: Maximum seconds to wait (None for no timeout)

        Returns:
            ImportJob: Completed import job

        Raises:
            TimeoutError: If timeout is reached
            ProcessingError: If job fails
        """
        import time

        from .._exceptions import ProcessingError, TimeoutError

        start_time = time.time()

        while True:
            job = self.retrieve(job_id)
            status = (job.status or "").lower()

            if status in ("completed", "failed", "cancelled"):
                if status == "failed":
                    raise ProcessingError(
                        f"Import job failed: {job.error_message}",
                        details={"job_id": job_id},
                    )
                return job

            if timeout and (time.time() - start_time) > timeout:
                raise TimeoutError(
                    f"Import job did not complete within {timeout} seconds",
                    details={"job_id": job_id, "status": job.status},
                )

            time.sleep(poll_interval)


class AsyncImportJobsResource:
    """
    Asynchronous Import Jobs resource.

    Provides async methods for bulk import operations.

    Example:
        async with AsyncVideoVector(api_key="<VIDEO_VECTOR_API_KEY>") as client:
            job = await client.import_jobs.create(
                connector_id="conn_123",
                index_id="idx_456",
                source_prefix="videos/"
            )

            job = await client.import_jobs.wait_for_completion(job.job_id)
    """

    def __init__(self, client: "AsyncHttpClient") -> None:
        self._client = client

    async def create(
        self,
        *,
        connector_id: str,
        index_id: str,
        source_prefix: str = "",
        file_pattern: str = "*",
        recursive: bool = True,
        idempotency_key: Optional[str] = None,
    ) -> ImportJob:
        """Create a new import job."""
        response = await self._client.post(
            "/import-jobs",
            json={
                "connector_id": connector_id,
                "index_id": index_id,
                "source_prefix": source_prefix,
                "file_pattern": file_pattern,
                "recursive": recursive,
            },
            idempotency_key=_resolve_import_job_idempotency_key("create", idempotency_key),
        )
        return ImportJob.model_validate(response)

    async def retrieve(self, job_id: str) -> ImportJob:
        """Retrieve an import job by ID."""
        response = await self._client.get(f"/import-jobs/{job_id}")
        return ImportJob.model_validate(response)

    async def list(self, *, status: Optional[str] = None) -> List[ImportJob]:
        """List all import jobs."""
        params = {}
        if status:
            params["status"] = status

        response = await self._client.get("/import-jobs", params=params)
        return [ImportJob.model_validate(job) for job in response]

    async def cancel(self, job_id: str, *, idempotency_key: Optional[str] = None) -> ImportJob:
        """Cancel a running import job."""
        response = await self._client.post(
            f"/import-jobs/{job_id}/cancel",
            idempotency_key=_resolve_import_job_idempotency_key("cancel", idempotency_key),
        )
        return ImportJob.model_validate(response)

    async def wait_for_completion(
        self,
        job_id: str,
        *,
        poll_interval: float = 10.0,
        timeout: Optional[float] = None,
    ) -> ImportJob:
        """Poll until an import job completes."""
        import asyncio
        import time

        from .._exceptions import ProcessingError, TimeoutError

        start_time = time.time()

        while True:
            job = await self.retrieve(job_id)
            status = (job.status or "").lower()

            if status in ("completed", "failed", "cancelled"):
                if status == "failed":
                    raise ProcessingError(
                        f"Import job failed: {job.error_message}",
                        details={"job_id": job_id},
                    )
                return job

            if timeout and (time.time() - start_time) > timeout:
                raise TimeoutError(
                    f"Import job did not complete within {timeout} seconds",
                    details={"job_id": job_id, "status": job.status},
                )

            await asyncio.sleep(poll_interval)
