from __future__ import annotations

import asyncio
import io
import json
from typing import Any
from uuid import UUID

import httpx
import pytest

from videovector import AsyncVideoVector, VideoVector
from videovector._exceptions import AuthenticationError, AuthorizationError, VideoVectorError

BASE = "https://example.test/api/v2"
ACTIVITY = "/api/v2/auth/processing-activity"
ACK = {"accepted": True, "wake_status": "accepted", "reason": "recorded"}


def sync_client(handler: Any, **kwargs: Any) -> VideoVector:
    client = VideoVector(base_url=BASE, **kwargs)
    client._http._client.close()
    client._http._client = httpx.Client(
        base_url=BASE,
        headers=client._http._default_headers(),
        transport=httpx.MockTransport(handler),
    )
    return client


def async_client(handler: Any, **kwargs: Any) -> AsyncVideoVector:
    client = AsyncVideoVector(base_url=BASE, **kwargs)
    client._http._client = httpx.AsyncClient(
        base_url=BASE,
        headers=client._http._default_headers(),
        transport=httpx.MockTransport(handler),
    )
    return client


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("auth", [{"api_key": "test-key"}, {"bearer_token": "test-jwt"}])
def test_explicit_authentication_is_one_control_request(async_mode: bool, auth: dict) -> None:
    observed = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(
            (
                request.url.path,
                dict(request.headers),
                json.loads(request.content),
                request.extensions,
            )
        )
        return httpx.Response(200, json=ACK)

    async def run() -> None:
        client = async_client(handler, **auth)
        assert observed == []
        try:
            assert await client.authenticate() == ACK
        finally:
            await client.close()

    if async_mode:
        asyncio.run(run())
    else:
        with sync_client(handler, **auth) as client:
            assert observed == []
            assert client.authenticate() == ACK
    assert len(observed) == 1
    path, headers, body, extensions = observed[0]
    assert path == ACTIVITY
    assert body == {"event_id": body["event_id"], "surface": "sdk", "reason": "authentication"}
    assert UUID(body["event_id"]).version == 4
    assert extensions["timeout"] == {"connect": 3.0, "read": 3.0, "write": 3.0, "pool": 3.0}
    assert "idempotency-key" not in headers
    if "api_key" in auth:
        assert headers["x-api-key"] == "test-key"
        assert "authorization" not in headers
    else:
        assert headers["authorization"] == "Bearer test-jwt"
        assert "x-api-key" not in headers


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize(
    "status,error",
    [(401, AuthenticationError), (403, AuthorizationError), (429, None), (503, None)],
)
def test_auth_rejection_propagates_but_readiness_failure_is_advisory(
    async_mode, status, error
) -> None:
    observed = []

    def handler(request):
        observed.append(request.url.path)
        return httpx.Response(status, json={"error": {"message": "unavailable"}})

    async def run():
        client = async_client(handler, api_key="test-key", max_retries=3)
        try:
            if error:
                with pytest.raises(error):
                    await client.authenticate()
            else:
                assert await client.authenticate() is None
        finally:
            await client.close()

    if async_mode:
        asyncio.run(run())
    else:
        with sync_client(handler, api_key="test-key", max_retries=3) as client:
            if error:
                with pytest.raises(error):
                    client.authenticate()
            else:
                assert client.authenticate() is None
    assert observed == [ACTIVITY]


@pytest.mark.parametrize("async_mode", [False, True])
def test_polling_and_token_refresh_never_signal_activity(async_mode) -> None:
    observed = []
    provider_calls = []

    def provider():
        provider_calls.append(True)
        return f"access-token-{len(provider_calls)}"

    def handler(request):
        observed.append(request.url.path)
        return httpx.Response(200, json={})

    async def run():
        client = async_client(handler, oauth_token_provider=provider)
        try:
            for _ in range(2):
                await client._http.get("/prompt-runs/run-1")
        finally:
            await client.close()

    if async_mode:
        asyncio.run(run())
    else:
        with sync_client(handler, oauth_token_provider=provider) as client:
            for _ in range(2):
                client._http.get("/prompt-runs/run-1")
    assert len(provider_calls) == 2
    assert observed == ["/api/v2/prompt-runs/run-1"] * 2


CASES = [
    ("videos.upload", "upload_media", "/videos/upload", {"file": None, "title": "video"}),
    ("workflow.upload", "upload_media", "/workflow/upload", {"file": None}),
    ("videos.process", "process_media", "/videos/v1/process", {"video_id": "v1"}),
    ("workflow.process", "process_media", "/workflow/process", {"prompt_id": "p1"}),
    (
        "prompt_runs.execute",
        "process_media",
        "/prompt-runs/execute",
        {"prompt_id": "p1", "target": {"type": "playground"}},
    ),
    (
        "prompt_runs.retry_segment",
        "retry_prompt_run_segment",
        "/prompt-runs/r1/videos/v1/segments/s1/retry",
        {"run_id": "r1", "video_id": "v1", "segment_id": "s1"},
    ),
]


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("resource,operation,path,kwargs", CASES)
def test_resource_intent_precedes_only_the_matching_business_request(
    async_mode, resource, operation, path, kwargs
) -> None:
    observed = []

    def handler(request):
        observed.append(
            (
                request.url.path,
                json.loads(request.content) if request.url.path == ACTIVITY else None,
            )
        )
        if request.url.path == ACTIVITY:
            return httpx.Response(503, json={"error": {"message": "advisory failure"}})
        # A concrete business rejection must remain visible and is not retried.
        return httpx.Response(400, json={"error": {"message": "business rejection"}})

    values = dict(kwargs)
    if "file" in values:
        values["file"] = io.BytesIO(b"media-bytes")
    resource_name, method_name = resource.split(".")

    async def run():
        client = async_client(handler, api_key="test-key", max_retries=3)
        try:
            with pytest.raises(VideoVectorError, match="business rejection"):
                await getattr(getattr(client, resource_name), method_name)(**values)
        finally:
            await client.close()

    if async_mode:
        asyncio.run(run())
    else:
        with sync_client(handler, api_key="test-key", max_retries=3) as client:
            with pytest.raises(VideoVectorError, match="business rejection"):
                getattr(getattr(client, resource_name), method_name)(**values)
    assert [item[0] for item in observed] == [ACTIVITY, "/api/v2" + path]
    assert observed[0][1]["reason"] == "processing_intent"
    assert observed[0][1]["operation"] == operation


@pytest.mark.parametrize("async_mode", [False, True])
def test_transport_retry_reuses_business_identity_without_repeating_activity(
    async_mode, monkeypatch
) -> None:
    observed = []
    business_attempts = []

    def handler(request):
        observed.append(request.url.path)
        if request.url.path == ACTIVITY:
            return httpx.Response(401, json={"error": {"message": "advisory auth rejection"}})
        business_attempts.append(request.headers.get("idempotency-key"))
        return httpx.Response(503 if len(business_attempts) == 1 else 200, json={})

    async def no_sleep(_seconds):
        pass

    monkeypatch.setattr("videovector._http.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("videovector._http.asyncio.sleep", no_sleep)

    async def run():
        client = async_client(handler, api_key="test-key", max_retries=1)
        try:
            await client._http.post(
                "/workflow/process",
                json={},
                idempotency_key="same-run",
                processing_intent="process_media",
            )
        finally:
            await client.close()

    if async_mode:
        asyncio.run(run())
    else:
        with sync_client(handler, api_key="test-key", max_retries=1) as client:
            client._http.post(
                "/workflow/process",
                json={},
                idempotency_key="same-run",
                processing_intent="process_media",
            )
    assert observed == [ACTIVITY, "/api/v2/workflow/process", "/api/v2/workflow/process"]
    assert business_attempts == ["same-run", "same-run"]
