"""Triage safety footage into evidence-backed incident metadata."""

from __future__ import annotations

from _common import api_client, idempotency_key, require_env


def main() -> None:
    index_id = require_env("VIDEO_VECTOR_INDEX_ID")

    with api_client() as client:
        prompt = client.prompts.create(
            name="Safety Incident Triage",
            description="Flags visible safety hazards without making unsupported claims.",
            prompt_text=(
                "Review this workplace segment for observable safety events. Identify hazards, "
                "PPE presence, vehicle or equipment movement, blocked exits, spill/slip risks, "
                "and recommended review priority. Do not infer injury or liability."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "hazards": {"type": "array", "items": {"type": "string"}},
                    "ppe_observed": {"type": "array", "items": {"type": "string"}},
                    "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                    "review_reason": {"type": "string"},
                    "requires_human_review": {"type": "boolean"},
                },
                "required": ["priority", "requires_human_review"],
            },
            idempotency_key=idempotency_key("prompt-safety-triage"),
        )
        estimate = client.prompt_runs.estimate(
            prompt_id=prompt.prompt_id,
            target={"type": "index", "index_id": index_id},
            video_segmentation_type="smart",
        )
        print("estimated metered units", estimate.estimated_mt)


if __name__ == "__main__":
    main()
