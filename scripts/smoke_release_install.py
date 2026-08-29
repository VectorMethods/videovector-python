#!/usr/bin/env python3
"""Exercise the installed SDK's public sync/async release contract without network I/O."""

from __future__ import annotations

import argparse
import asyncio
import inspect

from videovector import (
    AsyncVideoVector,
    BatchVideoSegmentsTarget,
    VideoSegments,
    VideoVector,
    __version__,
)


def verify(expected_version: str) -> None:
    if __version__ != expected_version:
        raise RuntimeError(
            f"installed SDK version {__version__!r} differs from {expected_version!r}"
        )
    target = BatchVideoSegmentsTarget(video_id="video_1", run_id="run_1")
    segments = VideoSegments(video_id=target.video_id, run_id=target.run_id, segments=[])
    if segments.run_id != "run_1":
        raise RuntimeError("VideoSegments.run_id is not preserved")

    sync_client = VideoVector(
        api_key="release-smoke-key",
        base_url="https://release-smoke.invalid/api/v2",
    )
    try:
        if not callable(sync_client.videos.batch_segments_for_targets):
            raise RuntimeError("sync batch_segments_for_targets is unavailable")
        if not callable(sync_client.videos.get_signed_url):
            raise RuntimeError("sync get_signed_url is unavailable")
    finally:
        sync_client.close()

    async_client = AsyncVideoVector(
        api_key="release-smoke-key",
        base_url="https://release-smoke.invalid/api/v2",
    )
    try:
        if not inspect.iscoroutinefunction(async_client.videos.batch_segments_for_targets):
            raise RuntimeError("async batch_segments_for_targets is not awaitable")
        if not inspect.iscoroutinefunction(async_client.videos.get_signed_url):
            raise RuntimeError("async get_signed_url is not awaitable")
    finally:
        asyncio.run(async_client.close())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-version", required=True)
    arguments = parser.parse_args()
    verify(arguments.expected_version)
    print(f"verified installed videovector {arguments.expected_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
