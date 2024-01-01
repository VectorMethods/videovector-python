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
        client.import_jobs.wait_for_completion(upload.job_id)
        for part in client.import_jobs.iter_outputs(upload.job_id):
            print(f"imported {part.video_id} into {index.index_id}")
        run = client.workflow.process(
            import_job_id=upload.job_id,
            prompt_instruction="Describe visible activities and objects.",
        )
        client.workflow.wait_until_searchable(run.run.run_id)

        results = client.search.text(
            index_id=index.index_id,
            query="employee restocking shelves near checkout",
            top_k=10,
        )
        for result in results:
            print(result.video_id, result.start_time, result.content_preview)


if __name__ == "__main__":
    main()
