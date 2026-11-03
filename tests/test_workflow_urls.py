from unittest.mock import AsyncMock, Mock

import pytest

from videovector.resources.workflow import AsyncWorkflowResource, WorkflowResource

JOB = {"job_id": "job_1", "status": "pending", "progress": {"total_files": 2}}
ANALYSIS = {
    "analysis_id": "analysis_1",
    "status": "pending",
    "terminal": False,
    "stage": "importing",
    "message": "Accepted",
    "scope": {"type": "playground"},
    "progress": {},
    "results": {},
    "next_action": {"type": "continue_polling"},
}


@pytest.mark.parametrize(
    "urls",
    ["https://media.example/a.mp4", ["https://youtu.be/video", "https://media.example/b.mp4"]],
)
def test_urls_submit_once_without_downloading_or_polling(urls):
    http = Mock(post=Mock(return_value=JOB))
    result = WorkflowResource(http).import_urls(urls, index_name="Library", idempotency_key="same")
    assert result.job_id == "job_1"
    http.post.assert_called_once_with(
        "/workflow/attachments",
        json={"urls": urls, "index_name": "Library"},
        idempotency_key="same",
    )
    http.get.assert_not_called()


@pytest.mark.asyncio
async def test_async_analysis_uses_same_id_and_explicit_reads():
    http = Mock(post=AsyncMock(return_value=ANALYSIS), get=AsyncMock(return_value=ANALYSIS))
    resource = AsyncWorkflowResource(http)
    result = await resource.analyze(
        instruction="Describe", urls="https://youtu.be/video", idempotency_key="same"
    )
    assert result.analysis_id == "analysis_1"
    assert http.post.call_args.kwargs["json"]["urls"] == "https://youtu.be/video"
    http.get.assert_not_called()
    assert (await resource.get_analysis(result.analysis_id)).analysis_id == result.analysis_id
    http.get.assert_awaited_once_with(
        "/workflow/analyses/analysis_1", params={"wait_seconds": 0, "detail": "summary"}
    )


@pytest.mark.parametrize(
    "source", [{"files": []}, {"video_ids": ["v"]}, {"upload": True}, {"import_job_id": "i"}]
)
def test_analysis_rejects_ambiguous_source_before_admission(source):
    http = Mock()
    with pytest.raises(ValueError, match="one source"):
        WorkflowResource(http).analyze(
            instruction="Describe", urls="https://media.example/a.mp4", **source
        )
    http.post.assert_not_called()


@pytest.mark.parametrize("urls", [[], "", [""], ["https://media.example/a.mp4"] * 9])
def test_url_batch_preserves_existing_eight_file_limit(urls):
    with pytest.raises(ValueError, match="urls"):
        WorkflowResource(Mock()).import_urls(urls)
