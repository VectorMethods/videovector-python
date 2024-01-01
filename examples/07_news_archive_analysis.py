"""Create and run a newsroom archive prompt for story retrieval."""

from __future__ import annotations

from _common import api_client, idempotency_key, require_env


def main() -> None:
    index_id = require_env("VIDEO_VECTOR_INDEX_ID")

    with api_client() as client:
        prompt = client.prompts.create(
            name="News Archive Story Metadata",
            description="Extracts newsroom-specific metadata for archive search and licensing.",
            prompt_text=(
                "You are cataloging broadcast news footage. Extract people, organizations, "
                "locations, lower-third text, event type, visual evidence, quotes, and rights "
                "sensitivity. Mark uncertainty explicitly."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "story_slug": {"type": "string"},
                    "people": {"type": "array", "items": {"type": "string"}},
                    "organizations": {"type": "array", "items": {"type": "string"}},
                    "locations": {"type": "array", "items": {"type": "string"}},
                    "event_type": {"type": "string"},
                    "rights_sensitive": {"type": "boolean"},
                    "search_keywords": {"type": "array", "items": {"type": "string"}},
                },
            },
            idempotency_key=idempotency_key("prompt-news-archive"),
        )
        run = client.prompt_runs.execute(
            prompt_id=prompt.prompt_id,
            target={"type": "index", "index_id": index_id},
            idempotency_key=idempotency_key("run-news-archive"),
        )
        print(run.run_id, run.status)


if __name__ == "__main__":
    main()

