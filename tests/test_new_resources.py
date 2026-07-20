from __future__ import annotations

import asyncio
import inspect
import io
import threading
from pathlib import Path
from typing import Any, Optional, get_args, get_type_hints

import pytest

from videovector._exceptions import VideoVectorError
from videovector._types import FilterCondition
from videovector.resources.connectors import AsyncConnectorsResource, ConnectorsResource
from videovector.resources.exports import (
    DEFAULT_EXPORT_DOWNLOAD_MAX_BYTES,
    AsyncExportsResource,
    ExportsResource,
)
from videovector.resources.import_jobs import AsyncImportJobsResource, ImportJobsResource
from videovector.resources.indexes import AsyncIndexesResource, IndexesResource
from videovector.resources.prompt_runs import AsyncPromptRunsResource, PromptRunsResource
from videovector.resources.prompts import AsyncPromptsResource, PromptsResource
from videovector.resources.rate_limits import AsyncRateLimitsResource, RateLimitsResource
from videovector.resources.search import AsyncSearchResource, SearchResource
from videovector.resources.usage import AsyncUsageResource, UsageResource
from videovector.resources.videos import AsyncVideosResource, VideosResource
from videovector.resources.webhooks import AsyncWebhooksResource, WebhooksResource

VALID_EXPORT_DOWNLOAD_TOKEN = f"v1.{'a' * 64}.{'b' * 43}"


def test_export_download_default_matches_backend_artifact_ceiling() -> None:
    assert DEFAULT_EXPORT_DOWNLOAD_MAX_BYTES == 64 * 1024 * 1024


def test_filter_search_public_surface_is_canonical_only() -> None:
    for method in (
        SearchResource.filter,
        SearchResource.filter_playground,
        AsyncSearchResource.filter,
        AsyncSearchResource.filter_playground,
    ):
        assert "cursor" in inspect.signature(method).parameters
        assert "start_after" not in inspect.signature(method).parameters

    annotations = get_type_hints(FilterCondition)
    assert "fuzzyMatch" not in annotations
    assert set(get_args(annotations["type"])) == {"string", "integer", "number", "boolean", "array"}
    assert set(get_args(annotations["operator"])) == {
        "contains",
        "ends_with",
        "equals",
        "greater_equal",
        "greater_than",
        "is_empty",
        "is_not_empty",
        "item_contains",
        "item_equals",
        "length_equals",
        "length_greater",
        "length_less",
        "less_equal",
        "less_than",
        "starts_with",
    }
    assert not {"eq", "gt", "gte", "lt", "lte"} & set(get_args(annotations["operator"]))


def _marker_payload(marker_id: str = "marker_1", color: str = "blue") -> dict[str, Any]:
    return {
        "marker_id": marker_id,
        "color": color,
        "note": "review",
        "updated_at": "2026-01-01T00:00:00Z",
    }


def _video_processing_status_payload() -> dict[str, Any]:
    return {
        "run_id": "run_1",
        "prompt_id": "prompt_1",
        "status": "processing",
        "total_segments": 2,
        "pending_segments": 0,
        "processing_segments": 1,
        "successful_segments": 1,
        "failed_segments": 0,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:01Z",
        "attempt_id": "attempt_1",
        "video_level": {
            "status": "processing",
            "result_available": False,
            "successful_segment_count": 1,
            "failed_segment_count": 0,
            "started_at": "2026-01-01T00:00:00Z",
            "completed_at": None,
            "updated_at": "2026-01-01T00:00:01Z",
            "error_message": None,
            "attempt_id": "attempt_1",
        },
        "segments": [
            {
                "segment_id": "seg_1",
                "video_id": "video_1",
                "status": "processing",
                "start_time": 0.0,
                "end_time": 10.0,
                "started_at": "2026-01-01T00:00:00Z",
                "completed_at": None,
                "updated_at": "2026-01-01T00:00:01Z",
                "error_message": None,
                "failure_stage": None,
                "attempt_id": "attempt_seg_1",
            }
        ],
    }


def _video_level_payload() -> dict[str, Any]:
    return {
        "instructions_text": "Summarize the full video.",
        "included_segment_fields": ["summary", "transcription"],
        "json_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    }


def _index_payload() -> dict[str, Any]:
    return {
        "index_id": "idx_1",
        "name": "Archive",
        "user_id": "user_1",
        "created_at": "2026-01-01T00:00:00Z",
        "is_default": False,
    }


def _index_deletion_payload(status: str = "draining") -> dict[str, Any]:
    return {
        "index_id": "idx_1",
        "deletion_id": "index-delete-1",
        "status": status,
        "retry_after_seconds": None if status == "deleted" else 5,
    }


def _prompt_payload() -> dict[str, Any]:
    return {
        "prompt_id": "prompt_1",
        "user_id": "user_1",
        "name": "Prompt",
        "description": "Describe the video",
        "prompt_text": "Extract structured metadata from the segment.",
        "json_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
        "video_level": _video_level_payload(),
        "is_active": True,
        "created_at": "2026-01-01T00:00:00Z",
    }


def _prompt_run_payload() -> dict[str, Any]:
    return {
        "run_id": "run_1",
        "prompt_id": "prompt_1",
        "prompt_name": "Prompt",
        "prompt_type": "custom",
        "executed_at": "2026-01-01T00:00:00Z",
        "executed_by": "user_1",
        "status": "completed",
        "run_context": {"type": "index", "index_id": "idx_1"},
        "total_videos": 2,
        "completed_videos": 1,
        "failed_videos": 0,
        "partial_videos": 1,
        "total_audios": 1,
        "completed_audios": 1,
        "failed_audios": 0,
        "partial_audios": 0,
        "total_images": 0,
        "completed_images": 0,
        "failed_images": 0,
        "partial_images": 0,
        "total_segments": 10,
        "completed_segments": 8,
        "field_extraction_failures": 1,
        "transcription_failures": 0,
        "image_embedding_failures": 0,
        "field_extraction_succeeded": False,
        "transcription_succeeded": True,
        "image_embedding_succeeded": None,
        "error_message": None,
        "video_segmentation_type": "smart",
        "audio_segmentation_type": "content_aware",
        "image_segmentation_type": "image",
        "video_segment_duration": None,
        "audio_segment_duration": None,
        "created_new_segments": False,
        "processing_model": "gemini-2.5-flash",
        "total_video_seconds": 92.5,
        "enable_transcription": True,
        "enable_image_embedding": True,
        "video_level_enabled": True,
        "video_level_total_items": 3,
        "video_level_completed_items": 2,
        "video_level_failed_items": 0,
        "video_level_partial_items": 1,
        "billing_estimated_mt": 2.5,
        "billing_actual_mt": 2.25,
        "billing_status": "confirmed",
        "billing_error": None,
        "marker": {
            "marker_id": "marker_1",
            "color": "blue",
            "note": "review",
            "updated_at": "2026-01-01T00:00:00Z",
        },
    }


def _video_payload() -> dict[str, Any]:
    return {
        "video_id": "video_1",
        "title": "Demo",
        "video_uri": "gs://bucket/demo.mp4",
        "status": "processed",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:01Z",
        "metadata_keys": ["summary"],
        "media_type": "video",
        "processing_status": [_video_processing_status_payload()],
        "marker": _marker_payload(),
    }


def _video_deletion_payload(status: str = "deleting") -> dict[str, Any]:
    return {
        "video_id": "video_1",
        "deletion_id": "video-delete-1",
        "status": status,
        "retry_after_seconds": None if status == "deleted" else 5,
    }


def _search_result_payload() -> dict[str, Any]:
    return {
        "result_type": "segment",
        "result_id": "segment:seg_1:run_1",
        "segment_id": "seg_1",
        "video_id": "video_1",
        "video_name": "Episode 1",
        "start_time": 0.0,
        "end_time": 10.0,
        "preview_segment_id": "seg_1",
        "preview_start_time": 0.0,
        "preview_end_time": 10.0,
        "preview_segment_uri": "https://api.example.com/media/segment?token=segment",
        "preview_thumbnail_uri": "https://api.example.com/media/thumbnail?token=thumbnail",
        "preview_gif_uri": "https://api.example.com/media/gif?token=gif",
        "text_content": "demo",
        "metadata_text": "demo metadata",
        "similarity_score": 0.9,
        "reranked_score": 0.95,
        "gcs_uri": "gs://bucket/segments/seg_1.mp4",
        "thumbnail_gcs_uri": "gs://bucket/thumbnails/seg_1.jpg",
        "gif_gcs_uri": "gs://bucket/gifs/seg_1.gif",
        "media_type": "image",
        "metadata": {"summary": "full metadata"},
        "extracted_metadata": {"scene": "intro"},
        "run_id": "run_1",
        "source_run_id": "source_run_1",
        "prompt_run_id": "run_1",
        "raw_llm_response": '{"scene":"intro"}',
        "source_index_id": "idx_1",
        "marker": _marker_payload("marker_search_1", "green"),
        "extracted_metadata_markers": {
            "scene": _marker_payload("marker_scene_1", "yellow"),
        },
    }


def _segment_run_result_payload() -> dict[str, Any]:
    return {
        "result_type": "segment",
        "result_id": "segment:seg_1:run_1",
        "segment_id": "seg_1",
        "video_id": "video_1",
        "run_id": "run_1",
        "prompt_id": "prompt_1",
        "prompt_run_id": "run_1",
        "video_name": "Episode 1",
        "source_index_id": "idx_1",
        "executed_at": "2026-01-01T00:00:00Z",
        "start_time": 0.0,
        "end_time": 10.0,
        "segment_uri": "https://api.example.com/media/segment?token=segment",
        "gcs_uri": "gs://bucket/segments/seg_1.mp4",
        "thumbnail_uri": "https://api.example.com/media/thumbnail?token=thumbnail",
        "thumbnail_gcs_uri": "gs://bucket/thumbnails/seg_1.jpg",
        "gif_uri": "https://api.example.com/media/gif?token=gif",
        "gif_gcs_uri": "gs://bucket/gifs/seg_1.gif",
        "thumbnail_available": True,
        "gif_available": True,
        "metadata": {"summary": "demo"},
        "metadata_text": "demo",
        "processing_warning": None,
        "schema_used": '{"type":"object"}',
        "field_extraction_succeeded": True,
        "transcription_succeeded": True,
        "image_embedding_succeeded": None,
        "field_extraction_error": None,
        "transcription_error": None,
        "image_embedding_error": None,
        "metadata_markers": {
            "summary": {
                "marker_id": "marker_field_1",
                "color": "green",
                "note": "verified",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        },
    }


def _prompt_run_video_result_payload() -> dict[str, Any]:
    return {
        "result_type": "video",
        "result_id": "video:video_1:run_1",
        "run_id": "run_1",
        "prompt_id": "prompt_1",
        "prompt_run_id": "run_1",
        "video_id": "video_1",
        "video_name": "Episode 1",
        "source_index_id": "idx_1",
        "executed_at": "2026-01-01T00:00:00Z",
        "status": "completed",
        "metadata": {"summary": "Full video summary"},
        "metadata_text": "Full video summary",
        "raw_llm_response": "{}",
        "processing_warning": None,
        "schema_used": '{"type":"object"}',
        "successful_segment_count": 8,
        "failed_segment_count": 2,
        "omitted_segment_ids": ["seg_9"],
        "template_fields": ["summary"],
        "source_fingerprint": "fp_1",
        "rendered_prompt_char_count": 1200,
        "llm_attempted": True,
        "attempt_id": "attempt_1",
        "error_message": None,
        "started_at": "2026-01-01T00:00:00Z",
        "completed_at": "2026-01-01T00:00:02Z",
        "segment_uri": "https://api.example.com/media/segment?token=segment",
        "gcs_uri": "gs://bucket/segments/seg_1.mp4",
        "thumbnail_uri": "https://api.example.com/media/thumbnail?token=thumbnail",
        "thumbnail_gcs_uri": "gs://bucket/thumbnails/seg_1.jpg",
        "gif_uri": "https://api.example.com/media/gif?token=gif",
        "gif_gcs_uri": "gs://bucket/gifs/seg_1.gif",
        "thumbnail_available": True,
        "gif_available": True,
        "preview_segment_id": "seg_1",
        "preview_start_time": 0.0,
        "preview_end_time": 10.0,
        "preview_segment_uri": "https://api.example.com/media/segment?token=segment",
        "preview_thumbnail_uri": "https://api.example.com/media/thumbnail?token=thumbnail",
        "preview_gif_uri": "https://api.example.com/media/gif?token=gif",
    }


def _failed_segments_manifest_payload() -> dict[str, Any]:
    return {
        "run_id": "run_1",
        "status": "completed_with_failures",
        "videos_with_failures": 1,
        "failed_segments": 2,
        "operation_counts": {
            "field_extraction": 1,
            "transcription": 1,
            "image_embedding": 0,
            "processing": 0,
        },
        "videos": [
            {
                "video_id": "video_1",
                "failed_segments": 2,
                "operation_counts": {
                    "field_extraction": 1,
                    "transcription": 1,
                    "image_embedding": 0,
                    "processing": 0,
                },
                "segments": [
                    {
                        "segment_id": "seg_2",
                        "failed_operations": ["field_extraction"],
                        "field_extraction_error": "schema mismatch",
                        "transcription_error": None,
                        "image_embedding_error": None,
                        "failure_stage": "field_extraction",
                        "failure_message": "schema mismatch",
                        "failure_code": "schema_invalid",
                        "retryable": True,
                        "start_time": 10.0,
                        "end_time": 20.0,
                        "projection_only": False,
                    }
                ],
            }
        ],
    }


def _segment_retry_payload() -> dict[str, Any]:
    return {
        "run_id": "run_1",
        "retry_id": "retry_1",
        "status": "pending",
        "message": "retry queued",
        "idempotency_key": "retry-key-1",
        "video_id": "video_1",
        "segment_id": "seg_2",
        "created_at": "2026-01-01T00:00:00Z",
        "started_at": None,
        "completed_at": None,
        "error": None,
        "billing_estimated_mt": 1.25,
        "billing_actual_mt": 0.0,
        "billing_status": "pending",
        "billing_error": None,
    }


def _segment_retry_status_payload() -> dict[str, Any]:
    payload = _segment_retry_payload()
    payload.update(
        {
            "status": "completed",
            "started_at": "2026-01-01T00:00:01Z",
            "completed_at": "2026-01-01T00:00:04Z",
            "field_extraction_succeeded": True,
            "transcription_succeeded": True,
            "image_embedding_succeeded": None,
            "billing_status": "confirmed",
            "billing_actual_mt": 1.25,
        }
    )
    return payload


def _prompt_run_estimate_payload() -> dict[str, Any]:
    return {
        "estimated_mt": 12.5,
        "breakdown": {"base_estimate_mt": 10.0, "prompt_run_estimate": {"eligible_item_count": 3}},
        "sufficient_balance": True,
        "current_balance_mt": 100.0,
    }


def _connector_payload(provider: str = "gcs") -> dict[str, Any]:
    return {
        "connector_id": "conn_1",
        "name": "Archive",
        "provider": provider,
        "status": "active",
        "scopes": ["import", "export"],
        "import_mode": "new_only",
        "export_base_path": "exports/",
        "bucket": "bucket-a" if provider in {"gcs", "s3"} else None,
        "region": "us-east-1" if provider == "s3" else None,
        "storage_account": "storage-a" if provider == "azure" else None,
        "container": "video-container" if provider == "azure" else None,
        "gcp_project_id": "proj_1" if provider == "gcs" else None,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:01Z",
        "last_tested_at": None,
        "last_test_result": None,
        "last_test_error": None,
    }


def _export_create_payload(export_id: str) -> dict[str, Any]:
    return {
        "export_id": export_id,
        "status": "processing",
    }


def _import_job_payload() -> dict[str, Any]:
    return {
        "job_id": "job_1",
        "connector_id": "conn_1",
        "target_index_id": "idx_1",
        "source_prefix": "videos/",
        "file_pattern": "*.mp4",
        "recursive": True,
        "status": "pending",
        "created_at": "2026-01-01T00:00:00Z",
        "started_at": None,
        "completed_at": None,
        "error_message": None,
        "progress": {
            "total_files": 10,
            "imported": 0,
            "failed": 0,
            "skipped": 0,
            "bytes_transferred": 0,
            "current_file": None,
        },
        "video_ids": [],
        "failed_files": [],
        "skipped_files": [],
    }


def _webhook_payload() -> dict[str, Any]:
    return {
        "webhook_id": "wh_1",
        "name": "Prompt Terminal",
        "url": "https://example.com/webhook",
        "events": ["prompt.run.completed"],
        "index_ids": ["idx_1"],
        "status": "active",
        "failure_count": 0,
        "last_failure_at": None,
        "last_success_at": None,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "metadata": {"env": "test"},
    }


def _webhook_with_secret_payload() -> dict[str, Any]:
    return {
        **_webhook_payload(),
        "secret": "whsec_123",
    }


def _webhook_test_payload() -> dict[str, Any]:
    return {
        "success": True,
        "status_code": 200,
        "error": None,
    }


class _FakeSyncHttp:
    def __init__(self, responses: dict[tuple[str, str], Any]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []
        self.base_url = "https://api.example.test/api/v2"

    def get(
        self,
        endpoint: str,
        *,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> Any:
        self.calls.append({"method": "GET", "endpoint": endpoint, "params": params})
        return self.responses[("GET", endpoint)]

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
    ) -> Any:
        self.calls.append(
            {
                "method": "POST",
                "endpoint": endpoint,
                "json": json,
                "data": data,
                "files": files,
                "params": params,
                "idempotency_key": idempotency_key,
            }
        )
        return self.responses[("POST", endpoint)]

    def delete(
        self,
        endpoint: str,
        *,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> Any:
        self.calls.append({"method": "DELETE", "endpoint": endpoint, "params": params})
        return self.responses[("DELETE", endpoint)]

    def put(
        self,
        endpoint: str,
        *,
        json: Optional[dict[str, Any]] = None,
        data: Optional[dict[str, Any]] = None,
        files: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        self.calls.append(
            {
                "method": "PUT",
                "endpoint": endpoint,
                "json": json,
                "data": data,
                "files": files,
                "params": params,
                "idempotency_key": idempotency_key,
            }
        )
        return self.responses[("PUT", endpoint)]

    def patch(
        self,
        endpoint: str,
        *,
        json: Optional[dict[str, Any]] = None,
        data: Optional[dict[str, Any]] = None,
        files: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        self.calls.append(
            {
                "method": "PATCH",
                "endpoint": endpoint,
                "json": json,
                "data": data,
                "files": files,
                "params": params,
                "idempotency_key": idempotency_key,
            }
        )
        return self.responses[("PATCH", endpoint)]


class _FakeAsyncHttp(_FakeSyncHttp):
    async def get(
        self,
        endpoint: str,
        *,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> Any:
        return super().get(endpoint, params=params, headers=headers)

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
    ) -> Any:
        return super().post(
            endpoint,
            json=json,
            data=data,
            files=files,
            params=params,
            headers=headers,
            idempotency_key=idempotency_key,
        )

    async def delete(
        self,
        endpoint: str,
        *,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> Any:
        return super().delete(endpoint, params=params, headers=headers)

    async def put(
        self,
        endpoint: str,
        *,
        json: Optional[dict[str, Any]] = None,
        data: Optional[dict[str, Any]] = None,
        files: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        return super().put(
            endpoint,
            json=json,
            data=data,
            files=files,
            params=params,
            headers=headers,
            idempotency_key=idempotency_key,
        )

    async def patch(
        self,
        endpoint: str,
        *,
        json: Optional[dict[str, Any]] = None,
        data: Optional[dict[str, Any]] = None,
        files: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        return super().patch(
            endpoint,
            json=json,
            data=data,
            files=files,
            params=params,
            headers=headers,
            idempotency_key=idempotency_key,
        )


def test_prompts_resource_sync() -> None:
    http = _FakeSyncHttp(
        {
            ("POST", "/prompts"): _prompt_payload(),
            ("GET", "/prompts"): {
                "prompts": [_prompt_payload()],
                "total_count": 1,
                "active_count": 1,
            },
            ("GET", "/prompts/prompt_1"): _prompt_payload(),
            ("PUT", "/prompts/prompt_1"): {
                **_prompt_payload(),
                "name": "Prompt Updated",
                "description": "Updated description",
            },
            ("POST", "/prompts/test-schema"): {
                "valid": True,
                "validated_data": {"summary": "ok"},
                "error": None,
                "message": "Schema validation successful",
            },
            ("GET", "/prompts/prompt_1/usage"): {
                "prompt_id": "prompt_1",
                "name": "Prompt",
                "is_active": True,
                "is_in_use": True,
                "created_at": "2026-01-01T00:00:00Z",
                "schema_properties_count": 1,
            },
            ("DELETE", "/prompts/prompt_1"): {"message": "deleted"},
        }
    )
    resource = PromptsResource(http)  # type: ignore[arg-type]

    created = resource.create(
        name="Prompt",
        description="Describe the video",
        prompt_text="Extract structured metadata from the segment.",
        json_schema=_prompt_payload()["json_schema"],
        video_level=_video_level_payload(),
    )
    assert created.video_level is not None
    assert created.video_level.instructions_text == "Summarize the full video."
    assert http.calls[0]["json"]["video_level"] == _video_level_payload()
    assert str(http.calls[0]["idempotency_key"]).startswith("prompt-create:")

    listed = resource.list(active_only=True, include_defaults=True)
    assert listed.prompts[0].video_level is not None

    retrieved = resource.retrieve("prompt_1")
    assert retrieved.prompt_id == "prompt_1"

    updated = resource.update(
        "prompt_1",
        name="Prompt Updated",
        description="Updated description",
        prompt_text="Extract updated metadata from the segment.",
        json_schema={
            "type": "object",
            "properties": {"headline": {"type": "string"}},
            "required": ["headline"],
        },
        clear_video_level=True,
        idempotency_key="prompt-update-1",
    )
    assert updated.name == "Prompt Updated"
    assert http.calls[3]["json"] == {
        "name": "Prompt Updated",
        "description": "Updated description",
        "prompt_text": "Extract updated metadata from the segment.",
        "json_schema": {
            "type": "object",
            "properties": {"headline": {"type": "string"}},
            "required": ["headline"],
        },
        "clear_video_level": True,
    }
    assert http.calls[3]["idempotency_key"] == "prompt-update-1"

    schema_result = resource.test_schema(
        json_schema=_prompt_payload()["json_schema"],
        sample_data={"summary": "ok"},
    )
    assert schema_result.valid is True

    usage = resource.get_usage("prompt_1")
    assert usage.is_in_use is True

    deleted = resource.delete("prompt_1", force=True)
    assert deleted.message == "deleted"


def test_prompts_resource_async() -> None:
    http = _FakeAsyncHttp(
        {
            ("POST", "/prompts"): _prompt_payload(),
            ("GET", "/prompts"): {
                "prompts": [_prompt_payload()],
                "total_count": 1,
                "active_count": 1,
            },
            ("GET", "/prompts/prompt_1"): _prompt_payload(),
            ("PUT", "/prompts/prompt_1"): _prompt_payload(),
            ("POST", "/prompts/test-schema"): {
                "valid": True,
                "validated_data": {"summary": "ok"},
                "error": None,
                "message": "Schema validation successful",
            },
            ("GET", "/prompts/prompt_1/usage"): {
                "prompt_id": "prompt_1",
                "name": "Prompt",
                "is_active": True,
                "is_in_use": False,
                "created_at": "2026-01-01T00:00:00Z",
                "schema_properties_count": 1,
            },
            ("DELETE", "/prompts/prompt_1"): {"message": "deleted"},
        }
    )
    resource = AsyncPromptsResource(http)  # type: ignore[arg-type]

    async def _run() -> None:
        created = await resource.create(
            name="Prompt",
            prompt_text="Extract structured metadata from the segment.",
            json_schema=_prompt_payload()["json_schema"],
            video_level=_video_level_payload(),
        )
        assert created.video_level is not None
        assert str(http.calls[0]["idempotency_key"]).startswith("prompt-create:")

        listed = await resource.list()
        assert listed.total_count == 1

        retrieved = await resource.retrieve("prompt_1")
        assert retrieved.prompt_id == "prompt_1"

        updated = await resource.update(
            "prompt_1",
            prompt_text="Extract updated metadata from the segment.",
            video_level=_video_level_payload(),
        )
        assert updated.prompt_id == "prompt_1"
        assert str(http.calls[3]["idempotency_key"]).startswith("prompt-update:")

        schema_result = await resource.test_schema(
            json_schema=_prompt_payload()["json_schema"],
            sample_data={"summary": "ok"},
        )
        assert schema_result.valid is True

        usage = await resource.get_usage("prompt_1")
        assert usage.schema_properties_count == 1

        deleted = await resource.delete("prompt_1")
        assert deleted.message == "deleted"

    asyncio.run(_run())


def test_prompt_runs_resource_sync() -> None:
    http = _FakeSyncHttp(
        {
            ("GET", "/prompt-runs"): [_prompt_run_payload()],
            ("POST", "/prompt-runs/estimate"): _prompt_run_estimate_payload(),
            ("GET", "/prompt-runs/run_1"): _prompt_run_payload(),
            ("GET", "/prompt-runs/run_1/results"): {
                "data": [_segment_run_result_payload()],
                "pagination": {"limit": 50, "has_more": False, "next_cursor": None},
            },
            ("GET", "/prompt-runs/run_1/llm-calls"): [
                {
                    "llm_call_id": "llm_1",
                    "prompt_run_id": "run_1",
                    "prompt_id": "prompt_1",
                    "video_id": "video_1",
                    "segment_id": "seg_1",
                    "user_id": "user_1",
                    "model": "gemini-2.5-flash",
                    "purpose": "metadata_extraction",
                    "status": "success",
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                    "video_seconds": 10.0,
                    "prompt_text": "extract fields",
                    "response_text": "{}",
                    "schema_used": "{...}",
                    "invoked_at": "2026-01-01T00:00:00Z",
                    "completed_at": "2026-01-01T00:00:01Z",
                }
            ],
            (
                "GET",
                "/prompt-runs/run_1/videos/video_1/video-result",
            ): _prompt_run_video_result_payload(),
            ("GET", "/prompt-runs/run_1/failed-segments"): _failed_segments_manifest_payload(),
            ("POST", "/prompt-runs/run_1/cancel"): {**_prompt_run_payload(), "status": "cancelled"},
            (
                "POST",
                "/prompt-runs/run_1/videos/video_1/segments/seg_2/retry",
            ): _segment_retry_payload(),
            (
                "GET",
                "/prompt-runs/run_1/videos/video_1/segments/seg_2/retries/retry_1",
            ): _segment_retry_status_payload(),
        }
    )
    resource = PromptRunsResource(http)  # type: ignore[arg-type]

    runs = resource.list(limit=100)
    assert runs[0].marker.marker_id == "marker_1"
    assert runs[0].billing_status == "confirmed"
    assert runs[0].billing_actual_mt == 2.25
    assert http.calls[0]["params"] == {"limit": 100}

    estimate = resource.estimate(
        prompt_id="prompt_1",
        target={"type": "index", "index_id": "idx_1"},
        video_segmentation_type="fixed",
        video_segment_duration=15,
    )
    assert estimate.estimated_mt == 12.5
    assert http.calls[1]["json"] == {
        "prompt_id": "prompt_1",
        "target": {"type": "index", "index_id": "idx_1"},
        "video_segmentation_type": "fixed",
        "audio_segmentation_type": "content_aware",
        "video_segment_duration": 15,
        "enable_transcription": True,
        "enable_image_embedding": True,
    }

    retrieved = resource.retrieve("run_1")
    assert retrieved.video_level_enabled is True

    results = resource.list_results("run_1", video_id="video_1", limit=25)
    assert results.data[0].metadata_markers["summary"].marker_id == "marker_field_1"
    assert results.data[0].segment_uri == ("https://api.example.com/media/segment?token=segment")
    assert results.data[0].gcs_uri == "gs://bucket/segments/seg_1.mp4"
    assert results.data[0].thumbnail_gcs_uri == "gs://bucket/thumbnails/seg_1.jpg"
    assert results.data[0].gif_gcs_uri == "gs://bucket/gifs/seg_1.gif"

    llm_calls = resource.get_llm_calls("run_1")
    assert llm_calls[0].llm_call_id == "llm_1"

    video_result = resource.get_video_result("run_1", "video_1")
    assert video_result.llm_attempted is True
    assert video_result.segment_uri == ("https://api.example.com/media/segment?token=segment")
    assert video_result.gcs_uri == "gs://bucket/segments/seg_1.mp4"
    assert video_result.thumbnail_gcs_uri == "gs://bucket/thumbnails/seg_1.jpg"
    assert video_result.gif_gcs_uri == "gs://bucket/gifs/seg_1.gif"

    failed_segments = resource.get_failed_segments("run_1")
    assert failed_segments.videos[0].segments[0].retryable is True

    cancelled = resource.cancel("run_1", idempotency_key="run-cancel-1")
    assert cancelled.status == "cancelled"
    assert cancelled.billing_status == "confirmed"
    assert http.calls[7]["idempotency_key"] == "run-cancel-1"

    retry = resource.retry_segment("run_1", "video_1", "seg_2", idempotency_key="retry-key-1")
    assert retry.retry_id == "retry_1"
    assert retry.billing_status == "pending"
    assert http.calls[8]["idempotency_key"] == "retry-key-1"

    retry_status = resource.get_segment_retry_status("run_1", "video_1", "seg_2", "retry_1")
    assert retry_status.field_extraction_succeeded is True
    assert retry_status.billing_status == "confirmed"

    generated_retry = resource.retry_segment("run_1", "video_1", "seg_2")
    assert generated_retry.retry_id == "retry_1"
    assert http.calls[10]["idempotency_key"].startswith("prompt-run-segment-retry:")


def test_prompt_runs_resource_async() -> None:
    http = _FakeAsyncHttp(
        {
            ("GET", "/prompt-runs"): [_prompt_run_payload()],
            ("POST", "/prompt-runs/estimate"): _prompt_run_estimate_payload(),
            ("GET", "/prompt-runs/run_1"): _prompt_run_payload(),
            ("GET", "/prompt-runs/run_1/results"): {
                "data": [_segment_run_result_payload()],
                "pagination": {"limit": 50, "has_more": False, "next_cursor": None},
            },
            ("GET", "/prompt-runs/run_1/llm-calls"): [],
            (
                "GET",
                "/prompt-runs/run_1/videos/video_1/video-result",
            ): _prompt_run_video_result_payload(),
            ("GET", "/prompt-runs/run_1/failed-segments"): _failed_segments_manifest_payload(),
            ("POST", "/prompt-runs/run_1/cancel"): {**_prompt_run_payload(), "status": "cancelled"},
            (
                "POST",
                "/prompt-runs/run_1/videos/video_1/segments/seg_2/retry",
            ): _segment_retry_payload(),
            (
                "GET",
                "/prompt-runs/run_1/videos/video_1/segments/seg_2/retries/retry_1",
            ): _segment_retry_status_payload(),
        }
    )
    resource = AsyncPromptRunsResource(http)  # type: ignore[arg-type]

    async def _run() -> None:
        runs = await resource.list()
        assert runs[0].run_id == "run_1"
        assert runs[0].billing_status == "confirmed"

        estimate = await resource.estimate(
            prompt_id="prompt_1",
            target={"type": "index", "index_id": "idx_1"},
        )
        assert estimate.current_balance_mt == 100.0

        retrieved = await resource.retrieve("run_1")
        assert retrieved.partial_videos == 1

        results = await resource.list_results("run_1", video_id="video_1")
        assert results.data[0].segment_id == "seg_1"
        assert results.data[0].gcs_uri == "gs://bucket/segments/seg_1.mp4"
        assert results.data[0].thumbnail_gcs_uri == "gs://bucket/thumbnails/seg_1.jpg"
        assert results.data[0].gif_gcs_uri == "gs://bucket/gifs/seg_1.gif"

        llm_calls = await resource.get_llm_calls("run_1")
        assert llm_calls == []

        video_result = await resource.get_video_result("run_1", "video_1")
        assert video_result.video_id == "video_1"
        assert video_result.gcs_uri == "gs://bucket/segments/seg_1.mp4"
        assert video_result.thumbnail_gcs_uri == "gs://bucket/thumbnails/seg_1.jpg"
        assert video_result.gif_gcs_uri == "gs://bucket/gifs/seg_1.gif"

        failed_segments = await resource.get_failed_segments("run_1")
        assert failed_segments.failed_segments == 2

        cancelled = await resource.cancel("run_1")
        assert cancelled.status == "cancelled"
        assert cancelled.billing_status == "confirmed"
        assert http.calls[7]["idempotency_key"].startswith("prompt-run-cancel:")

        retry = await resource.retry_segment("run_1", "video_1", "seg_2")
        assert retry.status == "pending"
        assert retry.billing_status == "pending"
        assert http.calls[8]["idempotency_key"].startswith("prompt-run-segment-retry:")

        retry_status = await resource.get_segment_retry_status(
            "run_1", "video_1", "seg_2", "retry_1"
        )
        assert retry_status.status == "completed"
        assert retry_status.billing_status == "confirmed"

    asyncio.run(_run())


def test_prompt_runs_resource_sync_requires_video_id_for_list_results() -> None:
    http = _FakeSyncHttp({})
    resource = PromptRunsResource(http)  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        resource.list_results("run_1")


def test_prompt_runs_resource_async_requires_video_id_for_list_results() -> None:
    http = _FakeAsyncHttp({})
    resource = AsyncPromptRunsResource(http)  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        resource.list_results("run_1")


def test_prompt_runs_resource_sync_validates_fixed_segmentation_requests() -> None:
    http = _FakeSyncHttp({})
    resource = PromptRunsResource(http)  # type: ignore[arg-type]

    with pytest.raises(
        ValueError,
        match="video_segment_duration is required when video_segmentation_type is 'fixed'",
    ):
        resource.execute(
            prompt_id="prompt_1",
            target={"type": "index", "index_id": "idx_1"},
            video_segmentation_type="fixed",
        )

    assert http.calls == []


def test_prompt_runs_resource_async_validates_segmentation_options() -> None:
    http = _FakeAsyncHttp({})
    resource = AsyncPromptRunsResource(http)  # type: ignore[arg-type]

    async def _run() -> None:
        with pytest.raises(
            ValueError,
            match="audio_segment_duration is required when audio_segmentation_type is 'fixed'",
        ):
            await resource.estimate(
                prompt_id="prompt_1",
                target={"type": "index", "index_id": "idx_1"},
                audio_segmentation_type="fixed",
            )

    asyncio.run(_run())
    assert http.calls == []


def test_prompt_runs_resource_sync_validates_non_empty_video_targets() -> None:
    http = _FakeSyncHttp({})
    resource = PromptRunsResource(http)  # type: ignore[arg-type]

    with pytest.raises(
        ValueError,
        match="target.video_ids must be a non-empty array when target.type is 'videos'",
    ):
        resource.estimate(
            prompt_id="prompt_1",
            target={"type": "videos", "video_ids": []},
        )

    assert http.calls == []


def test_videos_prompt_runs_and_playground_sync() -> None:
    http = _FakeSyncHttp(
        {
            ("GET", "/videos/video_1/prompt-runs"): [_prompt_run_payload()],
            ("GET", "/playground/videos"): {
                "data": [_video_payload()],
                "pagination": {"limit": 50, "has_more": False, "next_cursor": None},
            },
        }
    )
    resource = VideosResource(http)  # type: ignore[arg-type]

    runs = resource.list_prompt_runs("video_1", limit=2)
    assert runs[0].run_id == "run_1"
    assert http.calls[0] == {
        "method": "GET",
        "endpoint": "/videos/video_1/prompt-runs",
        "params": {"limit": 2},
    }

    page = resource.list_playground(limit=50)
    assert len(page.data) == 1
    assert page.data[0].video_id == "video_1"
    assert page.data[0].marker.marker_id == "marker_1"
    assert page.data[0].processing_status[0].video_level.attempt_id == "attempt_1"


def test_videos_create_sync_adds_optional_source_connector_without_breaking_legacy_payload() -> (
    None
):
    http = _FakeSyncHttp({("POST", "/videos"): _video_payload()})
    resource = VideosResource(http)  # type: ignore[arg-type]

    resource.create(title="Demo", video_uri="gs://bucket/demo.mp4", index_id="idx_1")
    assert http.calls[-1]["json"] == {
        "title": "Demo",
        "video_uri": "gs://bucket/demo.mp4",
        "index_id": "idx_1",
    }

    resource.create(
        title="Private demo",
        video_uri="gs://private-bucket/demo.mp4",
        index_id="idx_1",
        source_connector_id="connector_1",
    )
    assert http.calls[-1]["json"] == {
        "title": "Private demo",
        "video_uri": "gs://private-bucket/demo.mp4",
        "index_id": "idx_1",
        "source_connector_id": "connector_1",
    }


def test_videos_prompt_runs_sync_omits_limit_when_unspecified() -> None:
    http = _FakeSyncHttp({("GET", "/videos/video_1/prompt-runs"): [_prompt_run_payload()]})
    resource = VideosResource(http)  # type: ignore[arg-type]

    runs = resource.list_prompt_runs("video_1")

    assert runs[0].run_id == "run_1"
    assert http.calls[0] == {
        "method": "GET",
        "endpoint": "/videos/video_1/prompt-runs",
        "params": None,
    }


def test_videos_prompt_runs_and_playground_async() -> None:
    http = _FakeAsyncHttp(
        {
            ("GET", "/videos/video_1/prompt-runs"): [_prompt_run_payload()],
            ("GET", "/playground/videos"): {
                "data": [_video_payload()],
                "pagination": {"limit": 50, "has_more": False, "next_cursor": None},
            },
        }
    )
    resource = AsyncVideosResource(http)  # type: ignore[arg-type]

    async def _run() -> None:
        runs = await resource.list_prompt_runs("video_1", limit=2)
        assert runs[0].run_id == "run_1"
        assert http.calls[0] == {
            "method": "GET",
            "endpoint": "/videos/video_1/prompt-runs",
            "params": {"limit": 2},
        }

        page = await resource.list_playground(limit=50)
        assert len(page.data) == 1
        assert page.data[0].marker.marker_id == "marker_1"
        assert page.data[0].processing_status[0].segments[0].attempt_id == "attempt_seg_1"

    asyncio.run(_run())


def test_videos_create_async_adds_optional_source_connector_without_breaking_legacy_payload() -> (
    None
):
    http = _FakeAsyncHttp({("POST", "/videos"): _video_payload()})
    resource = AsyncVideosResource(http)  # type: ignore[arg-type]

    async def _run() -> None:
        await resource.create(
            title="Demo",
            video_uri="gs://bucket/demo.mp4",
            index_id="idx_1",
        )
        assert http.calls[-1]["json"] == {
            "title": "Demo",
            "video_uri": "gs://bucket/demo.mp4",
            "index_id": "idx_1",
        }

        await resource.create(
            title="Private demo",
            video_uri="gs://private-bucket/demo.mp4",
            index_id="idx_1",
            source_connector_id="connector_1",
        )

    asyncio.run(_run())
    assert http.calls[-1]["json"] == {
        "title": "Private demo",
        "video_uri": "gs://private-bucket/demo.mp4",
        "index_id": "idx_1",
        "source_connector_id": "connector_1",
    }


def test_durable_index_and_video_deletion_sync() -> None:
    http = _FakeSyncHttp(
        {
            ("DELETE", "/indexes/idx_1"): _index_deletion_payload(),
            ("GET", "/indexes/idx_1/deletion"): _index_deletion_payload("deleted"),
            ("DELETE", "/videos/video_1"): _video_deletion_payload(),
            ("GET", "/videos/video_1/deletion"): _video_deletion_payload("deleted"),
        }
    )
    indexes = IndexesResource(http)  # type: ignore[arg-type]
    videos = VideosResource(http)  # type: ignore[arg-type]

    accepted_index = indexes.delete("idx_1")
    completed_index = indexes.get_deletion("idx_1")
    accepted_video = videos.delete("video_1")
    completed_video = videos.get_deletion("video_1")

    assert accepted_index.status == "draining"
    assert accepted_index.retry_after_seconds == 5
    assert completed_index.status == "deleted"
    assert completed_index.deletion_id == accepted_index.deletion_id
    assert accepted_video.status == "deleting"
    assert accepted_video.retry_after_seconds == 5
    assert completed_video.status == "deleted"
    assert completed_video.deletion_id == accepted_video.deletion_id
    assert [(call["method"], call["endpoint"]) for call in http.calls] == [
        ("DELETE", "/indexes/idx_1"),
        ("GET", "/indexes/idx_1/deletion"),
        ("DELETE", "/videos/video_1"),
        ("GET", "/videos/video_1/deletion"),
    ]


def test_durable_index_and_video_deletion_async() -> None:
    http = _FakeAsyncHttp(
        {
            ("DELETE", "/indexes/idx_1"): _index_deletion_payload(),
            ("GET", "/indexes/idx_1/deletion"): _index_deletion_payload("deleted"),
            ("DELETE", "/videos/video_1"): _video_deletion_payload(),
            ("GET", "/videos/video_1/deletion"): _video_deletion_payload("deleted"),
        }
    )
    indexes = AsyncIndexesResource(http)  # type: ignore[arg-type]
    videos = AsyncVideosResource(http)  # type: ignore[arg-type]

    async def _run() -> None:
        accepted_index = await indexes.delete("idx_1")
        completed_index = await indexes.get_deletion("idx_1")
        accepted_video = await videos.delete("video_1")
        completed_video = await videos.get_deletion("video_1")

        assert accepted_index.status == "draining"
        assert completed_index.status == "deleted"
        assert completed_index.deletion_id == accepted_index.deletion_id
        assert accepted_video.status == "deleting"
        assert completed_video.status == "deleted"
        assert completed_video.deletion_id == accepted_video.deletion_id

    asyncio.run(_run())
    assert [(call["method"], call["endpoint"]) for call in http.calls] == [
        ("DELETE", "/indexes/idx_1"),
        ("GET", "/indexes/idx_1/deletion"),
        ("DELETE", "/videos/video_1"),
        ("GET", "/videos/video_1/deletion"),
    ]


def test_videos_prompt_runs_async_omits_limit_when_unspecified() -> None:
    http = _FakeAsyncHttp({("GET", "/videos/video_1/prompt-runs"): [_prompt_run_payload()]})
    resource = AsyncVideosResource(http)  # type: ignore[arg-type]

    async def _run() -> None:
        runs = await resource.list_prompt_runs("video_1")
        assert runs[0].run_id == "run_1"
        assert http.calls[0] == {
            "method": "GET",
            "endpoint": "/videos/video_1/prompt-runs",
            "params": None,
        }

    asyncio.run(_run())


def test_search_filter_playground_sync() -> None:
    http = _FakeSyncHttp(
        {
            ("POST", "/search/filter/playground"): {
                "results": [_search_result_payload()],
                "next_page_token": None,
                "total_shown": 1,
            }
        }
    )
    resource = SearchResource(http)  # type: ignore[arg-type]

    result = resource.filter_playground(
        conditions=[{"field": "label", "operator": "equals", "value": "car", "type": "string"}],
        page_size=10,
    )
    assert result.total_shown == 1
    assert result.results[0].gcs_uri == "gs://bucket/segments/seg_1.mp4"
    assert result.results[0].thumbnail_gcs_uri == "gs://bucket/thumbnails/seg_1.jpg"
    assert result.results[0].gif_gcs_uri == "gs://bucket/gifs/seg_1.gif"
    assert result.results[0].media_type == "image"
    assert result.results[0].video_name == "Episode 1"
    assert result.results[0].metadata == {"summary": "full metadata"}
    assert result.results[0].extracted_metadata == {"scene": "intro"}
    assert result.results[0].metadata_text == "demo metadata"
    assert result.results[0].reranked_score == 0.95
    assert result.results[0].source_run_id == "source_run_1"
    assert result.results[0].prompt_run_id == "run_1"
    assert result.results[0].raw_llm_response == '{"scene":"intro"}'
    assert result.results[0].marker.marker_id == "marker_search_1"
    assert result.results[0].extracted_metadata_markers["scene"].marker_id == "marker_scene_1"


def test_search_filter_sync_uses_canonical_cursor_body_and_parses_paginated_shape() -> None:
    http = _FakeSyncHttp(
        {
            ("POST", "/search/filter/idx_1"): {
                "data": [_search_result_payload()],
                "pagination": {"limit": 10, "has_more": True, "next_cursor": "cursor_2"},
            }
        }
    )
    resource = SearchResource(http)  # type: ignore[arg-type]

    result = resource.filter(
        "idx_1",
        conditions=[{"field": "label", "operator": "equals", "value": "car", "type": "string"}],
        page_size=10,
        cursor="cursor_1",
        run_ids=["run_1"],
    )

    assert result.total_shown == 1
    assert result.next_page_token == "cursor_2"
    assert result.data[0].marker.marker_id == "marker_search_1"
    assert http.calls[0]["json"] == {
        "conditions": [{"field": "label", "operator": "equals", "value": "car", "type": "string"}],
        "page_size": 10,
        "cursor": "cursor_1",
        "run_ids": ["run_1"],
    }


def test_search_filter_rejects_noncanonical_conditions_before_request() -> None:
    http = _FakeSyncHttp({("POST", "/search/filter/idx_1"): {}})
    resource = SearchResource(http)  # type: ignore[arg-type]

    invalid_condition_sets = [
        [{"field": "label", "operator": "gte", "value": "car", "type": "string"}],
        [{"field": "label", "operator": "contains", "type": "string"}],
        [{"field": "label", "operator": "is_empty", "value": None, "type": "string"}],
        [{"field": "label", "operator": "greater_equal", "value": "car", "type": "string"}],
        [{"field": "label", "operator": "contains", "value": "car", "type": "unknown"}],
        [{"field": "score", "operator": "greater_equal", "value": "0.8", "type": "number"}],
        [{"field": "enabled", "operator": "equals", "value": "false", "type": "boolean"}],
        [{"field": "count", "operator": "greater_than", "value": 1.2, "type": "integer"}],
        [{"field": "tags", "operator": "item_contains", "value": 3, "type": "array"}],
        [{"field": "tags", "operator": "length_greater", "value": -1, "type": "array"}],
        [
            {
                "field": "label",
                "operator": "contains",
                "value": "car",
                "type": "string",
                "fuzzyMatch": True,
            }
        ],
        [
            {"field": "one", "operator": "equals", "value": "1", "type": "string"},
            {"field": "two", "operator": "equals", "value": "2", "type": "string"},
            {"field": "three", "operator": "equals", "value": "3", "type": "string"},
            {"field": "four", "operator": "equals", "value": "4", "type": "string"},
            {"field": "five", "operator": "equals", "value": "5", "type": "string"},
        ],
    ]

    for conditions in invalid_condition_sets:
        with pytest.raises(ValueError):
            resource.filter("idx_1", conditions=conditions)  # type: ignore[arg-type]

    assert http.calls == []


def test_search_filter_accepts_valueless_condition_without_value() -> None:
    http = _FakeSyncHttp(
        {
            ("POST", "/search/filter/idx_1"): {
                "data": [_search_result_payload()],
                "pagination": {"limit": 10, "has_more": False, "next_cursor": None},
            }
        }
    )
    resource = SearchResource(http)  # type: ignore[arg-type]

    resource.filter(
        "idx_1",
        conditions=[{"field": "label", "operator": "is_empty", "type": "string"}],
        page_size=10,
    )

    assert http.calls[0]["json"]["conditions"] == [
        {"field": "label", "operator": "is_empty", "type": "string"}
    ]


def test_search_filter_playground_async() -> None:
    http = _FakeAsyncHttp(
        {
            ("POST", "/search/filter/playground"): {
                "results": [_search_result_payload()],
                "next_page_token": None,
                "total_shown": 1,
            }
        }
    )
    resource = AsyncSearchResource(http)  # type: ignore[arg-type]

    async def _run() -> None:
        result = await resource.filter_playground(
            conditions=[{"field": "label", "operator": "equals", "value": "car", "type": "string"}],
        )
        assert result.total_shown == 1
        assert result.results[0].marker.color == "green"
        assert result.results[0].extracted_metadata_markers["scene"].color == "yellow"

    asyncio.run(_run())


def test_connectors_and_exports_sync() -> None:
    http = _FakeSyncHttp(
        {
            ("POST", "/connectors/gcs"): _connector_payload("gcs"),
            ("POST", "/connectors/s3"): _connector_payload("s3"),
            ("POST", "/connectors/azure"): _connector_payload("azure"),
            ("POST", "/exports/index/idx_1"): _export_create_payload("exp_1"),
            ("POST", "/exports/prompt-run/run_1"): _export_create_payload("exp_2"),
            ("POST", "/exports/exp_1/download-url"): {
                "export_id": "exp_1",
                "status": "completed",
                "destination_type": "download",
                "destination_connector_id": None,
                "download_url": (
                    "https://api.example.test/api/v2/exports/exp_1/download"
                    f"?token={VALID_EXPORT_DOWNLOAD_TOKEN}"
                ),
            },
        }
    )
    connectors = ConnectorsResource(http)  # type: ignore[arg-type]
    exports = ExportsResource(http)  # type: ignore[arg-type]

    gcs_connector = connectors.create_gcs(
        name="Archive",
        bucket="bucket-a",
        gcp_project_id="proj_1",
        credentials_file=io.BytesIO(b'{"type":"service_account"}'),
        scopes=["import", "export"],
        export_base_path="exports/",
        import_mode="new_only",
    )
    assert gcs_connector.import_mode == "new_only"
    assert http.calls[0]["data"] == {
        "name": "Archive",
        "bucket": "bucket-a",
        "gcp_project_id": "proj_1",
        "scopes": ["import", "export"],
        "import_mode": "new_only",
        "export_base_path": "exports/",
    }
    assert "credentials_file" in http.calls[0]["files"]
    assert str(http.calls[0]["idempotency_key"]).startswith("connector-create-gcs:")

    s3_connector = connectors.create_s3(
        name="Archive",
        bucket="bucket-a",
        region="us-east-1",
        aws_access_key_id="key",
        aws_secret_access_key="secret",
        scopes=["import", "export"],
        export_base_path="exports/",
        import_mode="new_only",
    )
    assert s3_connector.provider == "s3"
    assert http.calls[1]["json"]["import_mode"] == "new_only"
    assert str(http.calls[1]["idempotency_key"]).startswith("connector-create-s3:")

    azure_connector = connectors.create_azure(
        name="Archive",
        storage_account="storage-a",
        container="video-container",
        tenant_id="tenant-1",
        client_id="client-1",
        client_secret="secret",
        scopes=["import", "export"],
        export_base_path="exports/",
        import_mode="new_only",
    )
    assert azure_connector.provider == "azure"
    assert http.calls[2]["json"]["import_mode"] == "new_only"
    assert str(http.calls[2]["idempotency_key"]).startswith("connector-create-azure:")

    index_export = exports.create_index_export(
        "idx_1",
        prompt_run_ids=["run_1"],
        destination_connector_id="conn_1",
        destination_subpath="daily/",
        idempotency_key="idem-exp-1",
    )
    assert index_export.export_id == "exp_1"
    assert http.calls[3]["json"] == {
        "prompt_run_ids": ["run_1"],
        "destination_connector_id": "conn_1",
        "destination_subpath": "daily/",
    }
    assert http.calls[3]["params"] is None
    assert http.calls[3]["idempotency_key"] == "idem-exp-1"

    prompt_run_export = exports.create_prompt_run_export(
        "run_1",
        destination_connector_id="conn_1",
        destination_subpath="daily/",
        idempotency_key="idem-exp-2",
    )
    assert prompt_run_export.export_id == "exp_2"
    assert http.calls[4]["json"] == {
        "destination_connector_id": "conn_1",
        "destination_subpath": "daily/",
    }
    assert http.calls[4]["idempotency_key"] == "idem-exp-2"

    download_url = exports.download_url("exp_1")
    assert download_url == (
        "https://api.example.test/api/v2/exports/exp_1/download"
        f"?token={VALID_EXPORT_DOWNLOAD_TOKEN}"
    )
    assert http.calls[5] == {
        "method": "POST",
        "endpoint": "/exports/exp_1/download-url",
        "json": None,
        "data": None,
        "files": None,
        "params": None,
        "idempotency_key": None,
    }


def test_connectors_and_exports_async() -> None:
    http = _FakeAsyncHttp(
        {
            ("POST", "/connectors/gcs"): _connector_payload("gcs"),
            ("POST", "/connectors/s3"): _connector_payload("s3"),
            ("POST", "/connectors/azure"): _connector_payload("azure"),
            ("POST", "/exports/index/idx_1"): _export_create_payload("exp_1"),
            ("POST", "/exports/prompt-run/run_1"): _export_create_payload("exp_2"),
            ("POST", "/exports/exp_2/download-url"): {
                "export_id": "exp_2",
                "status": "completed",
                "destination_type": "connector",
                "destination_connector_id": "conn_1",
                "download_url": None,
            },
        }
    )
    connectors = AsyncConnectorsResource(http)  # type: ignore[arg-type]
    exports = AsyncExportsResource(http)  # type: ignore[arg-type]

    async def _run() -> None:
        gcs_connector = await connectors.create_gcs(
            name="Archive",
            bucket="bucket-a",
            gcp_project_id="proj_1",
            credentials_file=io.BytesIO(b'{"type":"service_account"}'),
            scopes=["import", "export"],
            export_base_path="exports/",
            import_mode="new_only",
        )
        assert gcs_connector.import_mode == "new_only"
        assert http.calls[0]["data"]["import_mode"] == "new_only"
        assert str(http.calls[0]["idempotency_key"]).startswith("connector-create-gcs:")

        s3_connector = await connectors.create_s3(
            name="Archive",
            bucket="bucket-a",
            region="us-east-1",
            aws_access_key_id="key",
            aws_secret_access_key="secret",
            scopes=["import", "export"],
            export_base_path="exports/",
            import_mode="new_only",
        )
        assert s3_connector.import_mode == "new_only"
        assert str(http.calls[1]["idempotency_key"]).startswith("connector-create-s3:")

        azure_connector = await connectors.create_azure(
            name="Archive",
            storage_account="storage-a",
            container="video-container",
            tenant_id="tenant-1",
            client_id="client-1",
            client_secret="secret",
            scopes=["import", "export"],
            export_base_path="exports/",
            import_mode="new_only",
        )
        assert azure_connector.import_mode == "new_only"
        assert str(http.calls[2]["idempotency_key"]).startswith("connector-create-azure:")

        index_export = await exports.create_index_export(
            "idx_1",
            prompt_run_ids=["run_1"],
            destination_connector_id="conn_1",
            destination_subpath="daily/",
        )
        assert index_export.export_id == "exp_1"
        assert http.calls[3]["json"] == {
            "prompt_run_ids": ["run_1"],
            "destination_connector_id": "conn_1",
            "destination_subpath": "daily/",
        }
        assert http.calls[3]["idempotency_key"].startswith("export-create:")

        prompt_run_export = await exports.create_prompt_run_export(
            "run_1",
            destination_connector_id="conn_1",
            destination_subpath="daily/",
        )
        assert prompt_run_export.export_id == "exp_2"
        assert http.calls[4]["json"] == {
            "destination_connector_id": "conn_1",
            "destination_subpath": "daily/",
        }
        assert http.calls[4]["idempotency_key"].startswith("export-create:")

        assert await exports.download_url("exp_2") is None
        assert http.calls[5] == {
            "method": "POST",
            "endpoint": "/exports/exp_2/download-url",
            "json": None,
            "data": None,
            "files": None,
            "params": None,
            "idempotency_key": None,
        }

    asyncio.run(_run())


def test_export_download_url_rejects_a_cross_export_response() -> None:
    http = _FakeSyncHttp(
        {
            ("POST", "/exports/exp_1/download-url"): {
                "export_id": "exp_2",
                "status": "completed",
                "destination_type": "download",
                "destination_connector_id": None,
                "download_url": (
                    "https://api.example.test/api/v2/exports/exp_2/download"
                    f"?token={VALID_EXPORT_DOWNLOAD_TOKEN}"
                ),
            },
        }
    )
    exports = ExportsResource(http)  # type: ignore[arg-type]

    with pytest.raises(VideoVectorError) as exc_info:
        exports.download_url("exp_1")

    assert exc_info.value.error_code == "invalid_export_download_url_response"
    assert exc_info.value.status_code == 502


@pytest.mark.parametrize("use_async_client", [False, True], ids=["sync", "async"])
def test_export_download_url_does_not_echo_response_derived_export_id(
    use_async_client: bool,
) -> None:
    response_credential = "v1.x.y"
    response = {
        "export_id": response_credential,
        "status": "completed",
        "destination_type": "download",
        "destination_connector_id": None,
        "download_url": (
            "https://api.example.test/api/v2/exports/exp_1/download"
            f"?token={VALID_EXPORT_DOWNLOAD_TOKEN}"
        ),
    }
    if use_async_client:
        http = _FakeAsyncHttp({("POST", "/exports/exp_1/download-url"): response})
        exports = AsyncExportsResource(http)  # type: ignore[arg-type]

        async def _call() -> None:
            await exports.download_url("exp_1")

        with pytest.raises(VideoVectorError) as exc_info:
            asyncio.run(_call())
    else:
        http = _FakeSyncHttp({("POST", "/exports/exp_1/download-url"): response})
        exports = ExportsResource(http)  # type: ignore[arg-type]
        with pytest.raises(VideoVectorError) as exc_info:
            exports.download_url("exp_1")

    error = exc_info.value
    assert error.error_code == "invalid_export_download_url_response"
    assert error.status_code == 502
    assert error.details == {}
    assert response_credential not in str(error)
    assert response_credential not in repr(error)
    assert response_credential not in repr(error.args)
    assert response_credential not in repr(error.details)
    assert error.__cause__ is None
    assert error.__context__ is None


def test_export_download_url_rejects_a_malformed_response_without_echoing_it() -> None:
    bearer_credential = "do-not-echo-this-bearer-credential"
    http = _FakeSyncHttp(
        {
            ("POST", "/exports/exp_1/download-url"): {
                "export_id": "exp_1",
                "status": "processing",
                "destination_type": "download",
                "destination_connector_id": None,
                "download_url": bearer_credential,
            },
        }
    )
    exports = ExportsResource(http)  # type: ignore[arg-type]

    with pytest.raises(VideoVectorError) as exc_info:
        exports.download_url("exp_1")

    assert exc_info.value.error_code == "invalid_export_download_url_response"
    assert exc_info.value.status_code == 502
    assert bearer_credential not in str(exc_info.value)
    assert bearer_credential not in repr(exc_info.value)
    assert bearer_credential not in repr(exc_info.value.args)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


@pytest.mark.parametrize("use_async_client", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize(
    "bearer_credential",
    [
        f"http://api.example.test/api/v2/exports/exp_1/download?token={VALID_EXPORT_DOWNLOAD_TOKEN}",
        f"https://attacker.example/api/v2/exports/exp_1/download?token={VALID_EXPORT_DOWNLOAD_TOKEN}",
        f"https://user:password@api.example.test/api/v2/exports/exp_1/download?token={VALID_EXPORT_DOWNLOAD_TOKEN}",
        f"https://api.example.test:444/api/v2/exports/exp_1/download?token={VALID_EXPORT_DOWNLOAD_TOKEN}",
        f"https://api.example.test:0/api/v2/exports/exp_1/download?token={VALID_EXPORT_DOWNLOAD_TOKEN}",
        f"https://api.example.test:/api/v2/exports/exp_1/download?token={VALID_EXPORT_DOWNLOAD_TOKEN}",
        f"https://api.example.test/api/v2/exports/exp_2/download?token={VALID_EXPORT_DOWNLOAD_TOKEN}",
        f"https://api.example.test/api/v2/exports/exp_1/download?token={VALID_EXPORT_DOWNLOAD_TOKEN}#credential",
        f"https://api.example.test/api/v2/exports/exp_1/download?token={VALID_EXPORT_DOWNLOAD_TOKEN}#",
        (
            "https://api.example.test/api/v2/exports/exp_1/download"
            f"?token={VALID_EXPORT_DOWNLOAD_TOKEN}&next=https%3A%2F%2Fattacker.example"
        ),
        (
            "https://api.example.test/api/v2/exports/exp_1/download"
            f"?token={VALID_EXPORT_DOWNLOAD_TOKEN}&token={VALID_EXPORT_DOWNLOAD_TOKEN}"
        ),
        (
            "https://api.example.test/api/v2/exports/exp_1/download"
            f"?access_token={VALID_EXPORT_DOWNLOAD_TOKEN}"
        ),
        ("https://api.example.test/api/v2/exports/exp_1/download" "?token=bad"),
        ("https://api.example.test/api/v2/exports/exp_1/download" "?token=v1.a.b"),
        (
            "https://api.example.test/api/v2/exports/exp_1/download?token=v1."
            + ("a" * 2048)
            + ".signature"
        ),
    ],
    ids=[
        "http",
        "host",
        "userinfo",
        "port",
        "zero-port",
        "empty-port",
        "cross-export-path",
        "fragment",
        "empty-fragment",
        "extra-query",
        "duplicate-token",
        "wrong-query-key",
        "token-shape",
        "token-too-short",
        "token-size",
    ],
)
def test_export_download_url_rejects_hostile_capability_shapes_without_echoing(
    bearer_credential: str,
    use_async_client: bool,
) -> None:
    response = {
        "export_id": "exp_1",
        "status": "completed",
        "destination_type": "download",
        "destination_connector_id": None,
        "download_url": bearer_credential,
    }
    if use_async_client:
        http = _FakeAsyncHttp({("POST", "/exports/exp_1/download-url"): response})
        exports = AsyncExportsResource(http)  # type: ignore[arg-type]

        async def _call() -> None:
            await exports.download_url("exp_1")

        with pytest.raises(VideoVectorError) as exc_info:
            asyncio.run(_call())
    else:
        http = _FakeSyncHttp({("POST", "/exports/exp_1/download-url"): response})
        exports = ExportsResource(http)  # type: ignore[arg-type]
        with pytest.raises(VideoVectorError) as exc_info:
            exports.download_url("exp_1")

    error = exc_info.value
    assert error.error_code == "invalid_export_download_url_response"
    assert error.status_code == 502
    assert bearer_credential not in str(error)
    assert bearer_credential not in repr(error)
    assert bearer_credential not in repr(error.args)
    assert error.__cause__ is None
    assert error.__context__ is None


@pytest.mark.parametrize("use_async_client", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize(
    "configured_base_url",
    [
        "http://api.example.test/api/v2",
        "https://api.example.test/custom/v2",
        "https://api.example.test/api/v2?tenant=unsafe",
        "https://api.example.test/api/v2?",
        "https://api.example.test/api/v2#",
        "https://api.example.test/api/v2/",
        "https://user:password@api.example.test/api/v2",
    ],
    ids=[
        "http",
        "path",
        "query",
        "empty-query",
        "empty-fragment",
        "trailing-slash",
        "userinfo",
    ],
)
def test_export_download_url_fails_closed_for_noncanonical_configured_api_origin(
    configured_base_url: str,
    use_async_client: bool,
) -> None:
    bearer_credential = (
        "https://api.example.test/api/v2/exports/exp_1/download"
        f"?token={VALID_EXPORT_DOWNLOAD_TOKEN}"
    )
    response = {
        "export_id": "exp_1",
        "status": "completed",
        "destination_type": "download",
        "destination_connector_id": None,
        "download_url": bearer_credential,
    }
    if use_async_client:
        http = _FakeAsyncHttp({("POST", "/exports/exp_1/download-url"): response})
        http.base_url = configured_base_url
        exports = AsyncExportsResource(http)  # type: ignore[arg-type]

        async def _call() -> None:
            await exports.download_url("exp_1")

        with pytest.raises(VideoVectorError) as exc_info:
            asyncio.run(_call())
    else:
        http = _FakeSyncHttp({("POST", "/exports/exp_1/download-url"): response})
        http.base_url = configured_base_url
        exports = ExportsResource(http)  # type: ignore[arg-type]
        with pytest.raises(VideoVectorError) as exc_info:
            exports.download_url("exp_1")

    error = exc_info.value
    assert error.error_code == "invalid_export_download_url_response"
    assert bearer_credential not in str(error)
    assert error.__cause__ is None
    assert error.__context__ is None


class _StreamingSyncHttp:
    def __init__(self, chunks: list[bytes], *, fail_after: Optional[int] = None) -> None:
        self.chunks = chunks
        self.fail_after = fail_after
        self.calls: list[dict[str, Any]] = []

    def iter_bytes(
        self,
        endpoint: str,
        *,
        chunk_size: int,
        max_bytes: int,
    ) -> Any:
        self.calls.append(
            {
                "endpoint": endpoint,
                "chunk_size": chunk_size,
                "max_bytes": max_bytes,
            }
        )
        for index, chunk in enumerate(self.chunks):
            if self.fail_after is not None and index >= self.fail_after:
                raise RuntimeError("interrupted")
            yield chunk


class _StreamingAsyncHttp:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.calls: list[dict[str, Any]] = []

    async def iter_bytes(
        self,
        endpoint: str,
        *,
        chunk_size: int,
        max_bytes: int,
    ) -> Any:
        self.calls.append(
            {
                "endpoint": endpoint,
                "chunk_size": chunk_size,
                "max_bytes": max_bytes,
            }
        )
        for chunk in self.chunks:
            yield chunk


def test_exports_download_streams_to_atomic_path(tmp_path: Path) -> None:
    http = _StreamingSyncHttp([b'{"a":', b"1}"])
    exports = ExportsResource(http)  # type: ignore[arg-type]
    destination = tmp_path / "export.json"

    written = exports.download(
        "exp_1",
        destination,
        chunk_size=7,
        max_bytes=100,
    )

    assert written == 7
    assert destination.read_bytes() == b'{"a":1}'
    assert list(tmp_path.glob("*.part")) == []
    assert http.calls == [
        {
            "endpoint": "/exports/exp_1/download",
            "chunk_size": 7,
            "max_bytes": 100,
        }
    ]


def test_exports_download_interruption_preserves_existing_destination(tmp_path: Path) -> None:
    http = _StreamingSyncHttp([b"partial", b"never"], fail_after=1)
    exports = ExportsResource(http)  # type: ignore[arg-type]
    destination = tmp_path / "export.json"
    destination.write_bytes(b"existing")

    with pytest.raises(RuntimeError, match="interrupted"):
        exports.download("exp_1", destination)

    assert destination.read_bytes() == b"existing"
    assert list(tmp_path.glob("*.part")) == []


def test_exports_download_async_streams_without_buffering(tmp_path: Path) -> None:
    http = _StreamingAsyncHttp([b"first", b"-second"])
    exports = AsyncExportsResource(http)  # type: ignore[arg-type]
    destination = tmp_path / "async-export.json"

    async def _run() -> int:
        return await exports.download(
            "exp_async",
            destination,
            chunk_size=11,
            max_bytes=200,
        )

    assert asyncio.run(_run()) == 12
    assert destination.read_bytes() == b"first-second"
    assert http.calls == [
        {
            "endpoint": "/exports/exp_async/download",
            "chunk_size": 11,
            "max_bytes": 200,
        }
    ]


def test_exports_download_async_cancellation_during_open_closes_handle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    http = _StreamingAsyncHttp([b"should-not-start"])
    exports = AsyncExportsResource(http)  # type: ignore[arg-type]
    destination = tmp_path / "async-export.json"
    destination.write_bytes(b"existing")
    open_started = threading.Event()
    allow_open = threading.Event()
    opened_handle = io.BytesIO()
    original_open = Path.open

    def delayed_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path.suffix == ".part":
            open_started.set()
            assert allow_open.wait(timeout=5)
            return opened_handle
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", delayed_open)

    async def _run() -> None:
        task = asyncio.create_task(exports.download("exp_async", destination))
        assert await asyncio.to_thread(open_started.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        allow_open.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_run())

    assert opened_handle.closed
    assert destination.read_bytes() == b"existing"
    assert list(tmp_path.glob("*.part")) == []
    assert http.calls == []


def test_import_jobs_idempotency_sync() -> None:
    http = _FakeSyncHttp(
        {
            ("POST", "/import-jobs"): _import_job_payload(),
            ("POST", "/import-jobs/job_1/cancel"): {**_import_job_payload(), "status": "cancelled"},
        }
    )
    resource = ImportJobsResource(http)  # type: ignore[arg-type]

    created = resource.create(
        connector_id="conn_1",
        index_id="idx_1",
        source_prefix="videos/",
        file_pattern="*.mp4",
        recursive=True,
    )
    assert created.job_id == "job_1"
    assert http.calls[0]["idempotency_key"].startswith("import-job-create:")

    created_with_key = resource.create(
        connector_id="conn_1",
        index_id="idx_1",
        idempotency_key="import-idem-1",
    )
    assert created_with_key.job_id == "job_1"
    assert http.calls[1]["idempotency_key"] == "import-idem-1"

    cancelled = resource.cancel("job_1")
    assert cancelled.status == "cancelled"
    assert str(http.calls[2]["idempotency_key"]).startswith("import-job-cancel:")

    cancelled_with_key = resource.cancel("job_1", idempotency_key="import-cancel-1")
    assert cancelled_with_key.status == "cancelled"
    assert http.calls[3]["idempotency_key"] == "import-cancel-1"


def test_import_jobs_idempotency_async() -> None:
    http = _FakeAsyncHttp(
        {
            ("POST", "/import-jobs"): _import_job_payload(),
            ("POST", "/import-jobs/job_1/cancel"): {**_import_job_payload(), "status": "cancelled"},
        }
    )
    resource = AsyncImportJobsResource(http)  # type: ignore[arg-type]

    async def _run() -> None:
        created = await resource.create(
            connector_id="conn_1",
            index_id="idx_1",
        )
        assert created.job_id == "job_1"
        assert http.calls[0]["idempotency_key"].startswith("import-job-create:")

        created_with_key = await resource.create(
            connector_id="conn_1",
            index_id="idx_1",
            idempotency_key="import-idem-1",
        )
        assert created_with_key.job_id == "job_1"
        assert http.calls[1]["idempotency_key"] == "import-idem-1"

        cancelled = await resource.cancel("job_1")
        assert cancelled.status == "cancelled"
        assert str(http.calls[2]["idempotency_key"]).startswith("import-job-cancel:")

        cancelled_with_key = await resource.cancel("job_1", idempotency_key="import-cancel-1")
        assert cancelled_with_key.status == "cancelled"
        assert http.calls[3]["idempotency_key"] == "import-cancel-1"

    asyncio.run(_run())


def test_indexes_and_webhooks_idempotency_sync() -> None:
    http = _FakeSyncHttp(
        {
            ("POST", "/indexes"): _index_payload(),
            ("POST", "/webhooks"): _webhook_with_secret_payload(),
            ("PATCH", "/webhooks/wh_1"): {**_webhook_payload(), "name": "Prompt Terminal Updated"},
            ("POST", "/webhooks/wh_1/test"): _webhook_test_payload(),
        }
    )
    indexes = IndexesResource(http)  # type: ignore[arg-type]
    webhooks = WebhooksResource(http)  # type: ignore[arg-type]

    index = indexes.create(name="Archive")
    assert index.index_id == "idx_1"
    assert str(http.calls[0]["idempotency_key"]).startswith("index-create:")

    webhook = webhooks.create(
        name="Prompt Terminal",
        url="https://example.com/webhook",
        events=["prompt.run.completed"],
        index_ids=["idx_1"],
        metadata={"env": "test"},
    )
    assert webhook.secret == "whsec_123"
    assert str(http.calls[1]["idempotency_key"]).startswith("webhook-create:")

    updated = webhooks.update(
        "wh_1",
        name="Prompt Terminal Updated",
        idempotency_key="webhook-update-1",
    )
    assert updated.name == "Prompt Terminal Updated"
    assert http.calls[2]["idempotency_key"] == "webhook-update-1"

    test_result = webhooks.test("wh_1")
    assert test_result.success is True
    assert str(http.calls[3]["idempotency_key"]).startswith("webhook-test:")


def test_indexes_and_webhooks_idempotency_async() -> None:
    http = _FakeAsyncHttp(
        {
            ("POST", "/indexes"): _index_payload(),
            ("POST", "/webhooks"): _webhook_with_secret_payload(),
            ("PATCH", "/webhooks/wh_1"): {**_webhook_payload(), "name": "Prompt Terminal Updated"},
            ("POST", "/webhooks/wh_1/test"): _webhook_test_payload(),
        }
    )
    indexes = AsyncIndexesResource(http)  # type: ignore[arg-type]
    webhooks = AsyncWebhooksResource(http)  # type: ignore[arg-type]

    async def _run() -> None:
        index = await indexes.create(name="Archive")
        assert index.index_id == "idx_1"
        assert str(http.calls[0]["idempotency_key"]).startswith("index-create:")

        webhook = await webhooks.create(
            name="Prompt Terminal",
            url="https://example.com/webhook",
            events=["prompt.run.completed"],
            index_ids=["idx_1"],
            metadata={"env": "test"},
        )
        assert webhook.secret == "whsec_123"
        assert str(http.calls[1]["idempotency_key"]).startswith("webhook-create:")

        updated = await webhooks.update("wh_1", name="Prompt Terminal Updated")
        assert updated.name == "Prompt Terminal Updated"
        assert str(http.calls[2]["idempotency_key"]).startswith("webhook-update:")

        test_result = await webhooks.test("wh_1", idempotency_key="webhook-test-1")
        assert test_result.success is True
        assert http.calls[3]["idempotency_key"] == "webhook-test-1"

    asyncio.run(_run())


def test_connector_create_bodies_omit_empty_export_base_path() -> None:
    http = _FakeSyncHttp(
        {
            ("POST", "/connectors/s3"): _connector_payload("s3"),
            ("POST", "/connectors/azure"): _connector_payload("azure"),
        }
    )
    connectors = ConnectorsResource(http)  # type: ignore[arg-type]

    connectors.create_s3(
        name="Archive",
        bucket="bucket-a",
        region="us-east-1",
        aws_access_key_id="key",
        aws_secret_access_key="secret",
    )
    assert "export_base_path" not in http.calls[0]["json"]

    connectors.create_azure(
        name="Archive",
        storage_account="storage-a",
        container="video-container",
        tenant_id="tenant-1",
        client_id="client-1",
        client_secret="secret",
    )
    assert "export_base_path" not in http.calls[1]["json"]


def test_connector_create_bodies_omit_empty_export_base_path_async() -> None:
    http = _FakeAsyncHttp(
        {
            ("POST", "/connectors/s3"): _connector_payload("s3"),
            ("POST", "/connectors/azure"): _connector_payload("azure"),
        }
    )
    connectors = AsyncConnectorsResource(http)  # type: ignore[arg-type]

    async def _run() -> None:
        await connectors.create_s3(
            name="Archive",
            bucket="bucket-a",
            region="us-east-1",
            aws_access_key_id="key",
            aws_secret_access_key="secret",
        )
        assert "export_base_path" not in http.calls[0]["json"]

        await connectors.create_azure(
            name="Archive",
            storage_account="storage-a",
            container="video-container",
            tenant_id="tenant-1",
            client_id="client-1",
            client_secret="secret",
        )
        assert "export_base_path" not in http.calls[1]["json"]

    asyncio.run(_run())


def test_usage_and_rate_limits_sync() -> None:
    http = _FakeSyncHttp(
        {
            ("GET", "/usage"): {
                "user_id": "u1",
                "period_start": "2026-01-01T00:00:00Z",
                "period_end": "2026-01-31T23:59:59Z",
                "metrics": {"search_queries": 10.0},
                "model_usage": {},
                "auth_usage": {},
                "totals": {"total_tokens": 100, "total_searches": 10},
            },
            ("GET", "/usage/history"): {
                "user_id": "u1",
                "periods": [
                    {
                        "summary_id": "sum_1",
                        "period_start": "2026-01-01T00:00:00Z",
                        "period_end": "2026-01-31T23:59:59Z",
                        "metrics": {"search_queries": 10.0},
                        "model_usage": {},
                        "auth_usage": {},
                        "totals": {"total_tokens": 100, "total_searches": 10},
                    }
                ],
            },
            ("GET", "/usage/details"): [
                {
                    "event_id": "ev_1",
                    "metric_type": "search_queries",
                    "value": 1.0,
                    "unit": "count",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "metadata": {"query": "car"},
                }
            ],
            ("GET", "/usage/breakdown"): {
                "user_id": "u1",
                "period_start": "2026-01-01T00:00:00Z",
                "period_end": "2026-01-31T23:59:59Z",
                "breakdown": {"search_queries": 10.0},
                "totals": {
                    "total_tokens": 100,
                    "total_searches": 10,
                    "total_storage_bytes": 1000,
                    "total_videos_uploaded": 2,
                    "total_videos_processed": 2,
                    "total_segments_created": 10,
                },
            },
            ("GET", "/usage/metric-types"): [
                {"type": "search_queries", "description": "Searches", "unit": "count"}
            ],
            ("GET", "/rate-limit/status"): {
                "user_id": "u1",
                "plan_id": "free",
                "categories": {
                    "search": {
                        "minute_used": 1,
                        "minute_limit": 60,
                        "minute_remaining": 59,
                        "hour_used": 10,
                        "hour_limit": 1000,
                        "hour_remaining": 990,
                        "reset_at": 1730000000,
                    }
                },
            },
            ("POST", "/rate-limit/refresh"): {
                "user_id": "u1",
                "plan_id": "free",
                "categories": {
                    "search": {
                        "minute_used": 1,
                        "minute_limit": 60,
                        "minute_remaining": 59,
                        "hour_used": 10,
                        "hour_limit": 1000,
                        "hour_remaining": 990,
                        "reset_at": 1730000000,
                    }
                },
            },
        }
    )
    usage = UsageResource(http)  # type: ignore[arg-type]
    rate_limits = RateLimitsResource(http)  # type: ignore[arg-type]

    assert usage.get_current().user_id == "u1"
    assert usage.get_history().user_id == "u1"
    assert len(usage.get_details()) == 1
    assert usage.get_breakdown().user_id == "u1"
    assert len(usage.get_metric_types()) == 1

    assert rate_limits.get_status().plan_id == "free"
    assert rate_limits.refresh().plan_id == "free"


def test_usage_and_rate_limits_async() -> None:
    http = _FakeAsyncHttp(
        {
            ("GET", "/usage"): {
                "user_id": "u1",
                "period_start": "2026-01-01T00:00:00Z",
                "period_end": "2026-01-31T23:59:59Z",
                "metrics": {"search_queries": 10.0},
                "model_usage": {},
                "auth_usage": {},
                "totals": {"total_tokens": 100, "total_searches": 10},
            },
            ("GET", "/usage/history"): {"user_id": "u1", "periods": []},
            ("GET", "/usage/details"): [],
            ("GET", "/usage/breakdown"): {
                "user_id": "u1",
                "period_start": "2026-01-01T00:00:00Z",
                "period_end": "2026-01-31T23:59:59Z",
                "breakdown": {},
                "totals": {
                    "total_tokens": 0,
                    "total_searches": 0,
                    "total_storage_bytes": 0,
                    "total_videos_uploaded": 0,
                    "total_videos_processed": 0,
                    "total_segments_created": 0,
                },
            },
            ("GET", "/usage/metric-types"): [],
            ("GET", "/rate-limit/status"): {
                "user_id": "u1",
                "plan_id": "free",
                "categories": {
                    "search": {
                        "minute_used": 1,
                        "minute_limit": 60,
                        "minute_remaining": 59,
                        "hour_used": 10,
                        "hour_limit": 1000,
                        "hour_remaining": 990,
                        "reset_at": 1730000000,
                    }
                },
            },
            ("POST", "/rate-limit/refresh"): {
                "user_id": "u1",
                "plan_id": "free",
                "categories": {
                    "search": {
                        "minute_used": 1,
                        "minute_limit": 60,
                        "minute_remaining": 59,
                        "hour_used": 10,
                        "hour_limit": 1000,
                        "hour_remaining": 990,
                        "reset_at": 1730000000,
                    }
                },
            },
        }
    )
    usage = AsyncUsageResource(http)  # type: ignore[arg-type]
    rate_limits = AsyncRateLimitsResource(http)  # type: ignore[arg-type]

    async def _run() -> None:
        assert (await usage.get_current()).user_id == "u1"
        assert (await usage.get_history()).user_id == "u1"
        assert (await usage.get_details()) == []
        assert (await usage.get_breakdown()).user_id == "u1"
        assert (await usage.get_metric_types()) == []
        assert (await rate_limits.get_status()).plan_id == "free"
        assert (await rate_limits.refresh()).plan_id == "free"

    asyncio.run(_run())
