"""Run a segment prompt and synthesize a media-level summary."""

from __future__ import annotations

from _common import api_client, idempotency_key, require_env


def main() -> None:
    index_id = require_env("VIDEO_VECTOR_INDEX_ID")

    with api_client() as client:
        prompt = client.prompts.create(
            name="Executive Briefing Extractor",
            description="Extracts segment evidence and rolls it into a board-ready summary.",
            prompt_text=(
                "For this segment, extract decision points, named teams, risks, dates, "
                "metrics, and follow-up actions. Use only evidence in the media."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "decision_points": {"type": "array", "items": {"type": "string"}},
                    "risks": {"type": "array", "items": {"type": "string"}},
                    "follow_ups": {"type": "array", "items": {"type": "string"}},
                },
            },
            video_level={
                "instructions_text": (
                    "Create a concise executive brief from the extracted segment evidence. "
                    "Include decisions, risks, owners, and unresolved questions."
                ),
                "included_segment_fields": ["decision_points", "risks", "follow_ups"],
                "json_schema": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string"},
                        "top_risks": {"type": "array", "items": {"type": "string"}},
                        "next_actions": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            idempotency_key=idempotency_key("prompt-executive-briefing"),
        )
        run = client.prompt_runs.execute(
            prompt_id=prompt.prompt_id,
            target={"type": "index", "index_id": index_id},
            processing_model="gemini-2.5-flash",
            idempotency_key=idempotency_key("run-executive-briefing"),
        )
        completed = client.prompt_runs.wait_for_completion(run.run_id, timeout=1800)
        print(completed.run_id, completed.status)


if __name__ == "__main__":
    main()
