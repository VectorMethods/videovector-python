"""Combine text and image search for brand and asset review workflows."""

from __future__ import annotations

from _common import api_client, load_base64_file, optional_env, require_env


def main() -> None:
    index_id = require_env("VIDEO_VECTOR_INDEX_ID")
    image_data = load_base64_file("VIDEO_VECTOR_IMAGE_FILE")

    with api_client() as client:
        results = client.search.multimodal(
            index_id=index_id,
            text_query=optional_env("VIDEO_VECTOR_QUERY", "logo on packaging near checkout"),
            image_data=image_data,
            text_weight=0.65,
            image_weight=0.35,
            top_k=12,
        )
        for result in results:
            print(result.video_id, result.start_time, result.match_type, result.fused_score)


if __name__ == "__main__":
    main()
