"""Create and download a direct export without exposing bearer credentials."""

from __future__ import annotations

from pathlib import Path

from _common import api_client, idempotency_key, optional_env, require_env


def main() -> None:
    destination = Path(optional_env("VIDEO_VECTOR_EXPORT_DESTINATION", "videovector-export.json"))
    with api_client() as client:
        created = client.exports.create_prompt_run_export(
            run_id=require_env("VIDEO_VECTOR_RUN_ID"),
            idempotency_key=idempotency_key("export-prompt-run"),
        )
        completed = client.exports.wait_for_completion(created.export_id)

        # This is the preferred path: the SDK keeps API authentication attached,
        # streams once, enforces a local byte ceiling, and writes atomically.
        written = client.exports.download(completed.export_id, destination)
        print(f"Downloaded {written} bytes to {destination}")

        # Mint only when another bounded client specifically needs a bearer URL.
        # Never print, log, or persist the returned credential.
        bounded_url = client.exports.download_url(completed.export_id)
        print("Bounded browser URL available:", bounded_url is not None)


if __name__ == "__main__":
    main()
