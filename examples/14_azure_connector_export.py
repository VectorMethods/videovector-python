"""Create an Azure connector and export prompt-run metadata to it."""

from __future__ import annotations

from _common import api_client, idempotency_key, optional_env, require_env


def main() -> None:
    with api_client() as client:
        connector = client.connectors.create_azure(
            name=optional_env("VIDEO_VECTOR_CONNECTOR_NAME", "Azure analytics exports"),
            storage_account=require_env("VIDEO_VECTOR_AZURE_STORAGE_ACCOUNT"),
            container=require_env("VIDEO_VECTOR_AZURE_CONTAINER"),
            tenant_id=require_env("VIDEO_VECTOR_AZURE_TENANT_ID"),
            client_id=require_env("VIDEO_VECTOR_AZURE_CLIENT_ID"),
            client_secret=require_env("VIDEO_VECTOR_AZURE_CLIENT_SECRET"),
            scopes=["export"],
            export_base_path=optional_env("VIDEO_VECTOR_EXPORT_BASE_PATH", "videovector/exports"),
            idempotency_key=idempotency_key("connector-azure"),
        )

        export = client.exports.create_prompt_run_export(
            run_id=require_env("VIDEO_VECTOR_RUN_ID"),
            destination_connector_id=connector.connector_id,
            destination_subpath=optional_env("VIDEO_VECTOR_EXPORT_SUBPATH", "prompt-runs"),
            idempotency_key=idempotency_key("export-prompt-run"),
        )
        print(export.export_id, export.status)


if __name__ == "__main__":
    main()
