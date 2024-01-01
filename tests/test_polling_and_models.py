from __future__ import annotations

import asyncio
from typing import Any, Optional

import pytest

from videovector._types import (
    Export,
    FilterSearchResponse,
    ImageSearchResult,
    LlmCall,
    MultimodalSearchResult,
    SearchResult,
    SegmentRunResult,
)
from videovector.resources.import_jobs import AsyncImportJobsResource, ImportJobsResource
from videovector.resources.prompt_runs import AsyncPromptRunsResource, PromptRunsResource


def _prompt_run_payload(status: str) -> dict[str, Any]:
    return {
        "run_id": "run_1",
        "prompt_id": "prompt_1",
        "prompt_name": "Prompt",
        "prompt_type": "custom",
        "executed_at": "2026-01-01T00:00:00Z",
        "executed_by": "user_1",
        "status": status,
        "run_context": {"type": "index", "index_id": "idx_1"},
    }


def _import_job_payload(status: str) -> dict[str, Any]:
    return {
        "job_id": "job_1",
        "connector_id": "conn_1",
        "target_index_id": "idx_1",
        "source_prefix": "",
        "status": status,
        "progress": {
            "total_files": 0,
            "imported": 0,
            "failed": 0,
            "skipped": 0,
            "bytes_transferred": 0,
            "current_file": None,
        },
    }


class _FakeSyncHttp:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = responses
        self._idx = 0

    def get(
        self,
        endpoint: str,
        *,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        response = self._responses[self._idx]
        self._idx += 1
        return response


class _FakeAsyncHttp:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = responses
        self._idx = 0

    async def get(
        self,
        endpoint: str,
        *,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        response = self._responses[self._idx]
        self._idx += 1
        return response


class _CaptureSyncPostHttp:
    def __init__(self) -> None:
        self.last_post: Optional[dict[str, Any]] = None

    def post(
        self,
        endpoint: str,
        *,
        json: Optional[dict[str, Any]] = None,
        data: Optional[dict[str, Any]] = None,
        files: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        self.last_post = {
            "endpoint": endpoint,
            "json": json,
            "idempotency_key": idempotency_key,
        }
        return _prompt_run_payload("pending")


class _CaptureAsyncPostHttp(_CaptureSyncPostHttp):
    async def post(
        self,
        endpoint: str,
        *,
        json: Optional[dict[str, Any]] = None,
        data: Optional[dict[str, Any]] = None,
        files: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        return super().post(
            endpoint,
            json=json,
            data=data,
            files=files,
            params=params,
            headers=headers,
            idempotency_key=idempotency_key,
        )


def test_prompt_runs_wait_for_completion_accepts_lowercase_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http = _FakeSyncHttp([_prompt_run_payload("processing"), _prompt_run_payload("completed")])
    resource = PromptRunsResource(http)  # type: ignore[arg-type]
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)

    run = resource.wait_for_completion("run_1", poll_interval=0.0, timeout=5.0)
    assert run.status == "completed"


def test_prompt_runs_wait_for_completion_async_accepts_lowercase_status() -> None:
    http = _FakeAsyncHttp([_prompt_run_payload("processing"), _prompt_run_payload("completed")])
    resource = AsyncPromptRunsResource(http)  # type: ignore[arg-type]

    async def _run() -> None:
        run = await resource.wait_for_completion("run_1", poll_interval=0.0, timeout=5.0)
        assert run.status == "completed"

    asyncio.run(_run())


def test_prompt_runs_wait_for_completion_accepts_completed_with_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http = _FakeSyncHttp(
        [_prompt_run_payload("processing"), _prompt_run_payload("completed_with_failures")]
    )
    resource = PromptRunsResource(http)  # type: ignore[arg-type]
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)

    run = resource.wait_for_completion("run_1", poll_interval=0.0, timeout=5.0)
    assert run.status == "completed_with_failures"


def test_prompt_runs_wait_for_completion_async_accepts_completed_with_failures() -> None:
    http = _FakeAsyncHttp(
        [_prompt_run_payload("processing"), _prompt_run_payload("completed_with_failures")]
    )
    resource = AsyncPromptRunsResource(http)  # type: ignore[arg-type]

    async def _run() -> None:
        run = await resource.wait_for_completion("run_1", poll_interval=0.0, timeout=5.0)
        assert run.status == "completed_with_failures"

    asyncio.run(_run())


def test_prompt_runs_wait_for_completion_accepts_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http = _FakeSyncHttp([_prompt_run_payload("processing"), _prompt_run_payload("cancelled")])
    resource = PromptRunsResource(http)  # type: ignore[arg-type]
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)

    run = resource.wait_for_completion("run_1", poll_interval=0.0, timeout=5.0)
    assert run.status == "cancelled"


def test_prompt_runs_wait_for_completion_async_accepts_cancelled() -> None:
    http = _FakeAsyncHttp([_prompt_run_payload("processing"), _prompt_run_payload("cancelled")])
    resource = AsyncPromptRunsResource(http)  # type: ignore[arg-type]

    async def _run() -> None:
        run = await resource.wait_for_completion("run_1", poll_interval=0.0, timeout=5.0)
        assert run.status == "cancelled"

    asyncio.run(_run())


def test_import_jobs_wait_for_completion_accepts_lowercase_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http = _FakeSyncHttp([_import_job_payload("importing"), _import_job_payload("completed")])
    resource = ImportJobsResource(http)  # type: ignore[arg-type]
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)

    job = resource.wait_for_completion("job_1", poll_interval=0.0, timeout=5.0)
    assert job.status == "completed"


def test_import_jobs_wait_for_completion_async_accepts_lowercase_status() -> None:
    http = _FakeAsyncHttp([_import_job_payload("importing"), _import_job_payload("completed")])
    resource = AsyncImportJobsResource(http)  # type: ignore[arg-type]

    async def _run() -> None:
        job = await resource.wait_for_completion("job_1", poll_interval=0.0, timeout=5.0)
        assert job.status == "completed"

    asyncio.run(_run())


def test_prompt_runs_execute_generates_idempotency_key_when_missing() -> None:
    http = _CaptureSyncPostHttp()
    resource = PromptRunsResource(http)  # type: ignore[arg-type]

    run = resource.execute(
        prompt_id="prompt_1",
        target={"type": "index", "index_id": "idx_1"},
    )

    assert run.run_id == "run_1"
    assert http.last_post is not None
    assert http.last_post["endpoint"] == "/prompt-runs/execute"
    generated_key = str(http.last_post["idempotency_key"] or "")
    assert generated_key.startswith("prompt-run-execute:")
    assert len(generated_key) > len("prompt-run-execute:")


def test_prompt_runs_execute_preserves_explicit_idempotency_key() -> None:
    http = _CaptureSyncPostHttp()
    resource = PromptRunsResource(http)  # type: ignore[arg-type]

    resource.execute(
        prompt_id="prompt_1",
        target={"type": "index", "index_id": "idx_1"},
        idempotency_key="custom-key-1",
    )

    assert http.last_post is not None
    assert http.last_post["idempotency_key"] == "custom-key-1"


def test_prompt_runs_execute_async_generates_idempotency_key_when_missing() -> None:
    http = _CaptureAsyncPostHttp()
    resource = AsyncPromptRunsResource(http)  # type: ignore[arg-type]

    async def _run() -> None:
        run = await resource.execute(
            prompt_id="prompt_1",
            target={"type": "index", "index_id": "idx_1"},
        )
        assert run.run_id == "run_1"
        assert http.last_post is not None
        generated_key = str(http.last_post["idempotency_key"] or "")
        assert generated_key.startswith("prompt-run-execute:")

    asyncio.run(_run())


def test_export_model_accepts_backend_payload_without_user_id() -> None:
    payload = {
        "export_id": "exp_1",
        "export_type": "index",
        "target_id": "idx_1",
        "created_at": "2026-01-01T00:00:00Z",
        "status": "processing",
        "download_url": None,
        "file_size_bytes": None,
        "error_message": None,
    }
    export = Export.model_validate(payload)
    assert export.export_id == "exp_1"


def test_filter_search_response_accepts_paginated_backend_shape() -> None:
    payload = {
        "data": [
            {
                "result_type": "segment",
                "result_id": "segment:seg_1:run_1",
                "segment_id": "seg_1",
                "video_id": "video_1",
                "text_content": "car",
                "similarity_score": 0.9,
            }
        ],
        "pagination": {
            "limit": 10,
            "has_more": True,
            "next_cursor": "cursor_2",
        },
    }

    response = FilterSearchResponse.model_validate(payload)

    assert response.total_shown == 1
    assert response.next_page_token == "cursor_2"
    assert response.results[0].segment_id == "seg_1"
    assert response.data[0].segment_id == "seg_1"


def test_llm_call_model_accepts_invoked_at_schema() -> None:
    payload = {
        "llm_call_id": "llm_1",
        "prompt_run_id": "run_1",
        "prompt_id": "prompt_1",
        "video_id": "video_1",
        "segment_id": "seg_1",
        "user_id": "user_1",
        "model": "gemini-2.5-flash",
        "purpose": "metadata_extraction",
        "status": "success",
        "input_tokens": 123,
        "output_tokens": 45,
        "total_tokens": 168,
        "video_seconds": 30.0,
        "segment_start_time": 0.0,
        "segment_end_time": 10.0,
        "prompt_text": "extract fields",
        "response_text": "{}",
        "schema_used": "{...}",
        "error_message": None,
        "invoked_at": "2026-01-01T00:00:00Z",
        "completed_at": "2026-01-01T00:00:01Z",
    }
    call = LlmCall.model_validate(payload)
    assert call.invoked_at == "2026-01-01T00:00:00Z"


def test_segment_run_result_accepts_video_id() -> None:
    payload = {
        "segment_id": "seg_1",
        "video_id": "video_1",
        "run_id": "run_1",
        "prompt_id": "prompt_1",
        "executed_at": "2026-01-01T00:00:00Z",
        "metadata": {"label": "x"},
        "metadata_text": "x",
    }
    result = SegmentRunResult.model_validate(payload)
    assert result.video_id == "video_1"


@pytest.mark.parametrize("result_type", [ImageSearchResult, MultimodalSearchResult])
def test_visual_search_result_preserves_durable_matched_image_uri(
    result_type: type[ImageSearchResult] | type[MultimodalSearchResult],
) -> None:
    payload: dict[str, Any] = {
        "result_id": "segment:seg_1:run_1",
        "video_id": "video_1",
        "segment_id": "seg_1",
        "text_content": "sample",
        "similarity_score": 0.87,
        "matched_image_uri": "https://media.example.test/bounded",
        "matched_image_gcs_uri": "gs://managed-media/users/user_1/shots/shot_1.jpg",
        "shot_timestamp": 10.9,
    }
    if result_type is MultimodalSearchResult:
        payload.update(fused_score=0.91, match_type="both")

    result = result_type.model_validate(payload)

    assert result.matched_image_uri == "https://media.example.test/bounded"
    assert result.matched_image_gcs_uri == "gs://managed-media/users/user_1/shots/shot_1.jpg"
    assert result.shot_timestamp == 10.9


def test_multimodal_search_result_defaults_durable_matched_image_uri_to_none() -> None:
    result = MultimodalSearchResult.model_validate(
        {
            "result_id": "segment:seg_1:run_1",
            "video_id": "video_1",
            "segment_id": "seg_1",
            "text_content": "sample",
            "similarity_score": 0.87,
            "fused_score": 0.91,
            "match_type": "both",
            "shot_timestamp": 10.9,
        }
    )

    assert result.matched_image_gcs_uri is None
    assert result.shot_timestamp == 10.9


def test_search_result_preserves_nullable_similarity_and_metadata() -> None:
    result = SearchResult.model_validate(
        {
            "result_id": "video:video_1:run_1",
            "result_type": "video",
            "video_id": "video_1",
            "text_content": "sample",
            "similarity_score": None,
            "metadata": {"summary": "full metadata"},
            "extracted_metadata": None,
        }
    )

    assert result.similarity_score is None
    assert result.metadata == {"summary": "full metadata"}
    assert result.extracted_metadata is None
