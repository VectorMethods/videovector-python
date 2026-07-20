"""Fetch segments from one prompt run and mint bounded playback grants."""

from __future__ import annotations

from _common import api_client, require_env

from videovector import BatchVideoSegmentsTarget


def main() -> None:
    video_ids = [
        value.strip() for value in require_env("VIDEO_VECTOR_VIDEO_IDS").split(",") if value.strip()
    ]
    run_id = require_env("VIDEO_VECTOR_PROMPT_RUN_ID")

    with api_client() as client:
        responses = client.videos.batch_segments_for_targets(
            [BatchVideoSegmentsTarget(video_id=video_id, run_id=run_id) for video_id in video_ids]
        )
        for response in responses:
            print(response.video_id, response.run_id, len(response.segments))
            for segment in response.segments:
                if segment.gcs_uri:
                    grant = client.videos.get_signed_url(segment.gcs_uri)
                    print(segment.segment_id, grant.expires_at)


if __name__ == "__main__":
    main()
