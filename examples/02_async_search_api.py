"""Use the async client from an application service boundary."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from _common import optional_env, require_env

from videovector import AsyncVideoVector


@dataclass
class SearchRequest:
    index_id: str
    query: str
    top_k: int = 8


async def search_media(request: SearchRequest) -> list[dict[str, object]]:
    async with AsyncVideoVector(api_key=require_env("VIDEO_VECTOR_API_KEY")) as client:
        results = await client.search.text(
            index_id=request.index_id,
            query=request.query,
            top_k=request.top_k,
        )
        return [
            {
                "video_id": result.video_id,
                "segment_id": result.segment_id,
                "score": result.similarity_score,
                "preview": result.content_preview,
            }
            for result in results
        ]


async def main() -> None:
    request = SearchRequest(
        index_id=require_env("VIDEO_VECTOR_INDEX_ID"),
        query=optional_env("VIDEO_VECTOR_QUERY", "forklift crossing loading bay"),
    )
    for row in await search_media(request):
        print(row)


if __name__ == "__main__":
    asyncio.run(main())

