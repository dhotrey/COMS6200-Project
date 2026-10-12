"""Offline TypeSafe HTTP contract and credential isolation; no paid API calls."""
import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from agent import config, judge
from agent.tests.test_judge import assessment, judgment


def test_jev_uses_direct_endpoint_and_only_typesafe_credentials(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-typesafe-key")
    monkeypatch.setenv("CLOUDFLARE_AI_GATEWAY_API_TOKEN", "unrelated-gateway-key")
    monkeypatch.setenv("CLOUDFLARE_BYOK_ALIAS", "unrelated-alias")
    seen = []
    def transport(request):
        seen.append(request)
        assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
        assert request.headers["authorization"] == "Bearer test-typesafe-key"
        assert not any(name.startswith("cf-aig-") for name in request.headers)
        payload = json.loads(request.content)
        assert payload["model"] == "jev-1.13.0"
        assert payload["state"]["agent_diagnosis"] == assessment()["answer"]
        assert payload["questions"]["diagnosis_correctness"]["criteria"] == assessment()["criteria"]
        assert "input" not in payload and "tools" not in payload
        return httpx.Response(200, json=judgment())
    async def collect():
        client = config.make_judge_client(transport=httpx.MockTransport(transport))
        try:
            result = assessment()
            persist = AsyncMock()
            await judge.evaluate(client, None, None, result, persist=persist)
            assert result["status"] == "completed" and result["verdict"] == "correct"
            assert result["confidence"] == .91
            assert result["cost_usd"] == pytest.approx(100 * .042 / 1e6)
            assert {p["value"]: p["probability"] for p in result["probabilities"]} == judgment()["answers"]["diagnosis_correctness"]["probabilities"]
            persist.assert_awaited_once_with(result)
        finally:
            await client.close()
        assert client.http.is_closed
    asyncio.run(collect())
    assert len(seen) == 1


@pytest.mark.parametrize("response", [
    httpx.Response(401, json={"detail": "private upstream details"}),
    httpx.Response(302),
    httpx.Response(200, text="private upstream details"),
    httpx.Response(200, json={"error": "private upstream details"}),
    httpx.Response(200, json=[]),
])
def test_typesafe_errors_never_expose_response_bodies(monkeypatch, response):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    async def collect():
        client = config.make_judge_client(transport=httpx.MockTransport(lambda _: response))
        try:
            with pytest.raises(RuntimeError) as error:
                await client.create_judgment({})
            assert "private upstream details" not in str(error.value)
            assert "test-key" not in str(error.value)
        finally:
            await client.close()
    asyncio.run(collect())


@pytest.mark.parametrize("status", [429, 529])
@pytest.mark.parametrize("recovers", [True, False])
def test_overload_retries_are_bounded_and_honor_retry_after(monkeypatch, status, recovers):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    sleep = AsyncMock()
    monkeypatch.setattr(config.asyncio, "sleep", sleep)
    seen = []
    def transport(request):
        seen.append(request)
        if recovers and len(seen) == 2:
            return httpx.Response(200, json=judgment())
        return httpx.Response(status, headers={"retry-after": "3"})
    async def collect():
        client = config.make_judge_client(transport=httpx.MockTransport(transport))
        try:
            if recovers:
                assert await client.create_judgment({}) == judgment()
            else:
                with pytest.raises(RuntimeError, match=f"status {status}"):
                    await client.create_judgment({})
        finally:
            await client.close()
    asyncio.run(collect())
    assert len(seen) == (2 if recovers else 3)
    assert sleep.await_count == len(seen) - 1
    assert all(call.args == (3.0,) for call in sleep.await_args_list)


def test_missing_key_fails_only_the_evaluation(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", " ")
    assert config.make_judge_client() is None
    async def collect():
        result = assessment()
        await judge.evaluate(None, None, None, result, persist=AsyncMock())
        assert result["status"] == "error" and "TYPESAFE_API_KEY" in result["error"]
        assert "verdict" not in result
    asyncio.run(collect())
