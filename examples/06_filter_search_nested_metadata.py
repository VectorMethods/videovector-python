"""Search nested metadata fields produced by custom prompts."""

from __future__ import annotations

from _common import api_client, require_env


def main() -> None:
    index_id = require_env("VIDEO_VECTOR_INDEX_ID")
    run_id = require_env("VIDEO_VECTOR_RUN_ID")

    with api_client() as client:
        results = client.search.filter(
            index_id=index_id,
            run_ids=[run_id],
            conditions=[
                {
                    "field": "products[].brand_position",
                    "operator": "equals",
                    "value": "endcap",
                    "type": "string",
                },
                {
                    "field": "compliance.score",
                    "operator": "greater_equal",
                    "value": 0.8,
                    "type": "number",
                },
            ],
            page_size=25,
        )
        for result in results.results:
            print(result.video_id, result.segment_id, result.extracted_metadata)


if __name__ == "__main__":
    main()
