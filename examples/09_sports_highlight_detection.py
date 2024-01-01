"""Detect sports moments and create searchable highlight metadata."""

from __future__ import annotations

from _common import api_client, idempotency_key, require_env


def main() -> None:
    index_id = require_env("VIDEO_VECTOR_INDEX_ID")

    with api_client() as client:
        prompt = client.prompts.create(
            name="Sports Highlight Detector",
            prompt_text=(
                "Analyze this sports segment for highlight-worthy moments. Identify play type, "
                "athletes mentioned or visible, score context, crowd reaction, replay indicators, "
                "and whether this segment should be clipped for a recap."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "play_type": {"type": "string"},
                    "athletes": {"type": "array", "items": {"type": "string"}},
                    "teams": {"type": "array", "items": {"type": "string"}},
                    "highlight_score": {"type": "number", "minimum": 0, "maximum": 1},
                    "clip_reason": {"type": "string"},
                    "broadcast_elements": {"type": "array", "items": {"type": "string"}},
                },
            },
            idempotency_key=idempotency_key("prompt-sports-highlights"),
        )
        run = client.prompt_runs.execute(
            prompt_id=prompt.prompt_id,
            target={"type": "index", "index_id": index_id},
            enable_transcription=True,
            enable_image_embedding=True,
            idempotency_key=idempotency_key("run-sports-highlights"),
        )
        print(run.run_id, run.status)


if __name__ == "__main__":
    main()

