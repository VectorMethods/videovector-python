from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

import pytest

from videovector.resources.workflow import AsyncWorkflowResource, WorkflowResource


def _prompt_payload() -> dict[str, Any]:
    return {
        "prompt_id": "prompt_1",
        "user_id": "user_1",
        "name": "Products",
        "description": "Find products",
        "prompt_text": "Extract products",
        "json_schema": {"type": "object", "properties": {}},
        "semantic_indexing": {
            "disabled_segment_fields": [],
            "disabled_video_level_fields": [],
        },
        "is_active": True,
        "created_at": "2026-01-01T00:00:00Z",
    }


def _run_payload(status: str = "pending") -> dict[str, Any]:
    return {
        "run_id": "run_1",
        "prompt_id": "prompt_1",
        "prompt_name": "Products",
        "prompt_type": "custom",
        "executed_at": "2026-01-01T00:00:00Z",
        "executed_by": "user_1",
        "status": status,
        "run_context": {"is_playground": True},
    }


def _search_page(cursor: Optional[str]) -> dict[str, Any]:
    return {
        "data": [
            {
                "result_type": "segment",
                "result_id": "segment:seg_1:run_1",
                "segment_id": "seg_1",
                "video_id": "video_1",
                "text_content": "red bicycle",
                "similarity_score": 0.9,
                "reranked_score": 0.93,
                "preview_segment_id": "seg_preview",
                "preview_start_time": 4.0,
                "preview_end_time": 7.0,
                "preview_segment_uri": "https://media.example/preview.mp4",
                "media_type": "video",
                "metadata": {"brand": "Acme"},
                "matched_image_gcs_uri": "gs://bucket/match.jpg",
                "matched_image_uri": "https://media.example/match.jpg",
                "matched_image_timestamp": 5.5,
                "run_id": "run_1",
            }
        ],
        "mode": "vector",
        "result_level": "segment",
        "scope": {"type": "playground"},
        "coverage": {},
        "warnings": [],
        "pagination": {
            "limit": 1,
            "count": 1,
            "has_more": cursor is not None,
            "next_cursor": cursor,
            "result_window": 100,
            "truncated": False,
        },
    }


class CaptureSyncHttp:
    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []
        self.gets: list[dict[str, Any]] = []
        self.run_statuses = ["processing", "completed"]

    def post(self, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        self.posts.append({"endpoint": endpoint, **kwargs})
        if endpoint == "/workflow/process":
            return {
                "prompt": _prompt_payload(),
                "run": _run_payload(),
                "status_url": "/api/v2/prompt-runs/run_1",
                "prompt_created_inline": True,
            }
        if endpoint == "/workflow/search":
            return _search_page("cursor-2")
        if endpoint == "/workflow/define":
            return {
                "prompt_id": "prompt_1",
                "saved": True,
                "definition": {
                    "name": "Products",
                    "description": "Find products",
                    "prompt_text": "Extract products",
                    "json_schema": {"type": "object", "properties": {}},
                    "semantic_indexing": {
                        "disabled_segment_fields": [],
                        "disabled_video_level_fields": [],
                    },
                },
                "prompt": _prompt_payload(),
            }
        return {
            "video": {
                "video_id": "video_1",
                "title": "demo",
                "video_uri": "gs://bucket/demo.mp4",
                "status": "uploaded",
                "message": "ok",
                "media_type": "video",
                "duration_seconds": 12.5,
                "thumbnail_gcs_uri": "gs://bucket/demo.jpg",
                "thumbnail_uri": "https://media.example/demo.jpg",
                "thumbnail_available": True,
            },
            "destination": {
                "type": "playground",
                "index_created": False,
            },
        }

    def get(self, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        self.gets.append({"endpoint": endpoint, **kwargs})
        if endpoint == "/workflow/search/page":
            return _search_page(None)
        return _run_payload(self.run_statuses.pop(0))


class CaptureAsyncHttp(CaptureSyncHttp):
    async def post(self, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        return super().post(endpoint, **kwargs)

    async def get(self, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        return super().get(endpoint, **kwargs)


def test_process_uses_low_cost_defaults_and_inline_prompt() -> None:
    http = CaptureSyncHttp()
    response = WorkflowResource(http).process(prompt_instruction="Find products")  # type: ignore[arg-type]

    assert response.run.run_id == "run_1"
    assert response.prompt_created_inline is True
    request = http.posts[-1]
    assert request["endpoint"] == "/workflow/process"
    assert request["json"] == {
        "prompt_instruction": "Find products",
        "segmentation_mode": "smart",
        "advanced_transcription": False,
        "create_image_embeddings": False,
    }
    assert request["idempotency_key"].startswith("workflow-process:")


def test_fixed_processing_defaults_duration_on_backend_and_validates_other_modes() -> None:
    http = CaptureSyncHttp()
    resource = WorkflowResource(http)  # type: ignore[arg-type]
    resource.process(prompt_id="prompt_1", segmentation_mode="fixed")
    assert "fixed_segment_duration_seconds" not in http.posts[-1]["json"]

    with pytest.raises(ValueError, match="accepted only"):
        resource.process(
            prompt_id="prompt_1",
            segmentation_mode="smart",
            fixed_segment_duration_seconds=10,
        )


def test_search_uses_post_then_get_cursor_pages() -> None:
    http = CaptureSyncHttp()
    page = WorkflowResource(http).search("red bicycle", limit=1)  # type: ignore[arg-type]
    assert page.has_more is True
    assert page.data[0].run_id == "run_1"
    assert page.data[0].preview_segment_id == "seg_preview"
    assert page.data[0].preview_segment_uri == "https://media.example/preview.mp4"
    assert page.data[0].reranked_score == 0.93
    assert page.data[0].media_type == "video"
    assert page.data[0].metadata == {"brand": "Acme"}
    assert page.data[0].matched_image_uri == "https://media.example/match.jpg"

    second = page.next_page()
    assert second is not None
    assert second.has_more is False
    assert http.gets[-1] == {
        "endpoint": "/workflow/search/page",
        "params": {"cursor": "cursor-2"},
    }


def test_search_cursor_rejects_ignored_search_arguments() -> None:
    resource = WorkflowResource(CaptureSyncHttp())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="cannot be combined"):
        resource.search("red bicycle", cursor="cursor-2")

    with pytest.raises(ValueError, match="must not be blank"):
        resource.search(cursor="  ")


def test_upload_streams_path_and_generates_key(tmp_path: Path) -> None:
    source = tmp_path / "demo.mp4"
    source.write_bytes(b"video")
    http = CaptureSyncHttp()

    response = WorkflowResource(http).upload(source)  # type: ignore[arg-type]

    assert response.video.video_id == "video_1"
    assert response.video.duration_seconds == 12.5
    assert response.video.thumbnail_gcs_uri == "gs://bucket/demo.jpg"
    assert response.video.thumbnail_uri == "https://media.example/demo.jpg"
    assert response.video.thumbnail_available is True
    request = http.posts[-1]
    assert request["endpoint"] == "/workflow/upload"
    assert request["idempotency_key"].startswith("workflow-upload:")
    assert request["files"]["file"][0] == "demo.mp4"


def test_wait_until_searchable() -> None:
    http = CaptureSyncHttp()
    run = WorkflowResource(http).wait_until_searchable(  # type: ignore[arg-type]
        "run_1", poll_interval=0, timeout=1
    )
    assert run.status == "completed"


def test_async_workflow_surface_parity(tmp_path: Path) -> None:
    source = tmp_path / "demo.mp4"
    source.write_bytes(b"video")

    async def run() -> None:
        http = CaptureAsyncHttp()
        resource = AsyncWorkflowResource(http)  # type: ignore[arg-type]

        uploaded = await resource.upload(source, index_name="Field Review Clips")
        assert uploaded.video.video_id == "video_1"
        assert http.posts[-1]["idempotency_key"].startswith("workflow-upload:")

        defined = await resource.define("Find products")
        assert defined.prompt_id == "prompt_1"
        assert http.posts[-1]["idempotency_key"].startswith("workflow-define:")

        processed = await resource.process(prompt_id="prompt_1")
        assert processed.run.run_id == "run_1"

        first = await resource.search(filters=[{"field": "brand", "value": "Acme"}], limit=1)
        second = await first.next_page()
        assert second is not None and not second.has_more

        with pytest.raises(ValueError, match="cannot be combined"):
            await resource.search(cursor="cursor-2", video_ids=["video_1"])

        searchable = await resource.wait_until_searchable("run_1", poll_interval=0, timeout=1)
        assert searchable.status == "completed"

    asyncio.run(run())
