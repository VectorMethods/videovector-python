"""Inspect failed prompt-run segments and retry one retryable segment."""

from __future__ import annotations

from _common import api_client, idempotency_key, require_env


def main() -> None:
    run_id = require_env("VIDEO_VECTOR_RUN_ID")

    with api_client() as client:
        manifest = client.prompt_runs.get_failed_segments(run_id)
        print("failed segments", manifest.failed_segments)

        for video in manifest.videos:
            for segment in video.segments:
                print(video.video_id, segment.segment_id, segment.failed_operations)
                if segment.retryable:
                    retry = client.prompt_runs.retry_segment(
                        run_id,
                        video.video_id,
                        segment.segment_id,
                        idempotency_key=idempotency_key("retry-segment"),
                    )
                    print("retry queued", retry.retry_id, retry.status)
                    return

        print("no retryable failed segments found")


if __name__ == "__main__":
    main()
