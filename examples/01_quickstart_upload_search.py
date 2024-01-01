"""Upload a media file to an index and run semantic text search."""

from __future__ import annotations

from _common import api_client, idempotency_key, optional_env, require_env


def main() -> None:
    media_file = require_env("VIDEO_VECTOR_MEDIA_FILE")
    index_name = optional_env("VIDEO_VECTOR_INDEX_NAME", "SDK quickstart review")

    with api_client() as client:
        index = client.indexes.create(
            name=index_name,
            idempotency_key=idempotency_key("index-quickstart"),
        )
        upload = client.videos.upload(
            file=media_file,
            title=optional_env("VIDEO_VECTOR_MEDIA_TITLE", "Store walk-through"),
            index_id=index.index_id,
        )
        print(f"uploaded {upload.video_id} into {index.index_id}")

        results = client.search.text(
            index_id=index.index_id,
            query="employee restocking shelves near checkout",
            top_k=10,
        )
        for result in results:
            print(result.video_id, result.start_time, result.content_preview)


if __name__ == "__main__":
    main()
