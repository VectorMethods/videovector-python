"""Estimate prompt-run cost before executing with an idempotency key."""

from __future__ import annotations

from _common import api_client, idempotency_key, require_env


def main() -> None:
    prompt_id = require_env("VIDEO_VECTOR_PROMPT_ID")
    index_id = require_env("VIDEO_VECTOR_INDEX_ID")

    with api_client() as client:
        estimate = client.prompt_runs.estimate(
            prompt_id=prompt_id,
            target={"type": "index", "index_id": index_id},
            video_segmentation_type="smart",
            processing_model="gemini-2.5-flash",
        )
        print("estimated metered units", estimate.estimated_mt)

        run = client.prompt_runs.execute(
            prompt_id=prompt_id,
            target={"type": "index", "index_id": index_id},
            video_segmentation_type="smart",
            processing_model="gemini-2.5-flash",
            idempotency_key=idempotency_key("run-estimated-workflow"),
        )
        print(run.run_id, run.billing_status)


if __name__ == "__main__":
    main()
