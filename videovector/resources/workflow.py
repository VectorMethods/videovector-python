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
from urllib.parse import quote
from uuid import uuid4

from .._exceptions import ProcessingError, TimeoutError, VideoVectorError
from .._types import (
    AnalysisResponse,
    ImportJob,
    PromptRun,
    SearchResult,
    WorkflowDefineResponse,
    WorkflowProcessResponse,
    WorkflowSearchResponse,
)
from ._uploads import async_upload_files, local_files, upload_files

if TYPE_CHECKING:
    from .._http import AsyncHttpClient, SyncHttpClient


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
) -> None:
    if bool((prompt_id or "").strip()) == bool((prompt_instruction or "").strip()):
        raise ValueError("Exactly one of prompt_id or prompt_instruction is required")


def _process_body(
    *,
    prompt_id: Optional[str],
    prompt_instruction: Optional[str],
    import_job_id: Optional[str],
    video_ids: Optional[Union[str, List[str]]],
    index_id: Optional[str],
    index_name: Optional[str],
    processing_model: Optional[str],
    enable_image_embedding: Optional[bool],
) -> Dict[str, Any]:
    _validate_process_options(
        prompt_id=prompt_id,
        prompt_instruction=prompt_instruction,
    )
    if import_job_id is not None and any(
        value is not None for value in (video_ids, index_id, index_name)
    ):
        raise ValueError("import_job_id cannot be combined with another processing target")
    body: Dict[str, Any] = {}
    for key, value in {
        "processing_model": processing_model,
        "enable_image_embedding": enable_image_embedding,
        "import_job_id": import_job_id,
        "prompt_id": prompt_id,
        "prompt_instruction": prompt_instruction,
        "video_ids": video_ids,
        "index_id": index_id,
        "index_name": index_name,
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


def _source_body(
    *,
    urls: Optional[Union[str, List[str]]] = None,
    files: Optional[List[Dict[str, Any]]] = None,
    upload: bool = False,
    video_ids: Optional[List[str]] = None,
    import_job_id: Optional[str] = None,
    index_id: Optional[str] = None,
    index_name: Optional[str] = None,
) -> Dict[str, Any]:
    if (
        sum(
            (
                urls is not None,
                files is not None,
                upload,
                video_ids is not None,
                import_job_id is not None,
            )
        )
        > 1
    ):
        raise ValueError("Provide one source: urls, files, upload, or video_ids")
    if import_job_id and (index_id or index_name):
        raise ValueError("import_job_id cannot be combined with an index")
    if index_id and index_name:
        raise ValueError("index_id and index_name are mutually exclusive")
    if urls is not None:
        values = [urls] if isinstance(urls, str) else urls
        if (
            not isinstance(values, list)
            or not 1 <= len(values) <= 8
            or any(not isinstance(value, str) or not value.strip() for value in values)
        ):
            raise ValueError("urls must be a URL or a list of 1 to 8 URLs")
    return {
        key: value
        for key, value in {
            "urls": urls,
            "files": files,
            "video_ids": video_ids,
            "import_job_id": import_job_id,
            "index_id": index_id,
            "index_name": index_name,
            "upload": True if upload else None,
        }.items()
        if value is not None
    }


def _analysis_body(
    *,
    instruction: Optional[str],
    prompt_id: Optional[str],
    wait_seconds: int,
    detail: Literal["summary", "full"],
    **sources: Any,
) -> Dict[str, Any]:
    if bool((instruction or "").strip()) == bool((prompt_id or "").strip()):
        raise ValueError("Provide exactly one of instruction or prompt_id")
    if (
        isinstance(wait_seconds, bool)
        or not isinstance(wait_seconds, int)
        or not 0 <= wait_seconds <= 30
    ):
        raise ValueError("wait_seconds must be between 0 and 30")
    if detail not in {"summary", "full"}:
        raise ValueError("detail must be summary or full")
    body = _source_body(**sources)
    body.update(wait_seconds=wait_seconds, detail=detail)
    if instruction is not None:
        body["instruction"] = instruction
    else:
        body["prompt_id"] = prompt_id
    return body


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

    def upload_files(
        self,
        paths: List[Union[str, Path]],
        *,
        title: Optional[str] = None,
        index_id: Optional[str] = None,
        index_name: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> ImportJob:
        """Upload up to eight local files directly to storage with bounded concurrency."""
        key = _idempotency_key("upload-files", idempotency_key)
        files = local_files(paths, key)
        body = _source_body(index_id=index_id, index_name=index_name)
        if title is not None:
            body["title"] = title
        job = self._client.post("/workflow/attachments", json=body, idempotency_key=key)
        try:
            result = upload_files(self._client, job, files)
        except VideoVectorError as error:
            error.details = {
                **(error.details or {}),
                "job_id": job["job_id"],
                "idempotency_key": key,
            }
            raise
        return ImportJob.model_validate(result)

    def import_urls(
        self,
        urls: Union[str, List[str]],
        *,
        title: Optional[str] = None,
        index_id: Optional[str] = None,
        index_name: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> ImportJob:
        """Import public media/YouTube URLs in one server-owned job; no local download."""
        body = _source_body(urls=urls, index_id=index_id, index_name=index_name)
        if title is not None:
            body["title"] = title
        response = self._client.post(
            "/workflow/attachments",
            json=body,
            idempotency_key=_idempotency_key("import", idempotency_key),
        )
        return ImportJob.model_validate(response)

    def analyze(
        self,
        *,
        instruction: Optional[str] = None,
        prompt_id: Optional[str] = None,
        urls: Optional[Union[str, List[str]]] = None,
        files: Optional[List[Dict[str, Any]]] = None,
        upload: bool = False,
        video_ids: Optional[List[str]] = None,
        import_job_id: Optional[str] = None,
        index_id: Optional[str] = None,
        index_name: Optional[str] = None,
        wait_seconds: int = 0,
        detail: Literal["summary", "full"] = "summary",
        idempotency_key: Optional[str] = None,
    ) -> AnalysisResponse:
        """Submit once; an index with URLs/files selects their destination."""
        response = self._client.post(
            "/workflow/analyses",
            json=_analysis_body(
                instruction=instruction,
                prompt_id=prompt_id,
                urls=urls,
                files=files,
                upload=upload,
                video_ids=video_ids,
                import_job_id=import_job_id,
                index_id=index_id,
                index_name=index_name,
                wait_seconds=wait_seconds,
                detail=detail,
            ),
            idempotency_key=_idempotency_key("analyze", idempotency_key),
        )
        return AnalysisResponse.model_validate(response)

    def get_analysis(
        self,
        analysis_id: str,
        *,
        wait_seconds: int = 0,
        detail: Literal["summary", "full"] = "summary",
    ) -> AnalysisResponse:
        """Read the existing analysis without submitting or downloading media again."""
        response = self._client.get(
            f"/workflow/analyses/{quote(analysis_id, safe='')}",
            params={"wait_seconds": wait_seconds, "detail": detail},
        )
        return AnalysisResponse.model_validate(response)

    def upload(
        self,
        file: MediaInput,
        *,
        title: Optional[str] = None,
        index_id: Optional[str] = None,
        index_name: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> ImportJob:
        key = _idempotency_key("upload", idempotency_key)
        if isinstance(file, (str, Path)):
            return self.upload_files(
                [file],
                title=title,
                index_id=index_id,
                index_name=index_name,
                idempotency_key=key,
            )
        data = {
            key: value
            for key, value in {
                "title": title,
                "index_id": index_id,
                "index_name": index_name,
            }.items()
            if value is not None
        }
        filename = Path(str(getattr(file, "name", "upload"))).name
        response = self._client.post(
            "/workflow/upload",
            processing_intent="upload_media",
            data=data,
            files={"file": (filename, file)},
            idempotency_key=key,
        )
        return ImportJob.model_validate(response)

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
        import_job_id: Optional[str] = None,
        video_ids: Optional[Union[str, List[str]]] = None,
        index_id: Optional[str] = None,
        index_name: Optional[str] = None,
        processing_model: Optional[str] = None,
        enable_image_embedding: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> WorkflowProcessResponse:
        response = self._client.post(
            "/workflow/process",
            processing_intent="process_media",
            json=_process_body(
                prompt_id=prompt_id,
                prompt_instruction=prompt_instruction,
                import_job_id=import_job_id,
                video_ids=video_ids,
                index_id=index_id,
                index_name=index_name,
                processing_model=processing_model,
                enable_image_embedding=enable_image_embedding,
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

    async def upload_files(
        self,
        paths: List[Union[str, Path]],
        *,
        title: Optional[str] = None,
        index_id: Optional[str] = None,
        index_name: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> ImportJob:
        """Upload up to eight local files directly to storage with bounded concurrency."""
        key = _idempotency_key("upload-files", idempotency_key)
        files = local_files(paths, key)
        body = _source_body(index_id=index_id, index_name=index_name)
        if title is not None:
            body["title"] = title
        job = await self._client.post("/workflow/attachments", json=body, idempotency_key=key)
        try:
            result = await async_upload_files(self._client, job, files)
        except VideoVectorError as error:
            error.details = {
                **(error.details or {}),
                "job_id": job["job_id"],
                "idempotency_key": key,
            }
            raise
        return ImportJob.model_validate(result)

    async def import_urls(
        self,
        urls: Union[str, List[str]],
        *,
        title: Optional[str] = None,
        index_id: Optional[str] = None,
        index_name: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> ImportJob:
        """Import public media/YouTube URLs in one server-owned job; no local download."""
        body = _source_body(urls=urls, index_id=index_id, index_name=index_name)
        if title is not None:
            body["title"] = title
        response = await self._client.post(
            "/workflow/attachments",
            json=body,
            idempotency_key=_idempotency_key("import", idempotency_key),
        )
        return ImportJob.model_validate(response)

    async def analyze(
        self,
        *,
        instruction: Optional[str] = None,
        prompt_id: Optional[str] = None,
        urls: Optional[Union[str, List[str]]] = None,
        files: Optional[List[Dict[str, Any]]] = None,
        upload: bool = False,
        video_ids: Optional[List[str]] = None,
        import_job_id: Optional[str] = None,
        index_id: Optional[str] = None,
        index_name: Optional[str] = None,
        wait_seconds: int = 0,
        detail: Literal["summary", "full"] = "summary",
        idempotency_key: Optional[str] = None,
    ) -> AnalysisResponse:
        """Submit once; an index with URLs/files selects their destination."""
        response = await self._client.post(
            "/workflow/analyses",
            json=_analysis_body(
                instruction=instruction,
                prompt_id=prompt_id,
                urls=urls,
                files=files,
                upload=upload,
                video_ids=video_ids,
                import_job_id=import_job_id,
                index_id=index_id,
                index_name=index_name,
                wait_seconds=wait_seconds,
                detail=detail,
            ),
            idempotency_key=_idempotency_key("analyze", idempotency_key),
        )
        return AnalysisResponse.model_validate(response)

    async def get_analysis(
        self,
        analysis_id: str,
        *,
        wait_seconds: int = 0,
        detail: Literal["summary", "full"] = "summary",
    ) -> AnalysisResponse:
        """Read the existing analysis without submitting or downloading media again."""
        response = await self._client.get(
            f"/workflow/analyses/{quote(analysis_id, safe='')}",
            params={"wait_seconds": wait_seconds, "detail": detail},
        )
        return AnalysisResponse.model_validate(response)

    async def upload(
        self,
        file: MediaInput,
        *,
        title: Optional[str] = None,
        index_id: Optional[str] = None,
        index_name: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> ImportJob:
        key = _idempotency_key("upload", idempotency_key)
        if isinstance(file, (str, Path)):
            return await self.upload_files(
                [file],
                title=title,
                index_id=index_id,
                index_name=index_name,
                idempotency_key=key,
            )
        data = {
            key: value
            for key, value in {
                "title": title,
                "index_id": index_id,
                "index_name": index_name,
            }.items()
            if value is not None
        }
        filename = Path(str(getattr(file, "name", "upload"))).name
        response = await self._client.post(
            "/workflow/upload",
            processing_intent="upload_media",
            data=data,
            files={"file": (filename, file)},
            idempotency_key=key,
        )
        return ImportJob.model_validate(response)

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
        import_job_id: Optional[str] = None,
        video_ids: Optional[Union[str, List[str]]] = None,
        index_id: Optional[str] = None,
        index_name: Optional[str] = None,
        processing_model: Optional[str] = None,
        enable_image_embedding: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> WorkflowProcessResponse:
        response = await self._client.post(
            "/workflow/process",
            processing_intent="process_media",
            json=_process_body(
                prompt_id=prompt_id,
                prompt_instruction=prompt_instruction,
                import_job_id=import_job_id,
                video_ids=video_ids,
                index_id=index_id,
                index_name=index_name,
                processing_model=processing_model,
                enable_image_embedding=enable_image_embedding,
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
