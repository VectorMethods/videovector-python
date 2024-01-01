"""
VideoVector SDK Exports Resource.

Provides methods for exporting metadata from indexes and prompt runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import uuid4

from .._types import Export, ExportCreateResult

if TYPE_CHECKING:
    from .._http import AsyncHttpClient, SyncHttpClient


def _resolve_export_idempotency_key(idempotency_key: Optional[str]) -> str:
    """Ensure export creation requests can be retried safely."""
    candidate = (idempotency_key or "").strip()
    if candidate:
        return candidate
    return f"export-create:{uuid4().hex}"


class ExportsResource:
    """
    Synchronous Exports resource.

    Provides methods for exporting metadata from indexes and prompt runs
    to JSON files for analytics, compliance, or data migration.

    Example:
        client = VideoVector(api_key="<VIDEO_VECTOR_API_KEY>")

        # Export all metadata from an index
        export = client.exports.create_index_export(
            index_id="idx_123"
        )

        # Wait for export to complete
        export = client.exports.wait_for_completion(export.export_id)

        # Download the export
        print(f"Download URL: {export.download_url}")
        print(f"File size: {export.file_size_bytes} bytes")

        # Export specific prompt runs from an index
        export = client.exports.create_index_export(
            index_id="idx_123",
            prompt_run_ids=["run_abc", "run_def"]
        )

        # Export a single prompt run
        export = client.exports.create_prompt_run_export(
            run_id="run_123"
        )

        # List all exports
        exports = client.exports.list()
        for e in exports:
            print(f"{e.export_id}: {e.status}")
    """

    def __init__(self, client: "SyncHttpClient") -> None:
        self._client = client

    def create_index_export(
        self,
        index_id: str,
        *,
        prompt_run_ids: Optional[List[str]] = None,
        destination_connector_id: Optional[str] = None,
        destination_subpath: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> ExportCreateResult:
        """
        Create an export of index metadata.

        Exports all segments and their extracted metadata from an index.
        Optionally filter to specific prompt runs.

        Args:
            index_id: Index ID to export
            prompt_run_ids: Optional list of specific prompt run IDs to include.
                If not provided, exports all prompt runs.
            idempotency_key: Optional key for idempotent requests

        Returns:
            ExportCreateResult: Export job ID and initial status

        Raises:
            NotFoundError: If index doesn't exist
            ValidationError: If prompt_run_ids are invalid
        """
        body: Dict[str, Any] = {}
        if prompt_run_ids:
            body["prompt_run_ids"] = prompt_run_ids
        if destination_connector_id:
            body["destination_connector_id"] = destination_connector_id
        if destination_subpath:
            body["destination_subpath"] = destination_subpath

        response = self._client.post(
            f"/exports/index/{index_id}",
            json=body if body else None,
            idempotency_key=_resolve_export_idempotency_key(idempotency_key),
        )
        return ExportCreateResult.model_validate(response)

    def create_prompt_run_export(
        self,
        run_id: str,
        *,
        destination_connector_id: Optional[str] = None,
        destination_subpath: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> ExportCreateResult:
        """
        Create an export of prompt run metadata.

        Exports all segments and their extracted metadata from a specific
        prompt run.

        Args:
            run_id: Prompt run ID to export
            idempotency_key: Optional key for idempotent requests

        Returns:
            ExportCreateResult: Export job ID and initial status

        Raises:
            NotFoundError: If prompt run doesn't exist
        """
        body: Dict[str, Any] = {}
        if destination_connector_id:
            body["destination_connector_id"] = destination_connector_id
        if destination_subpath:
            body["destination_subpath"] = destination_subpath

        response = self._client.post(
            f"/exports/prompt-run/{run_id}",
            json=body if body else None,
            idempotency_key=_resolve_export_idempotency_key(idempotency_key),
        )
        return ExportCreateResult.model_validate(response)

    def retrieve(self, export_id: str) -> Export:
        """
        Retrieve an export by ID.

        Args:
            export_id: Export ID

        Returns:
            Export: Export details including status and download URL

        Raises:
            NotFoundError: If export doesn't exist
        """
        response = self._client.get(f"/exports/{export_id}")
        return Export.model_validate(response)

    def list(self, *, limit: int = 50) -> List[Export]:
        """
        List all exports.

        Args:
            limit: Maximum number of exports to return (1-100)

        Returns:
            List[Export]: Export jobs sorted by creation time
        """
        response = self._client.get("/exports", params={"limit": limit})
        return [Export.model_validate(e) for e in response]

    def wait_for_completion(
        self,
        export_id: str,
        *,
        poll_interval: float = 5.0,
        timeout: Optional[float] = None,
    ) -> Export:
        """
        Poll until an export completes.

        Args:
            export_id: Export ID
            poll_interval: Seconds between polls (default 5)
            timeout: Maximum seconds to wait (None for no timeout)

        Returns:
            Export: Completed export with download URL

        Raises:
            TimeoutError: If timeout is reached
            ProcessingError: If export fails
        """
        import time

        from .._exceptions import ProcessingError, TimeoutError

        start_time = time.time()

        while True:
            export = self.retrieve(export_id)

            if export.status in ("completed", "failed"):
                if export.status == "failed":
                    raise ProcessingError(
                        f"Export failed: {export.error_message}",
                        details={"export_id": export_id},
                    )
                return export

            if timeout and (time.time() - start_time) > timeout:
                raise TimeoutError(
                    f"Export did not complete within {timeout} seconds",
                    details={"export_id": export_id, "status": export.status},
                )

            time.sleep(poll_interval)

    def download_url(self, export_id: str) -> Optional[str]:
        """
        Get the download URL for a completed export.

        Convenience method that retrieves the export and returns
        the download URL if available.

        Args:
            export_id: Export ID

        Returns:
            Optional[str]: Download URL if export is completed, None otherwise

        Raises:
            NotFoundError: If export doesn't exist
        """
        export = self.retrieve(export_id)
        return export.download_url


class AsyncExportsResource:
    """
    Asynchronous Exports resource.

    Provides async methods for exporting metadata.

    Example:
        async with AsyncVideoVector(api_key="<VIDEO_VECTOR_API_KEY>") as client:
            # Create an export
            export = await client.exports.create_index_export(
                index_id="idx_123"
            )

            # Wait for completion
            export = await client.exports.wait_for_completion(export.export_id)

            # Download
            print(f"Download: {export.download_url}")
    """

    def __init__(self, client: "AsyncHttpClient") -> None:
        self._client = client

    async def create_index_export(
        self,
        index_id: str,
        *,
        prompt_run_ids: Optional[List[str]] = None,
        destination_connector_id: Optional[str] = None,
        destination_subpath: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> ExportCreateResult:
        """Create an export of index metadata."""
        body: Dict[str, Any] = {}
        if prompt_run_ids:
            body["prompt_run_ids"] = prompt_run_ids
        if destination_connector_id:
            body["destination_connector_id"] = destination_connector_id
        if destination_subpath:
            body["destination_subpath"] = destination_subpath

        response = await self._client.post(
            f"/exports/index/{index_id}",
            json=body if body else None,
            idempotency_key=_resolve_export_idempotency_key(idempotency_key),
        )
        return ExportCreateResult.model_validate(response)

    async def create_prompt_run_export(
        self,
        run_id: str,
        *,
        destination_connector_id: Optional[str] = None,
        destination_subpath: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> ExportCreateResult:
        """Create an export of prompt run metadata."""
        body: Dict[str, Any] = {}
        if destination_connector_id:
            body["destination_connector_id"] = destination_connector_id
        if destination_subpath:
            body["destination_subpath"] = destination_subpath

        response = await self._client.post(
            f"/exports/prompt-run/{run_id}",
            json=body if body else None,
            idempotency_key=_resolve_export_idempotency_key(idempotency_key),
        )
        return ExportCreateResult.model_validate(response)

    async def retrieve(self, export_id: str) -> Export:
        """Retrieve an export by ID."""
        response = await self._client.get(f"/exports/{export_id}")
        return Export.model_validate(response)

    async def list(self, *, limit: int = 50) -> List[Export]:
        """List all exports."""
        response = await self._client.get("/exports", params={"limit": limit})
        return [Export.model_validate(e) for e in response]

    async def wait_for_completion(
        self,
        export_id: str,
        *,
        poll_interval: float = 5.0,
        timeout: Optional[float] = None,
    ) -> Export:
        """Poll until an export completes."""
        import asyncio
        import time

        from .._exceptions import ProcessingError, TimeoutError

        start_time = time.time()

        while True:
            export = await self.retrieve(export_id)

            if export.status in ("completed", "failed"):
                if export.status == "failed":
                    raise ProcessingError(
                        f"Export failed: {export.error_message}",
                        details={"export_id": export_id},
                    )
                return export

            if timeout and (time.time() - start_time) > timeout:
                raise TimeoutError(
                    f"Export did not complete within {timeout} seconds",
                    details={"export_id": export_id, "status": export.status},
                )

            await asyncio.sleep(poll_interval)

    async def download_url(self, export_id: str) -> Optional[str]:
        """Get the download URL for a completed export."""
        export = await self.retrieve(export_id)
        return export.download_url
