"""Create an S3 connector, browse media, and start a bulk import job."""

from __future__ import annotations

from _common import api_client, idempotency_key, optional_env, require_env


def main() -> None:
    with api_client() as client:
        connector = client.connectors.create_s3(
            name=optional_env("VIDEO_VECTOR_CONNECTOR_NAME", "S3 media archive"),
            bucket=require_env("VIDEO_VECTOR_S3_BUCKET"),
            region=require_env("VIDEO_VECTOR_S3_REGION"),
            aws_access_key_id=require_env("VIDEO_VECTOR_AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=require_env("VIDEO_VECTOR_AWS_SECRET_ACCESS_KEY"),
            scopes=["import", "export"],
            import_mode="new_only",
            export_base_path=optional_env("VIDEO_VECTOR_EXPORT_BASE_PATH", "videovector/exports"),
            idempotency_key=idempotency_key("connector-s3"),
        )
        test = client.connectors.test(connector.connector_id)
        print("connector test", test.success)

        files = client.connectors.browse(
            connector.connector_id,
            prefix=optional_env("VIDEO_VECTOR_IMPORT_PREFIX", "incoming/"),
            pattern=optional_env("VIDEO_VECTOR_FILE_PATTERN", "*.mp4"),
        )
        print(f"matching files: {len(files)}")

        job = client.import_jobs.create(
            connector_id=connector.connector_id,
            index_id=require_env("VIDEO_VECTOR_INDEX_ID"),
            source_prefix=optional_env("VIDEO_VECTOR_IMPORT_PREFIX", "incoming/"),
            file_pattern=optional_env("VIDEO_VECTOR_FILE_PATTERN", "*.mp4"),
            recursive=True,
            idempotency_key=idempotency_key("import-s3"),
        )
        print(job.job_id, job.status)


if __name__ == "__main__":
    main()

