"""
VideoVector SDK Videos Resource.

Provides methods for video CRUD operations, uploads, and processing.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, List, Optional, Union

from .._pagination import (
    AsyncPage,
    SyncPage,
    _parse_paginated_response,
    _parse_paginated_response_async,
)
from .._types import (
    BatchVideoSegmentsTarget,
    ProcessingStartedResponse,
    PromptRun,
    Segment,
    SignedUrl,
    UploadResult,
    Video,
    VideoDeletionResponse,
    VideoSegments,
    VideoStatus,
    VideoWithDetails,
)

if TYPE_CHECKING:
    from .._http import AsyncHttpClient, SyncHttpClient


def _batch_segments_payload(
    *,
    video_ids: Optional[List[str]] = None,
    targets: Optional[List[BatchVideoSegmentsTarget]] = None,
) -> dict[str, Any]:
    if video_ids is not None and targets is not None:
        raise ValueError("video_ids and targets are mutually exclusive")
    if targets is not None:
        if not targets:
            raise ValueError("targets must not be empty")
        return {"targets": [target.model_dump(exclude_none=True) for target in targets]}
    if video_ids is not None:
        if not video_ids:
            raise ValueError("video_ids must not be empty")
        return {"video_ids": video_ids}
    raise ValueError("Either video_ids or targets must be provided")


class VideosResource:
    """
    Synchronous Videos resource.

    Provides methods for managing videos including upload, processing,
    retrieval, and deletion.

    Example:
        client = VideoVector(api_key="<VIDEO_VECTOR_API_KEY>")

        # Upload a video
        result = client.videos.upload(
            file="/path/to/video.mp4",
            title="My Video",
            index_id="idx_123"
        )

        # Get video details
        video = client.videos.retrieve("video_123")

        # List video segments
        segments = client.videos.list_segments("video_123")
        for segment in segments.auto_paging_iter():
            print(segment.metadata)
    """

    def __init__(self, client: "SyncHttpClient") -> None:
        self._client = client

    def create(
        self,
        *,
        title: str,
        video_uri: str,
        index_id: str,
        source_connector_id: Optional[str] = None,
    ) -> Video:
        """
        Create a video from an existing GCS URI.

        Args:
            title: Video title (1-255 characters)
            video_uri: GCS URI of the video (gs://bucket/path)
            index_id: Target index ID
            source_connector_id: Optional caller-owned connector used to import a
                private external GCS object. Public and platform-managed objects
                do not require this field.

        Returns:
            Video: Created video object

        Raises:
            ValidationError: If parameters are invalid
            NotFoundError: If index doesn't exist
        """
        payload = {
            "title": title,
            "video_uri": video_uri,
            "index_id": index_id,
        }
        if source_connector_id is not None:
            payload["source_connector_id"] = source_connector_id
        response = self._client.post("/videos", json=payload)
        return Video.model_validate(response)

    def upload(
        self,
        *,
        file: Union[str, Path, BinaryIO],
        title: str,
        index_id: Optional[str] = None,
    ) -> UploadResult:
        """
        Upload a video, audio, or image file.

        Supported formats:
        - Video: mp4, avi, mkv, mov, webm
        - Audio: mp3, wav, flac, m4a, ogg, aac
        - Image: jpg, jpeg, png, webp, gif, bmp, tiff, heic, heif

        Args:
            file: File path or file-like object
            title: Media title (1-255 characters)
            index_id: Target index ID (None for playground)

        Returns:
            UploadResult: Upload result with video_id and status

        Raises:
            ValidationError: If file format is not supported
        """
        if isinstance(file, (str, Path)):
            file_path = Path(file)
            with open(file_path, "rb") as f:
                files: dict[str, tuple[str, Any]] = {"file": (file_path.name, f)}
                data: dict[str, Any] = {"title": title}
                if index_id:
                    data["index_id"] = index_id
                response = self._client.post("/videos/upload", files=files, data=data)
        else:
            filename = getattr(file, "name", "upload")
            files_payload: dict[str, tuple[str, Any]] = {"file": (filename, file)}
            data_payload: dict[str, Any] = {"title": title}
            if index_id:
                data_payload["index_id"] = index_id
            response = self._client.post("/videos/upload", files=files_payload, data=data_payload)

        return UploadResult.model_validate(response)

    def retrieve(self, video_id: str) -> Video:
        """
        Retrieve a video by ID.

        Args:
            video_id: Video ID

        Returns:
            Video: Video object

        Raises:
            NotFoundError: If video doesn't exist
        """
        response = self._client.get(f"/videos/{video_id}")
        return Video.model_validate(response)

    def delete(self, video_id: str) -> VideoDeletionResponse:
        """
        Start or resume durable video deletion.

        Args:
            video_id: Video ID to delete

        Returns:
            VideoDeletionResponse: Durable deletion identity and progress

        Raises:
            NotFoundError: If video doesn't exist
            AuthorizationError: If admin scope is required
        """
        response = self._client.delete(f"/videos/{video_id}")
        return VideoDeletionResponse.model_validate(response)

    def get_deletion(self, video_id: str) -> VideoDeletionResponse:
        """Retrieve durable deletion progress for a video."""

        response = self._client.get(f"/videos/{video_id}/deletion")
        return VideoDeletionResponse.model_validate(response)

    def process(
        self,
        video_id: str,
        *,
        segment_duration: int = 10,
        prompt_id: Optional[str] = None,
    ) -> ProcessingStartedResponse:
        """
        Start processing a video with segmentation.

        Args:
            video_id: Video ID to process
            segment_duration: Segment duration in seconds (1-300)
            prompt_id: Optional prompt ID for extraction

        Returns:
            ProcessingStartedResponse: Confirmation that processing has started

        Raises:
            NotFoundError: If video doesn't exist
            ValidationError: If video is already processing
        """
        params: dict[str, Any] = {"segment_duration": segment_duration}
        if prompt_id:
            params["prompt_id"] = prompt_id
        response = self._client.post(f"/videos/{video_id}/process", params=params)
        return ProcessingStartedResponse.model_validate(response)

    def list_segments(
        self,
        video_id: str,
        *,
        run_id: Optional[str] = None,
        latest_run: Optional[bool] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> SyncPage[Segment]:
        """
        List segments for a video.

        Args:
            video_id: Video ID
            run_id: Filter by prompt run ID
            latest_run: Get segments from latest run only
            limit: Number of results per page (1-100)
            cursor: Pagination cursor

        Returns:
            SyncPage[Segment]: Paginated segments
        """
        params: dict[str, Any] = {"limit": limit}
        if run_id:
            params["run_id"] = run_id
        if latest_run is not None:
            params["latest_run"] = latest_run
        if cursor:
            params["cursor"] = cursor

        response = self._client.get(f"/videos/{video_id}/segments", params=params)
        return _parse_paginated_response(
            response=response,
            model=Segment,
            client=self._client,
            endpoint=f"/videos/{video_id}/segments",
            params={"limit": limit, "run_id": run_id, "latest_run": latest_run},
        )

    def batch_retrieve(
        self,
        video_ids: List[str],
    ) -> List[VideoWithDetails]:
        """
        Retrieve multiple videos by ID with details.

        Args:
            video_ids: List of video IDs (1-100)

        Returns:
            List[VideoWithDetails]: Videos with thumbnail data
        """
        response = self._client.post("/videos/batch", json={"video_ids": video_ids})
        return [VideoWithDetails.model_validate(v) for v in response]

    def batch_status(
        self,
        video_ids: List[str],
    ) -> List[VideoStatus]:
        """
        Get processing status for multiple videos.

        Args:
            video_ids: List of video IDs (1-100)

        Returns:
            List[VideoStatus]: Video statuses including overall status plus per-run/per-segment
                processing snapshots when available.
        """
        response = self._client.post("/videos/batch/status", json={"video_ids": video_ids})
        return [VideoStatus.model_validate(v) for v in response]

    def batch_segments(
        self,
        video_ids: List[str],
    ) -> List[VideoSegments]:
        """
        Get segments for multiple videos.

        Args:
            video_ids: List of video IDs (1-50)

        Returns:
            List[VideoSegments]: List of video segments with video_id and segments list
        """
        response = self._client.post(
            "/videos/batch/segments",
            json=_batch_segments_payload(video_ids=video_ids),
        )
        return [VideoSegments.model_validate(v) for v in response]

    def batch_segments_for_targets(
        self,
        targets: List[BatchVideoSegmentsTarget],
    ) -> List[VideoSegments]:
        """Get segments for media targets, optionally scoped to prompt runs."""
        response = self._client.post(
            "/videos/batch/segments",
            json=_batch_segments_payload(targets=targets),
        )
        return [VideoSegments.model_validate(v) for v in response]

    def get_signed_url(
        self,
        gcs_uri: str,
        *,
        force_refresh: bool = False,
    ) -> SignedUrl:
        """
        Generate a signed URL for accessing a GCS resource.

        Args:
            gcs_uri: GCS URI (gs://bucket/path)

        Returns:
            SignedUrl: Signed URL with expiration
        """
        payload: dict[str, Any] = {"gcs_uri": gcs_uri}
        if force_refresh:
            payload["force_refresh"] = True
        response = self._client.post("/videos/signed-url", json=payload)
        return SignedUrl.model_validate(response)

    def list_prompt_runs(self, video_id: str, *, limit: Optional[int] = None) -> List[PromptRun]:
        """
        List prompt runs that include a video.

        Args:
            video_id: Video ID
            limit: Optional maximum number of runs to return (1-200)

        Returns:
            List[PromptRun]: Prompt runs touching the video
        """
        params = {"limit": limit} if limit is not None else None
        response = self._client.get(f"/videos/{video_id}/prompt-runs", params=params)
        return [PromptRun.model_validate(run) for run in response]

    def list_playground(
        self,
        *,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> SyncPage[Video]:
        """
        List index-less videos from the user's playground.

        Args:
            limit: Number of results per page (1-100)
            cursor: Pagination cursor

        Returns:
            SyncPage[Video]: Paginated playground videos
        """
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor

        response = self._client.get("/playground/videos", params=params)
        return _parse_paginated_response(
            response=response,
            model=Video,
            client=self._client,
            endpoint="/playground/videos",
            params={"limit": limit},
        )


class AsyncVideosResource:
    """
    Asynchronous Videos resource.

    Provides async methods for managing videos including upload, processing,
    retrieval, and deletion.

    Example:
        async with AsyncVideoVector(api_key="<VIDEO_VECTOR_API_KEY>") as client:
            # Upload a video
            result = await client.videos.upload(
                file="/path/to/video.mp4",
                title="My Video",
                index_id="idx_123"
            )

            # Get video details
            video = await client.videos.retrieve("video_123")
    """

    def __init__(self, client: "AsyncHttpClient") -> None:
        self._client = client

    async def create(
        self,
        *,
        title: str,
        video_uri: str,
        index_id: str,
        source_connector_id: Optional[str] = None,
    ) -> Video:
        """Create a video from GCS, optionally through an owned connector."""
        payload = {
            "title": title,
            "video_uri": video_uri,
            "index_id": index_id,
        }
        if source_connector_id is not None:
            payload["source_connector_id"] = source_connector_id
        response = await self._client.post("/videos", json=payload)
        return Video.model_validate(response)

    async def upload(
        self,
        *,
        file: Union[str, Path, BinaryIO],
        title: str,
        index_id: Optional[str] = None,
    ) -> UploadResult:
        """Upload a video, audio, or image file."""
        if isinstance(file, (str, Path)):
            file_path = Path(file)
            with open(file_path, "rb") as f:
                files: dict[str, tuple[str, Any]] = {"file": (file_path.name, f)}
                data: dict[str, Any] = {"title": title}
                if index_id:
                    data["index_id"] = index_id
                response = await self._client.post("/videos/upload", files=files, data=data)
        else:
            filename = getattr(file, "name", "upload")
            files_payload: dict[str, tuple[str, Any]] = {"file": (filename, file)}
            data_payload: dict[str, Any] = {"title": title}
            if index_id:
                data_payload["index_id"] = index_id
            response = await self._client.post(
                "/videos/upload",
                files=files_payload,
                data=data_payload,
            )

        return UploadResult.model_validate(response)

    async def retrieve(self, video_id: str) -> Video:
        """Retrieve a video by ID."""
        response = await self._client.get(f"/videos/{video_id}")
        return Video.model_validate(response)

    async def delete(self, video_id: str) -> VideoDeletionResponse:
        """Start or resume durable video deletion."""
        response = await self._client.delete(f"/videos/{video_id}")
        return VideoDeletionResponse.model_validate(response)

    async def get_deletion(self, video_id: str) -> VideoDeletionResponse:
        """Retrieve durable deletion progress for a video."""

        response = await self._client.get(f"/videos/{video_id}/deletion")
        return VideoDeletionResponse.model_validate(response)

    async def process(
        self,
        video_id: str,
        *,
        segment_duration: int = 10,
        prompt_id: Optional[str] = None,
    ) -> ProcessingStartedResponse:
        """Start processing a video with segmentation."""
        params: dict[str, Any] = {"segment_duration": segment_duration}
        if prompt_id:
            params["prompt_id"] = prompt_id
        response = await self._client.post(f"/videos/{video_id}/process", params=params)
        return ProcessingStartedResponse.model_validate(response)

    async def list_segments(
        self,
        video_id: str,
        *,
        run_id: Optional[str] = None,
        latest_run: Optional[bool] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> AsyncPage[Segment]:
        """List segments for a video."""
        params: dict[str, Any] = {"limit": limit}
        if run_id:
            params["run_id"] = run_id
        if latest_run is not None:
            params["latest_run"] = latest_run
        if cursor:
            params["cursor"] = cursor

        response = await self._client.get(f"/videos/{video_id}/segments", params=params)
        return _parse_paginated_response_async(
            response=response,
            model=Segment,
            client=self._client,
            endpoint=f"/videos/{video_id}/segments",
            params={"limit": limit, "run_id": run_id, "latest_run": latest_run},
        )

    async def batch_retrieve(
        self,
        video_ids: List[str],
    ) -> List[VideoWithDetails]:
        """Retrieve multiple videos by ID with details."""
        response = await self._client.post("/videos/batch", json={"video_ids": video_ids})
        return [VideoWithDetails.model_validate(v) for v in response]

    async def batch_status(
        self,
        video_ids: List[str],
    ) -> List[VideoStatus]:
        """Get processing status for multiple videos including run/segment snapshots when available."""
        response = await self._client.post("/videos/batch/status", json={"video_ids": video_ids})
        return [VideoStatus.model_validate(v) for v in response]

    async def batch_segments(
        self,
        video_ids: List[str],
    ) -> List[VideoSegments]:
        """Get segments for multiple videos."""
        response = await self._client.post(
            "/videos/batch/segments",
            json=_batch_segments_payload(video_ids=video_ids),
        )
        return [VideoSegments.model_validate(v) for v in response]

    async def batch_segments_for_targets(
        self,
        targets: List[BatchVideoSegmentsTarget],
    ) -> List[VideoSegments]:
        """Get segments for media targets, optionally scoped to prompt runs."""
        response = await self._client.post(
            "/videos/batch/segments",
            json=_batch_segments_payload(targets=targets),
        )
        return [VideoSegments.model_validate(v) for v in response]

    async def get_signed_url(
        self,
        gcs_uri: str,
        *,
        force_refresh: bool = False,
    ) -> SignedUrl:
        """Generate a signed URL for accessing a GCS resource."""
        payload: dict[str, Any] = {"gcs_uri": gcs_uri}
        if force_refresh:
            payload["force_refresh"] = True
        response = await self._client.post("/videos/signed-url", json=payload)
        return SignedUrl.model_validate(response)

    async def list_prompt_runs(
        self, video_id: str, *, limit: Optional[int] = None
    ) -> List[PromptRun]:
        """List prompt runs that include a video."""
        params = {"limit": limit} if limit is not None else None
        response = await self._client.get(f"/videos/{video_id}/prompt-runs", params=params)
        return [PromptRun.model_validate(run) for run in response]

    async def list_playground(
        self,
        *,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> AsyncPage[Video]:
        """List index-less videos from the user's playground."""
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor

        response = await self._client.get("/playground/videos", params=params)
        return _parse_paginated_response_async(
            response=response,
            model=Video,
            client=self._client,
            endpoint="/playground/videos",
            params={"limit": limit},
        )
