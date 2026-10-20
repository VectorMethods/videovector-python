"""Manifest iteration preserves every part across the public 100-item page size."""

import asyncio
from typing import Any

from videovector.resources.import_jobs import AsyncImportJobsResource, ImportJobsResource


def page(cursor: Any) -> dict[str, Any]:
    start, end = (100, 103) if cursor else (0, 100)
    return {
        "items": [
            {
                "file_id": "file",
                "file_name": "long.mp4",
                "source_ordinal": 0,
                "part_index": i,
                "part_count": 103,
                "source_start_seconds": i * 2400,
                "source_end_seconds": (i + 1) * 2400,
                "video_id": f"video_{i}",
                "title": f"Part {i + 1}",
                "status": "completed",
            }
            for i in range(start, end)
        ],
        "next_cursor": "cursor-2" if end == 100 else None,
        "total": 103,
    }


class SyncHttp:
    def get(self, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        assert endpoint == "/import-jobs/job/outputs"
        return page(kwargs["params"].get("cursor"))


class AsyncHttp:
    async def get(self, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        return SyncHttp().get(endpoint, **kwargs)


def test_every_output_is_returned_once_sync_and_async() -> None:
    outputs = list(ImportJobsResource(SyncHttp()).iter_outputs("job"))  # type: ignore[arg-type]
    assert [item.video_id for item in outputs] == [f"video_{i}" for i in range(103)]

    async def collect() -> list[str]:
        resource = AsyncImportJobsResource(AsyncHttp())  # type: ignore[arg-type]
        return [item.video_id async for item in resource.iter_outputs("job")]

    assert asyncio.run(collect()) == [item.video_id for item in outputs]


def test_source_failure_pages_preserve_retry_details_sync_and_async() -> None:
    class SourceHttp:
        def get(self, endpoint: str, **kwargs: Any) -> dict[str, Any]:
            assert endpoint == "/import-jobs/job/files"
            assert kwargs["params"]["failed_only"] is True
            second = bool(kwargs["params"].get("cursor"))
            return {
                "items": [
                    {
                        "file_id": "last" if second else "first",
                        "file_name": "source.mp4",
                        "source_ordinal": int(second),
                        "status": "failed",
                        "failure": {
                            "error_code": "attachment_download_failed",
                            "refresh_required": True,
                        },
                    }
                ],
                "next_cursor": None if second else "source-cursor",
                "total": 2,
            }

    class AsyncSourceHttp:
        async def get(self, endpoint: str, **kwargs: Any) -> dict[str, Any]:
            return SourceHttp().get(endpoint, **kwargs)

    files = list(ImportJobsResource(SourceHttp()).iter_files("job", failed_only=True))  # type: ignore[arg-type]
    assert [file.file_id for file in files] == ["first", "last"]
    assert all(file.failure and file.failure["refresh_required"] for file in files)

    async def collect() -> list[str]:
        resource = AsyncImportJobsResource(AsyncSourceHttp())  # type: ignore[arg-type]
        return [file.file_id async for file in resource.iter_files("job", failed_only=True)]

    assert asyncio.run(collect()) == [file.file_id for file in files]


def test_unplanned_source_and_failure_cursor_round_trip() -> None:
    from videovector import ImportJob, ImportSourceFile

    source = ImportSourceFile.model_validate(
        {
            "file_id": "pending",
            "file_name": "source.mp4",
            "source_ordinal": 0,
            "status": "pending",
            "part_count": None,
            "parts_completed": None,
            "parts_failed": None,
            "failure": None,
        }
    )
    assert source.part_count is None
    job = ImportJob.model_validate(
        {
            "job_id": "job",
            "status": "failed",
            "progress": {"failed": 101},
            "failed_files_next_cursor": "after-first-page",
        }
    )
    assert job.failed_files_next_cursor == "after-first-page"
