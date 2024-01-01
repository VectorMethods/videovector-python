"""Create a reusable scene taxonomy prompt with a structured JSON schema."""

from __future__ import annotations

from _common import api_client, idempotency_key

SCENE_TAXONOMY_SCHEMA = {
    "type": "object",
    "properties": {
        "scene_type": {
            "type": "string",
            "enum": ["interview", "b_roll", "screen_recording", "product_demo", "field_report"],
        },
        "location_type": {"type": "string"},
        "visible_people_count": {"type": "integer", "minimum": 0},
        "primary_actions": {"type": "array", "items": {"type": "string"}},
        "notable_objects": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["scene_type", "primary_actions", "confidence"],
}


def main() -> None:
    with api_client() as client:
        prompt = client.prompts.create(
            name="Scene Taxonomy Classifier",
            description="Classifies video segments into reusable content operations categories.",
            prompt_text=(
                "Inspect this media segment as a production metadata analyst. "
                "Classify the scene, list observable actions and objects, and avoid guessing "
                "about anything that is not visible or audible."
            ),
            json_schema=SCENE_TAXONOMY_SCHEMA,
            semantic_indexing={
                "disabled_segment_fields": ["confidence"],
                "disabled_video_level_fields": [],
            },
            idempotency_key=idempotency_key("prompt-scene-taxonomy"),
        )
        print(prompt.prompt_id, prompt.name)


if __name__ == "__main__":
    main()

