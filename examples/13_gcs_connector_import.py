"""Create a GCS connector from a service-account file path and import media."""

from __future__ import annotations

from _common import api_client, idempotency_key, optional_env, require_env


def main() -> None:
    with api_client() as client:
        connector = client.connectors.create_gcs(
            name=optional_env("VIDEO_VECTOR_CONNECTOR_NAME", "GCS review ingest"),
            bucket=require_env("VIDEO_VECTOR_GCS_BUCKET"),
            gcp_project_id=require_env("VIDEO_VECTOR_GCP_PROJECT_ID"),
            credentials_file=require_env("VIDEO_VECTOR_GCS_CREDENTIALS_FILE"),
            scopes=["import"],
            import_mode="new_only",
        )
        print(connector.connector_id, connector.status)

        job = client.import_jobs.create(
            connector_id=connector.connector_id,
            index_id=require_env("VIDEO_VECTOR_INDEX_ID"),
            source_prefix=optional_env("VIDEO_VECTOR_IMPORT_PREFIX", "media/"),
            file_pattern=optional_env("VIDEO_VECTOR_FILE_PATTERN", "*.{mp4,mov}"),
            idempotency_key=idempotency_key("import-gcs"),
        )
        print(job.job_id, job.progress.total_files)


if __name__ == "__main__":
    main()

