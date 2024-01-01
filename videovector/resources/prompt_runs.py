"""
VideoVector SDK Prompt Runs Resource.

Provides methods for executing prompts and retrieving results.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional
from uuid import uuid4

from .._pagination import (
    AsyncPage,
    SyncPage,
    _parse_paginated_response,
    _parse_paginated_response_async,
)
from .._types import (
    ExecutePromptTarget,
    LlmCall,
    PromptRun,
    PromptRunCostEstimate,
    PromptRunFailedSegmentsManifest,
    PromptRunSegmentRetry,
    PromptRunSegmentRetryStatus,
    PromptRunVideoResult,
    SegmentRunResult,
)

if TYPE_CHECKING:
    from .._http import AsyncHttpClient, SyncHttpClient

_TERMINAL_PROMPT_RUN_STATUSES = {"completed", "completed_with_failures", "failed", "cancelled"}


def _resolve_generated_idempotency_key(operation: str, idempotency_key: Optional[str]) -> str:
    """Ensure retry-safe prompt-run POST calls always include an idempotency key."""
    candidate = (idempotency_key or "").strip()
    if candidate:
        return candidate
    return f"prompt-run-{operation}:{uuid4().hex}"


def _validate_segmentation_type(
    field_name: str,
    value: str,
    allowed: set[str],
) -> None:
    if value not in allowed:
        allowed_values = ", ".join(sorted(allowed))
        raise ValueError(f"{field_name} must be one of: {allowed_values}")


def _validate_segment_duration(field_name: str, value: Optional[int]) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or not (1 <= value <= 300):
        raise ValueError(f"{field_name} must be an integer between 1 and 300")


def _validate_prompt_run_target(target: ExecutePromptTarget) -> None:
    if not isinstance(target, dict):
        raise ValueError("target must be an object")

    target_type = target.get("type")
    if target_type not in {"index", "videos", "playground"}:
        raise ValueError("target.type must be one of: index, videos, playground")

    if target_type == "index":
        index_id = target.get("index_id")
        if not isinstance(index_id, str) or not index_id.strip():
            raise ValueError("target.index_id is required when target.type is 'index'")
        return

    if target_type == "videos":
        video_ids = target.get("video_ids")
        if not isinstance(video_ids, list) or len(video_ids) == 0:
            raise ValueError(
                "target.video_ids must be a non-empty array when target.type is 'videos'"
            )
        if any(not isinstance(video_id, str) or not video_id.strip() for video_id in video_ids):
            raise ValueError("target.video_ids must contain non-empty strings")

        index_id = target.get("index_id")
        if index_id is not None and (not isinstance(index_id, str) or not index_id.strip()):
            raise ValueError("target.index_id must be a non-empty string when provided")


def _build_prompt_run_request_body(
    *,
    prompt_id: str,
    target: ExecutePromptTarget,
    video_segmentation_type: Literal["smart", "fixed", "content_aware"] = "smart",
    audio_segmentation_type: Literal["fixed", "content_aware"] = "content_aware",
    video_segment_duration: Optional[int] = None,
    audio_segment_duration: Optional[int] = None,
    processing_model: Optional[str] = None,
    enable_transcription: bool = True,
    enable_image_embedding: bool = True,
) -> Dict[str, Any]:
    _validate_prompt_run_target(target)
    _validate_segmentation_type(
        "video_segmentation_type",
        video_segmentation_type,
        {"smart", "fixed", "content_aware"},
    )
    _validate_segmentation_type(
        "audio_segmentation_type",
        audio_segmentation_type,
        {"fixed", "content_aware"},
    )
    _validate_segment_duration("video_segment_duration", video_segment_duration)
    _validate_segment_duration("audio_segment_duration", audio_segment_duration)

    if video_segmentation_type == "fixed" and video_segment_duration is None:
        raise ValueError(
            "video_segment_duration is required when video_segmentation_type is 'fixed'"
        )
    if audio_segmentation_type == "fixed" and audio_segment_duration is None:
        raise ValueError(
            "audio_segment_duration is required when audio_segmentation_type is 'fixed'"
        )

    body: Dict[str, Any] = {
        "prompt_id": prompt_id,
        "target": target,
        "video_segmentation_type": video_segmentation_type,
        "audio_segmentation_type": audio_segmentation_type,
        "enable_transcription": enable_transcription,
        "enable_image_embedding": enable_image_embedding,
    }

    if video_segment_duration is not None:
        body["video_segment_duration"] = video_segment_duration
    if audio_segment_duration is not None:
        body["audio_segment_duration"] = audio_segment_duration
    if processing_model is not None:
        body["processing_model"] = processing_model

    return body


class PromptRunsResource:
    """
    Synchronous Prompt Runs resource.

    Provides methods for executing prompts on videos/indexes and
    retrieving extraction results.

    Example:
        client = VideoVector(api_key="<VIDEO_VECTOR_API_KEY>")

        # Execute prompt on an index
        run = client.prompt_runs.execute(
            prompt_id="prompt_123",
            target={"type": "index", "index_id": "idx_123"},
            video_segmentation_type="smart",
            processing_model="gemini-2.5-flash"
        )

        # Poll for completion
        run = client.prompt_runs.retrieve(run.run_id)

        # Get results
        results = client.prompt_runs.list_results(run.run_id, video_id="video_123")
        for result in results.auto_paging_iter():
            print(result.metadata)
    """

    def __init__(self, client: "SyncHttpClient") -> None:
        self._client = client

    def execute(
        self,
        *,
        prompt_id: str,
        target: ExecutePromptTarget,
        video_segmentation_type: Literal["smart", "fixed", "content_aware"] = "smart",
        audio_segmentation_type: Literal["fixed", "content_aware"] = "content_aware",
        video_segment_duration: Optional[int] = None,
        audio_segment_duration: Optional[int] = None,
        processing_model: Optional[str] = None,
        enable_transcription: bool = True,
        enable_image_embedding: bool = True,
        idempotency_key: Optional[str] = None,
    ) -> PromptRun:
        """
        Execute a prompt on videos or an index.

        Args:
            prompt_id: ID of the prompt to execute
            target: Target specification with type and either index_id or video_ids
                - {"type": "index", "index_id": "idx_123"}
                - {"type": "videos", "video_ids": ["vid_1", "vid_2"]}
                - {"type": "playground"}
            video_segmentation_type: How to segment videos (smart, fixed, content_aware)
            audio_segmentation_type: How to segment audio (fixed, content_aware)
            video_segment_duration: Duration for fixed segments (1-300 seconds)
            audio_segment_duration: Duration for fixed audio segments (1-300 seconds)
            processing_model: LLM model for extraction
                Options: gemini-3-pro-preview, gemini-2.5-pro, gemini-2.5-flash, gemini-2.5-flash-lite
            enable_transcription: Enable speech-to-text transcription
            enable_image_embedding: Enable image embeddings for visual search
            idempotency_key: Optional key for idempotent requests

        Returns:
            PromptRun: Created prompt run with status

        Raises:
            NotFoundError: If prompt or target doesn't exist
            ValidationError: If parameters are invalid
        """
        body = _build_prompt_run_request_body(
            prompt_id=prompt_id,
            target=target,
            video_segmentation_type=video_segmentation_type,
            audio_segmentation_type=audio_segmentation_type,
            video_segment_duration=video_segment_duration,
            audio_segment_duration=audio_segment_duration,
            processing_model=processing_model,
            enable_transcription=enable_transcription,
            enable_image_embedding=enable_image_embedding,
        )
        resolved_idempotency_key = _resolve_generated_idempotency_key("execute", idempotency_key)
        response = self._client.post(
            "/prompt-runs/execute",
            json=body,
            idempotency_key=resolved_idempotency_key,
        )
        return PromptRun.model_validate(response)

    def list(self, *, limit: int = 200) -> List[PromptRun]:
        """List prompt runs accessible to the current user."""
        response = self._client.get("/prompt-runs", params={"limit": limit})
        return [PromptRun.model_validate(run) for run in response]

    def estimate(
        self,
        *,
        prompt_id: str,
        target: ExecutePromptTarget,
        video_segmentation_type: Literal["smart", "fixed", "content_aware"] = "smart",
        audio_segmentation_type: Literal["fixed", "content_aware"] = "content_aware",
        video_segment_duration: Optional[int] = None,
        audio_segment_duration: Optional[int] = None,
        processing_model: Optional[str] = None,
        enable_transcription: bool = True,
        enable_image_embedding: bool = True,
    ) -> PromptRunCostEstimate:
        """Estimate the billing cost of a prompt run without starting it."""
        body = _build_prompt_run_request_body(
            prompt_id=prompt_id,
            target=target,
            video_segmentation_type=video_segmentation_type,
            audio_segmentation_type=audio_segmentation_type,
            video_segment_duration=video_segment_duration,
            audio_segment_duration=audio_segment_duration,
            processing_model=processing_model,
            enable_transcription=enable_transcription,
            enable_image_embedding=enable_image_embedding,
        )
        response = self._client.post("/prompt-runs/estimate", json=body)
        return PromptRunCostEstimate.model_validate(response)

    def retrieve(self, run_id: str) -> PromptRun:
        """
        Retrieve a prompt run by ID.

        Args:
            run_id: Prompt run ID

        Returns:
            PromptRun: Prompt run with current status

        Raises:
            NotFoundError: If run doesn't exist
        """
        response = self._client.get(f"/prompt-runs/{run_id}")
        return PromptRun.model_validate(response)

    def list_results(
        self,
        run_id: str,
        *,
        video_id: str,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> SyncPage[SegmentRunResult]:
        """
        List extraction results for a prompt run.

        Args:
            run_id: Prompt run ID
            video_id: Video or audio media ID within the run
            limit: Number of results per page (1-100)
            cursor: Pagination cursor

        Returns:
            SyncPage[SegmentRunResult]: Paginated segment results
        """
        params = {"limit": limit, "video_id": video_id}
        if cursor:
            params["cursor"] = cursor

        response = self._client.get(f"/prompt-runs/{run_id}/results", params=params)
        return _parse_paginated_response(
            response=response,
            model=SegmentRunResult,
            client=self._client,
            endpoint=f"/prompt-runs/{run_id}/results",
            params={"limit": limit, "video_id": video_id},
        )

    def get_llm_calls(self, run_id: str) -> List[LlmCall]:
        """
        Get LLM calls made during a prompt run.

        Useful for debugging and understanding extraction details.

        Args:
            run_id: Prompt run ID

        Returns:
            List[LlmCall]: LLM call records with token usage and timing info
        """
        response = self._client.get(f"/prompt-runs/{run_id}/llm-calls")
        return [LlmCall.model_validate(call) for call in response]

    def get_video_result(self, run_id: str, video_id: str) -> PromptRunVideoResult:
        """Get the video/audio-level synthesis result for one media item in a run."""
        response = self._client.get(f"/prompt-runs/{run_id}/videos/{video_id}/video-result")
        return PromptRunVideoResult.model_validate(response)

    def get_failed_segments(self, run_id: str) -> PromptRunFailedSegmentsManifest:
        """Get the failed segment manifest for a prompt run."""
        response = self._client.get(f"/prompt-runs/{run_id}/failed-segments")
        return PromptRunFailedSegmentsManifest.model_validate(response)

    def retry_segment(
        self,
        run_id: str,
        video_id: str,
        segment_id: str,
        *,
        idempotency_key: Optional[str] = None,
    ) -> PromptRunSegmentRetry:
        """Dispatch a retry for a failed segment inside a prompt run."""
        resolved_idempotency_key = _resolve_generated_idempotency_key(
            "segment-retry", idempotency_key
        )
        response = self._client.post(
            f"/prompt-runs/{run_id}/videos/{video_id}/segments/{segment_id}/retry",
            idempotency_key=resolved_idempotency_key,
        )
        return PromptRunSegmentRetry.model_validate(response)

    def cancel(
        self,
        run_id: str,
        *,
        idempotency_key: Optional[str] = None,
    ) -> PromptRun:
        """Request cancellation for a prompt run."""
        resolved_idempotency_key = _resolve_generated_idempotency_key("cancel", idempotency_key)
        response = self._client.post(
            f"/prompt-runs/{run_id}/cancel",
            idempotency_key=resolved_idempotency_key,
        )
        return PromptRun.model_validate(response)

    def get_segment_retry_status(
        self,
        run_id: str,
        video_id: str,
        segment_id: str,
        retry_id: str,
    ) -> PromptRunSegmentRetryStatus:
        """Get the status of a previously dispatched segment retry."""
        response = self._client.get(
            f"/prompt-runs/{run_id}/videos/{video_id}/segments/{segment_id}/retries/{retry_id}"
        )
        return PromptRunSegmentRetryStatus.model_validate(response)

    def wait_for_completion(
        self,
        run_id: str,
        *,
        poll_interval: float = 5.0,
        timeout: Optional[float] = None,
    ) -> PromptRun:
        """
        Poll until a prompt run completes.

        Args:
            run_id: Prompt run ID
            poll_interval: Seconds between polls (default 5)
            timeout: Maximum seconds to wait (None for no timeout)

        Returns:
            PromptRun: Completed prompt run

        Raises:
            TimeoutError: If timeout is reached
            ProcessingError: If run fails
        """
        import time

        from .._exceptions import ProcessingError, TimeoutError

        start_time = time.time()

        while True:
            run = self.retrieve(run_id)
            status = (run.status or "").lower()

            if status in _TERMINAL_PROMPT_RUN_STATUSES:
                if status == "failed":
                    raise ProcessingError(
                        f"Prompt run failed: {run.error_message}",
                        details={"run_id": run_id},
                    )
                return run

            if timeout and (time.time() - start_time) > timeout:
                raise TimeoutError(
                    f"Prompt run did not complete within {timeout} seconds",
                    details={"run_id": run_id, "status": run.status},
                )

            time.sleep(poll_interval)


class AsyncPromptRunsResource:
    """
    Asynchronous Prompt Runs resource.

    Provides async methods for executing prompts and retrieving results.

    Example:
        async with AsyncVideoVector(api_key="<VIDEO_VECTOR_API_KEY>") as client:
            run = await client.prompt_runs.execute(
                prompt_id="prompt_123",
                target={"type": "index", "index_id": "idx_123"}
            )

            # Wait for completion
            run = await client.prompt_runs.wait_for_completion(run.run_id)
    """

    def __init__(self, client: "AsyncHttpClient") -> None:
        self._client = client

    async def execute(
        self,
        *,
        prompt_id: str,
        target: ExecutePromptTarget,
        video_segmentation_type: Literal["smart", "fixed", "content_aware"] = "smart",
        audio_segmentation_type: Literal["fixed", "content_aware"] = "content_aware",
        video_segment_duration: Optional[int] = None,
        audio_segment_duration: Optional[int] = None,
        processing_model: Optional[str] = None,
        enable_transcription: bool = True,
        enable_image_embedding: bool = True,
        idempotency_key: Optional[str] = None,
    ) -> PromptRun:
        """Execute a prompt on videos or an index."""
        body = _build_prompt_run_request_body(
            prompt_id=prompt_id,
            target=target,
            video_segmentation_type=video_segmentation_type,
            audio_segmentation_type=audio_segmentation_type,
            video_segment_duration=video_segment_duration,
            audio_segment_duration=audio_segment_duration,
            processing_model=processing_model,
            enable_transcription=enable_transcription,
            enable_image_embedding=enable_image_embedding,
        )
        resolved_idempotency_key = _resolve_generated_idempotency_key("execute", idempotency_key)
        response = await self._client.post(
            "/prompt-runs/execute",
            json=body,
            idempotency_key=resolved_idempotency_key,
        )
        return PromptRun.model_validate(response)

    async def list(self, *, limit: int = 200) -> List[PromptRun]:
        """List prompt runs accessible to the current user."""
        response = await self._client.get("/prompt-runs", params={"limit": limit})
        return [PromptRun.model_validate(run) for run in response]

    async def estimate(
        self,
        *,
        prompt_id: str,
        target: ExecutePromptTarget,
        video_segmentation_type: Literal["smart", "fixed", "content_aware"] = "smart",
        audio_segmentation_type: Literal["fixed", "content_aware"] = "content_aware",
        video_segment_duration: Optional[int] = None,
        audio_segment_duration: Optional[int] = None,
        processing_model: Optional[str] = None,
        enable_transcription: bool = True,
        enable_image_embedding: bool = True,
    ) -> PromptRunCostEstimate:
        """Estimate the billing cost of a prompt run without starting it."""
        body = _build_prompt_run_request_body(
            prompt_id=prompt_id,
            target=target,
            video_segmentation_type=video_segmentation_type,
            audio_segmentation_type=audio_segmentation_type,
            video_segment_duration=video_segment_duration,
            audio_segment_duration=audio_segment_duration,
            processing_model=processing_model,
            enable_transcription=enable_transcription,
            enable_image_embedding=enable_image_embedding,
        )
        response = await self._client.post("/prompt-runs/estimate", json=body)
        return PromptRunCostEstimate.model_validate(response)

    async def retrieve(self, run_id: str) -> PromptRun:
        """Retrieve a prompt run by ID."""
        response = await self._client.get(f"/prompt-runs/{run_id}")
        return PromptRun.model_validate(response)

    async def list_results(
        self,
        run_id: str,
        *,
        video_id: str,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> AsyncPage[SegmentRunResult]:
        """List extraction results for a prompt run."""
        params = {"limit": limit, "video_id": video_id}
        if cursor:
            params["cursor"] = cursor

        response = await self._client.get(f"/prompt-runs/{run_id}/results", params=params)
        return _parse_paginated_response_async(
            response=response,
            model=SegmentRunResult,
            client=self._client,
            endpoint=f"/prompt-runs/{run_id}/results",
            params={"limit": limit, "video_id": video_id},
        )

    async def get_llm_calls(self, run_id: str) -> List[LlmCall]:
        """Get LLM calls made during a prompt run."""
        response = await self._client.get(f"/prompt-runs/{run_id}/llm-calls")
        return [LlmCall.model_validate(call) for call in response]

    async def get_video_result(self, run_id: str, video_id: str) -> PromptRunVideoResult:
        """Get the video/audio-level synthesis result for one media item in a run."""
        response = await self._client.get(f"/prompt-runs/{run_id}/videos/{video_id}/video-result")
        return PromptRunVideoResult.model_validate(response)

    async def get_failed_segments(self, run_id: str) -> PromptRunFailedSegmentsManifest:
        """Get the failed segment manifest for a prompt run."""
        response = await self._client.get(f"/prompt-runs/{run_id}/failed-segments")
        return PromptRunFailedSegmentsManifest.model_validate(response)

    async def retry_segment(
        self,
        run_id: str,
        video_id: str,
        segment_id: str,
        *,
        idempotency_key: Optional[str] = None,
    ) -> PromptRunSegmentRetry:
        """Dispatch a retry for a failed segment inside a prompt run."""
        resolved_idempotency_key = _resolve_generated_idempotency_key(
            "segment-retry", idempotency_key
        )
        response = await self._client.post(
            f"/prompt-runs/{run_id}/videos/{video_id}/segments/{segment_id}/retry",
            idempotency_key=resolved_idempotency_key,
        )
        return PromptRunSegmentRetry.model_validate(response)

    async def cancel(
        self,
        run_id: str,
        *,
        idempotency_key: Optional[str] = None,
    ) -> PromptRun:
        """Request cancellation for a prompt run."""
        resolved_idempotency_key = _resolve_generated_idempotency_key("cancel", idempotency_key)
        response = await self._client.post(
            f"/prompt-runs/{run_id}/cancel",
            idempotency_key=resolved_idempotency_key,
        )
        return PromptRun.model_validate(response)

    async def get_segment_retry_status(
        self,
        run_id: str,
        video_id: str,
        segment_id: str,
        retry_id: str,
    ) -> PromptRunSegmentRetryStatus:
        """Get the status of a previously dispatched segment retry."""
        response = await self._client.get(
            f"/prompt-runs/{run_id}/videos/{video_id}/segments/{segment_id}/retries/{retry_id}"
        )
        return PromptRunSegmentRetryStatus.model_validate(response)

    async def wait_for_completion(
        self,
        run_id: str,
        *,
        poll_interval: float = 5.0,
        timeout: Optional[float] = None,
    ) -> PromptRun:
        """Poll until a prompt run completes."""
        import asyncio
        import time

        from .._exceptions import ProcessingError, TimeoutError

        start_time = time.time()

        while True:
            run = await self.retrieve(run_id)
            status = (run.status or "").lower()

            if status in _TERMINAL_PROMPT_RUN_STATUSES:
                if status == "failed":
                    raise ProcessingError(
                        f"Prompt run failed: {run.error_message}",
                        details={"run_id": run_id},
                    )
                return run

            if timeout and (time.time() - start_time) > timeout:
                raise TimeoutError(
                    f"Prompt run did not complete within {timeout} seconds",
                    details={"run_id": run_id, "status": run.status},
                )

            await asyncio.sleep(poll_interval)
