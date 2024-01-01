"""Create a webhook for terminal workflow events."""

from __future__ import annotations

from _common import api_client, idempotency_key, require_env


def main() -> None:
    with api_client() as client:
        webhook = client.webhooks.create(
            name="Media workflow terminal events",
            url=require_env("VIDEO_VECTOR_WEBHOOK_URL"),
            events=[
                "prompt_run.completed",
                "prompt_run.failed",
                "import_job.completed",
                "export.ready",
            ],
            idempotency_key=idempotency_key("webhook-workflow-events"),
        )
        print(webhook.webhook_id)
        print("Persist the returned webhook secret in your secret store.")

        test = client.webhooks.test(webhook.webhook_id)
        print("test delivery accepted", test.success)


if __name__ == "__main__":
    main()
