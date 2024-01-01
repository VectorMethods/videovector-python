"""Turn long training videos into chapters, summaries, and quiz cues."""

from __future__ import annotations

from _common import api_client, idempotency_key, require_env


def main() -> None:
    index_id = require_env("VIDEO_VECTOR_INDEX_ID")

    with api_client() as client:
        prompt = client.prompts.create(
            name="Training Chapter Builder",
            prompt_text=(
                "Extract training structure from this segment. Capture learning objectives, "
                "procedural steps, definitions, warnings, quiz-worthy facts, and timestamps "
                "that would help build a course outline."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "chapter_title": {"type": "string"},
                    "learning_objectives": {"type": "array", "items": {"type": "string"}},
                    "procedural_steps": {"type": "array", "items": {"type": "string"}},
                    "quiz_questions": {"type": "array", "items": {"type": "string"}},
                    "warnings": {"type": "array", "items": {"type": "string"}},
                },
            },
            video_level={
                "instructions_text": "Assemble the segment evidence into a course outline.",
                "included_segment_fields": [
                    "chapter_title",
                    "learning_objectives",
                    "procedural_steps",
                    "quiz_questions",
                ],
                "json_schema": {
                    "type": "object",
                    "properties": {
                        "course_summary": {"type": "string"},
                        "chapters": {"type": "array", "items": {"type": "string"}},
                        "assessment_items": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            idempotency_key=idempotency_key("prompt-training-chapters"),
        )
        run = client.prompt_runs.execute(
            prompt_id=prompt.prompt_id,
            target={"type": "index", "index_id": index_id},
            audio_segmentation_type="content_aware",
            idempotency_key=idempotency_key("run-training-chapters"),
        )
        print(run.run_id)


if __name__ == "__main__":
    main()
