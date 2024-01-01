"""Analyze retail shelf videos for product placement and compliance."""

from __future__ import annotations

from _common import api_client, idempotency_key, require_env


def main() -> None:
    index_id = require_env("VIDEO_VECTOR_INDEX_ID")

    with api_client() as client:
        prompt = client.prompts.create(
            name="Retail Shelf Compliance Review",
            prompt_text=(
                "Review this retail aisle segment. Identify products, shelf position, "
                "out-of-stock indicators, blocked labels, price tag visibility, promotional "
                "materials, and compliance issues. Report only visible evidence."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "products": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "brand_position": {"type": "string"},
                                "price_visible": {"type": "boolean"},
                                "stock_state": {"type": "string"},
                            },
                        },
                    },
                    "compliance": {
                        "type": "object",
                        "properties": {
                            "score": {"type": "number"},
                            "issues": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
            },
            idempotency_key=idempotency_key("prompt-retail-compliance"),
        )
        run = client.prompt_runs.execute(
            prompt_id=prompt.prompt_id,
            target={"type": "index", "index_id": index_id},
            video_segmentation_type="fixed",
            video_segment_duration=20,
            idempotency_key=idempotency_key("run-retail-compliance"),
        )
        print(run.run_id)


if __name__ == "__main__":
    main()

