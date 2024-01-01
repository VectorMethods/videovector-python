"""Low-friction upload, prompt, processing, and search workflow."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    BinaryIO,
    Dict,
    Iterator,
    List,
    Literal,
    Optional,
    Union,
)
from uuid import uuid4

from .._exceptions import ProcessingError, TimeoutError
from .._types import (
    PromptRun,
    SearchResult,
    WorkflowDefineResponse,
    WorkflowProcessResponse,
    WorkflowSearchResponse,
    WorkflowUploadResponse,
)

if TYPE_CHECKING:
    from .._http import AsyncHttpClient, SyncHttpClient


SegmentationMode = Literal["smart", "content_aware", "fixed"]
ResultLevel = Literal["segment", "video"]
MediaInput = Union[str, Path, BinaryIO]

_SEARCHABLE_RUN_STATUSES = {"completed", "completed_with_failures"}
_TERMINAL_UNSEARCHABLE_RUN_STATUSES = {"failed", "cancelled"}


def _idempotency_key(operation: str, supplied: Optional[str]) -> str:
    candidate = (supplied or "").strip()
    return candidate or f"workflow-{operation}:{uuid4().hex}"


def _validate_process_options(
    *,
    prompt_id: Optional[str],
    prompt_instruction: Optional[str],
    segmentation_mode: SegmentationMode,
    fixed_segment_duration_seconds: Optional[int],
) -> None:
    if bool((prompt_id or "").strip()) == bool((prompt_instruction or "").strip()):
        raise ValueError("Exactly one of prompt_id or prompt_instruction is required")
    if segmentation_mode not in {"smart", "content_aware", "fixed"}:
        raise ValueError("segmentation_mode must be smart, content_aware, or fixed")
    if fixed_segment_duration_seconds is not None and (
        isinstance(fixed_segment_duration_seconds, bool)
        or not isinstance(fixed_segment_duration_seconds, int)
        or not 1 <= fixed_segment_duration_seconds <= 300
    ):
        raise ValueError("fixed_segment_duration_seconds must be between 1 and 300")
    if segmentation_mode != "fixed" and fixed_segment_duration_seconds is not None:
        raise ValueError(
            "fixed_segment_duration_seconds is accepted only when segmentation_mode='fixed'"
        )


def _process_body(
    *,
    prompt_id: Optional[str],
    prompt_instruction: Optional[str],
    video_ids: Optional[Union[str, List[str]]],
    index_id: Optional[str],
    index_name: Optional[str],
    segmentation_mode: SegmentationMode,
    fixed_segment_duration_seconds: Optional[int],
    advanced_transcription: bool,
    create_image_embeddings: bool,
) -> Dict[str, Any]:
    _validate_process_options(
        prompt_id=prompt_id,
        prompt_instruction=prompt_instruction,
        segmentation_mode=segmentation_mode,
        fixed_segment_duration_seconds=fixed_segment_duration_seconds,
    )
    body: Dict[str, Any] = {
        "segmentation_mode": segmentation_mode,
        "advanced_transcription": advanced_transcription,
        "create_image_embeddings": create_image_embeddings,
    }
    for key, value in {
        "prompt_id": prompt_id,
        "prompt_instruction": prompt_instruction,
        "video_ids": video_ids,
        "index_id": index_id,
        "index_name": index_name,
        "fixed_segment_duration_seconds": fixed_segment_duration_seconds,
    }.items():
        if value is not None:
            body[key] = value
    return body


def _search_body(
    *,
    query: Optional[str],
    filters: Optional[List[Dict[str, Any]]],
    result_level: ResultLevel,
    video_ids: Optional[Union[str, List[str]]],
    prompt_run_ids: Optional[Union[str, List[str]]],
    index_id: Optional[str],
    index_name: Optional[str],
    limit: int,
) -> Dict[str, Any]:
    if bool((query or "").strip()) == bool(filters):
        raise ValueError("Exactly one of query or filters is required")
    if result_level not in {"segment", "video"}:
        raise ValueError("result_level must be segment or video")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    body: Dict[str, Any] = {"result_level": result_level, "limit": limit}
    for key, value in {
        "query": query,
        "filters": filters,
        "video_ids": video_ids,
        "prompt_run_ids": prompt_run_ids,
        "index_id": index_id,
        "index_name": index_name,
    }.items():
        if value is not None:
            body[key] = value
    return body


def _cursor_request(
    *,
    cursor: Optional[str],
    query: Optional[str],
    filters: Optional[List[Dict[str, Any]]],
    result_level: ResultLevel,
    video_ids: Optional[Union[str, List[str]]],
    prompt_run_ids: Optional[Union[str, List[str]]],
    index_id: Optional[str],
    index_name: Optional[str],
    limit: int,
    idempotency_key: Optional[str],
) -> Optional[str]:
    if cursor is None:
        return None
    normalized = cursor.strip()
    if not normalized:
        raise ValueError("cursor must not be blank")
    if any(
        (
            query is not None,
            filters is not None,
            video_ids is not None,
            prompt_run_ids is not None,
            index_id is not None,
            index_name is not None,
            result_level != "segment",
            limit != 10,
            idempotency_key is not None,
        )
    ):
        raise ValueError("cursor continuation cannot be combined with search arguments")
    return normalized


class WorkflowSearchPage:
    """One stable workflow-search page with cursor continuation."""

    def __init__(self, response: WorkflowSearchResponse, client: "SyncHttpClient") -> None:
        self.response = response
        self._client = client

    @property
    def data(self) -> List[SearchResult]:
        return self.response.data

    @property
    def has_more(self) -> bool:
        return self.response.pagination.has_more

    @property
    def next_cursor(self) -> Optional[str]:
        return self.response.pagination.next_cursor

    def __iter__(self) -> Iterator[SearchResult]:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, index: int) -> SearchResult:
        return self.data[index]

    def next_page(self) -> Optional["WorkflowSearchPage"]:
        if not self.has_more or not self.next_cursor:
            return None
        response = self._client.get("/workflow/search/page", params={"cursor": self.next_cursor})
        return WorkflowSearchPage(WorkflowSearchResponse.model_validate(response), self._client)

    def auto_paging_iter(self) -> Iterator[SearchResult]:
        page: Optional[WorkflowSearchPage] = self
        while page is not None:
            yield from page.data
            page = page.next_page()


class AsyncWorkflowSearchPage:
    """Async counterpart of :class:`WorkflowSearchPage`."""

    def __init__(self, response: WorkflowSearchResponse, client: "AsyncHttpClient") -> None:
        self.response = response
        self._client = client

    @property
    def data(self) -> List[SearchResult]:
        return self.response.data

    @property
    def has_more(self) -> bool:
        return self.response.pagination.has_more

    @property
    def next_cursor(self) -> Optional[str]:
        return self.response.pagination.next_cursor

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, index: int) -> SearchResult:
        return self.data[index]

    async def next_page(self) -> Optional["AsyncWorkflowSearchPage"]:
        if not self.has_more or not self.next_cursor:
            return None
        response = await self._client.get(
            "/workflow/search/page", params={"cursor": self.next_cursor}
        )
        return AsyncWorkflowSearchPage(
            WorkflowSearchResponse.model_validate(response), self._client
        )

    async def auto_paging_iter(self) -> AsyncIterator[SearchResult]:
        page: Optional[AsyncWorkflowSearchPage] = self
        while page is not None:
            for item in page.data:
                yield item
            page = await page.next_page()


class WorkflowResource:
    """Synchronous simplified workflow operations."""

    def __init__(self, client: "SyncHttpClient") -> None:
        self._client = client

    def upload(
        self,
        file: MediaInput,
        *,
        title: Optional[str] = None,
        index_id: Optional[str] = None,
        index_name: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> WorkflowUploadResponse:
        data = {
            key: value
            for key, value in {
                "title": title,
                "index_id": index_id,
                "index_name": index_name,
            }.items()
            if value is not None
        }
        key = _idempotency_key("upload", idempotency_key)
        if isinstance(file, (str, Path)):
            path = Path(file)
            with path.open("rb") as stream:
                response = self._client.post(
                    "/workflow/upload",
                    data=data,
                    files={"file": (path.name, stream)},
                    idempotency_key=key,
                )
        else:
            filename = Path(str(getattr(file, "name", "upload"))).name
            response = self._client.post(
                "/workflow/upload",
                data=data,
                files={"file": (filename, file)},
                idempotency_key=key,
            )
        return WorkflowUploadResponse.model_validate(response)

    def define(
        self,
        instruction: str,
        *,
        save: bool = True,
        idempotency_key: Optional[str] = None,
    ) -> WorkflowDefineResponse:
        response = self._client.post(
            "/workflow/define",
            json={"instruction": instruction, "save": save},
            idempotency_key=_idempotency_key("define", idempotency_key),
        )
        return WorkflowDefineResponse.model_validate(response)

    def process(
        self,
        *,
        prompt_id: Optional[str] = None,
        prompt_instruction: Optional[str] = None,
        video_ids: Optional[Union[str, List[str]]] = None,
        index_id: Optional[str] = None,
        index_name: Optional[str] = None,
        segmentation_mode: SegmentationMode = "smart",
        fixed_segment_duration_seconds: Optional[int] = None,
        advanced_transcription: bool = False,
        create_image_embeddings: bool = False,
        idempotency_key: Optional[str] = None,
    ) -> WorkflowProcessResponse:
        response = self._client.post(
            "/workflow/process",
            json=_process_body(
                prompt_id=prompt_id,
                prompt_instruction=prompt_instruction,
                video_ids=video_ids,
                index_id=index_id,
                index_name=index_name,
                segmentation_mode=segmentation_mode,
                fixed_segment_duration_seconds=fixed_segment_duration_seconds,
                advanced_transcription=advanced_transcription,
                create_image_embeddings=create_image_embeddings,
            ),
            idempotency_key=_idempotency_key("process", idempotency_key),
        )
        return WorkflowProcessResponse.model_validate(response)

    def search(
        self,
        query: Optional[str] = None,
        *,
        filters: Optional[List[Dict[str, Any]]] = None,
        result_level: ResultLevel = "segment",
        video_ids: Optional[Union[str, List[str]]] = None,
        prompt_run_ids: Optional[Union[str, List[str]]] = None,
        index_id: Optional[str] = None,
        index_name: Optional[str] = None,
        limit: int = 10,
        cursor: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> WorkflowSearchPage:
        continuation = _cursor_request(
            cursor=cursor,
            query=query,
            filters=filters,
            result_level=result_level,
            video_ids=video_ids,
            prompt_run_ids=prompt_run_ids,
            index_id=index_id,
            index_name=index_name,
            limit=limit,
            idempotency_key=idempotency_key,
        )
        if continuation is not None:
            response = self._client.get("/workflow/search/page", params={"cursor": continuation})
        else:
            response = self._client.post(
                "/workflow/search",
                json=_search_body(
                    query=query,
                    filters=filters,
                    result_level=result_level,
                    video_ids=video_ids,
                    prompt_run_ids=prompt_run_ids,
                    index_id=index_id,
                    index_name=index_name,
                    limit=limit,
                ),
                idempotency_key=_idempotency_key("search", idempotency_key),
            )
        return WorkflowSearchPage(WorkflowSearchResponse.model_validate(response), self._client)

    def wait_until_searchable(
        self,
        run_id: str,
        *,
        poll_interval: float = 5.0,
        timeout: Optional[float] = None,
    ) -> PromptRun:
        started = time.monotonic()
        while True:
            run = PromptRun.model_validate(self._client.get(f"/prompt-runs/{run_id}"))
            status = (run.status or "").lower()
            if status in _SEARCHABLE_RUN_STATUSES:
                return run
            if status in _TERMINAL_UNSEARCHABLE_RUN_STATUSES:
                raise ProcessingError(
                    f"Prompt run ended with non-searchable status: {status}",
                    details={"run_id": run_id, "status": status},
                )
            if timeout is not None and time.monotonic() - started > timeout:
                raise TimeoutError(
                    f"Prompt run did not become searchable within {timeout} seconds",
                    details={"run_id": run_id, "status": status},
                )
            time.sleep(poll_interval)


class AsyncWorkflowResource:
    """Asynchronous simplified workflow operations."""

    def __init__(self, client: "AsyncHttpClient") -> None:
        self._client = client

    async def upload(
        self,
        file: MediaInput,
        *,
        title: Optional[str] = None,
        index_id: Optional[str] = None,
        index_name: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> WorkflowUploadResponse:
        data = {
            key: value
            for key, value in {
                "title": title,
                "index_id": index_id,
                "index_name": index_name,
            }.items()
            if value is not None
        }
        key = _idempotency_key("upload", idempotency_key)
        if isinstance(file, (str, Path)):
            path = Path(file)
            with path.open("rb") as stream:
                response = await self._client.post(
                    "/workflow/upload",
                    data=data,
                    files={"file": (path.name, stream)},
                    idempotency_key=key,
                )
        else:
            filename = Path(str(getattr(file, "name", "upload"))).name
            response = await self._client.post(
                "/workflow/upload",
                data=data,
                files={"file": (filename, file)},
                idempotency_key=key,
            )
        return WorkflowUploadResponse.model_validate(response)

    async def define(
        self,
        instruction: str,
        *,
        save: bool = True,
        idempotency_key: Optional[str] = None,
    ) -> WorkflowDefineResponse:
        response = await self._client.post(
            "/workflow/define",
            json={"instruction": instruction, "save": save},
            idempotency_key=_idempotency_key("define", idempotency_key),
        )
        return WorkflowDefineResponse.model_validate(response)

    async def process(
        self,
        *,
        prompt_id: Optional[str] = None,
        prompt_instruction: Optional[str] = None,
        video_ids: Optional[Union[str, List[str]]] = None,
        index_id: Optional[str] = None,
        index_name: Optional[str] = None,
        segmentation_mode: SegmentationMode = "smart",
        fixed_segment_duration_seconds: Optional[int] = None,
        advanced_transcription: bool = False,
        create_image_embeddings: bool = False,
        idempotency_key: Optional[str] = None,
    ) -> WorkflowProcessResponse:
        response = await self._client.post(
            "/workflow/process",
            json=_process_body(
                prompt_id=prompt_id,
                prompt_instruction=prompt_instruction,
                video_ids=video_ids,
                index_id=index_id,
                index_name=index_name,
                segmentation_mode=segmentation_mode,
                fixed_segment_duration_seconds=fixed_segment_duration_seconds,
                advanced_transcription=advanced_transcription,
                create_image_embeddings=create_image_embeddings,
            ),
            idempotency_key=_idempotency_key("process", idempotency_key),
        )
        return WorkflowProcessResponse.model_validate(response)

    async def search(
        self,
        query: Optional[str] = None,
        *,
        filters: Optional[List[Dict[str, Any]]] = None,
        result_level: ResultLevel = "segment",
        video_ids: Optional[Union[str, List[str]]] = None,
        prompt_run_ids: Optional[Union[str, List[str]]] = None,
        index_id: Optional[str] = None,
        index_name: Optional[str] = None,
        limit: int = 10,
        cursor: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> AsyncWorkflowSearchPage:
        continuation = _cursor_request(
            cursor=cursor,
            query=query,
            filters=filters,
            result_level=result_level,
            video_ids=video_ids,
            prompt_run_ids=prompt_run_ids,
            index_id=index_id,
            index_name=index_name,
            limit=limit,
            idempotency_key=idempotency_key,
        )
        if continuation is not None:
            response = await self._client.get(
                "/workflow/search/page", params={"cursor": continuation}
            )
        else:
            response = await self._client.post(
                "/workflow/search",
                json=_search_body(
                    query=query,
                    filters=filters,
                    result_level=result_level,
                    video_ids=video_ids,
                    prompt_run_ids=prompt_run_ids,
                    index_id=index_id,
                    index_name=index_name,
                    limit=limit,
                ),
                idempotency_key=_idempotency_key("search", idempotency_key),
            )
        return AsyncWorkflowSearchPage(
            WorkflowSearchResponse.model_validate(response), self._client
        )

    async def wait_until_searchable(
        self,
        run_id: str,
        *,
        poll_interval: float = 5.0,
        timeout: Optional[float] = None,
    ) -> PromptRun:
        started = time.monotonic()
        while True:
            run = PromptRun.model_validate(await self._client.get(f"/prompt-runs/{run_id}"))
            status = (run.status or "").lower()
            if status in _SEARCHABLE_RUN_STATUSES:
                return run
            if status in _TERMINAL_UNSEARCHABLE_RUN_STATUSES:
                raise ProcessingError(
                    f"Prompt run ended with non-searchable status: {status}",
                    details={"run_id": run_id, "status": status},
                )
            if timeout is not None and time.monotonic() - started > timeout:
                raise TimeoutError(
                    f"Prompt run did not become searchable within {timeout} seconds",
                    details={"run_id": run_id, "status": status},
                )
            await asyncio.sleep(poll_interval)
