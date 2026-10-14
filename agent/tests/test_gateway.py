"""Real request serialization and SSE parsing against an offline Cloudflare transport."""
import asyncio
import contextlib
import json

import httpx
import pytest

from agent import config, loop


def test_cloudflare_byok_stream_has_no_openai_authorization(monkeypatch):
    class Span:
        def set_attributes(self, _attributes):
            pass

    monkeypatch.setattr(loop.logfire, "span", lambda *_args, **_kwargs: contextlib.nullcontext(Span()))
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "test-account")
    monkeypatch.setenv("CLOUDFLARE_AI_GATEWAY_ID", "test-gateway")
    monkeypatch.setenv("CLOUDFLARE_AI_GATEWAY_API_TOKEN", "test-gateway-token")
    monkeypatch.setenv("CLOUDFLARE_BYOK_ALIAS", "test-provider-alias")
    message = {"id": "msg-test", "type": "message", "role": "assistant", "status": "completed",
               "content": [{"type": "output_text", "text": "All clear.", "annotations": []}]}
    response = {"id": "resp-test", "object": "response", "created_at": 1, "status": "completed",
                "model": "gpt-5.6-luna", "output": [message], "parallel_tool_calls": False,
                "tools": [], "tool_choice": "auto", "usage": {
                    "input_tokens": 10, "output_tokens": 4, "total_tokens": 14,
                    "input_tokens_details": {"cached_tokens": 2},
                    "output_tokens_details": {"reasoning_tokens": 1}}}
    events = [
        {"type": "response.created", "response": {**response, "status": "in_progress", "output": [], "usage": None}},
        {"type": "response.output_item.added", "output_index": 0,
         "item": {**message, "status": "in_progress", "content": []}},
        {"type": "response.content_part.added", "item_id": "msg-test", "output_index": 0,
         "content_index": 0, "part": {"type": "output_text", "text": "", "annotations": []}},
        {"type": "response.output_text.delta", "item_id": "msg-test", "output_index": 0,
         "content_index": 0, "delta": "All clear.", "logprobs": []},
        {"type": "response.completed", "response": response},
    ]
    sse = "".join("event: " + e["type"] + "\ndata: " + json.dumps({**e, "sequence_number": i}) + "\n\n"
                  for i, e in enumerate(events))
    requests = []

    def transport(request):
        requests.append(request)
        assert str(request.url) == "https://gateway.ai.cloudflare.com/v1/test-account/test-gateway/openai/responses"
        assert "authorization" not in request.headers
        assert request.headers["cf-aig-authorization"] == "Bearer test-gateway-token"
        assert request.headers["cf-aig-skip-cache"] == "true"
        assert request.headers["cf-aig-byok-alias"] == "test-provider-alias"
        payload = json.loads(request.content)
        assert payload["stream"] is True and payload["store"] is False
        assert payload["reasoning"] == {"effort": "medium"}
        assert payload["include"] == ["reasoning.encrypted_content"]
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse)

    async def collect():
        client = config.make_client(transport=httpx.MockTransport(transport))
        state = {"content": "", "tools": [], "stats": {}}
        history = [{"role": "user", "content": "Check the network"}]
        try:
            result = [event async for event in loop.run(client, history, "gpt-5.6-luna", "medium", state)]
        finally:
            await client.close()
        assert result == [{"type": "text", "text": "All clear."}]
        assert state["content"] == "All clear."
        assert state["stats"]["total_tokens"] == 14
        assert state["stats"]["usage_complete"] is True
        assert history[-1]["content"][0]["text"] == "All clear."

    async def timed_collect():
        await asyncio.wait_for(collect(), timeout=5)

    asyncio.run(timed_collect())
    assert len(requests) == 1


@pytest.mark.parametrize(("response", "error"), [
    (httpx.Response(302), "status 302"),
    (httpx.Response(200, headers={"content-type": "text/event-stream"}, content=b"data: null\n\n"),
     "malformed stream data"),
])
def test_gateway_rejects_non_success_and_invalid_events(monkeypatch, response, error):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "test-account")
    monkeypatch.setenv("CLOUDFLARE_AI_GATEWAY_ID", "test-gateway")
    monkeypatch.setenv("CLOUDFLARE_AI_GATEWAY_API_TOKEN", "test-gateway-token")

    async def collect():
        client = config.make_client(transport=httpx.MockTransport(lambda _request: response))
        try:
            with pytest.raises(RuntimeError, match=error):
                _ = [event async for event in client.stream_events({"model": "test", "stream": True})]
        finally:
            await client.close()

    asyncio.run(collect())


def test_decisions_and_explanations_use_existing_byok_route(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "test-account")
    monkeypatch.setenv("CLOUDFLARE_AI_GATEWAY_ID", "test-gateway")
    monkeypatch.setenv("CLOUDFLARE_AI_GATEWAY_API_TOKEN", "test-token")
    monkeypatch.setenv("CLOUDFLARE_BYOK_ALIAS", "test-alias")
    seen = []
    def transport(request):
        seen.append(request)
        assert "authorization" not in request.headers
        assert request.headers["cf-aig-authorization"] == "Bearer test-token"
        assert request.headers["cf-aig-byok-alias"] == "test-alias"
        assert request.headers["cf-aig-skip-cache"] == "true"
        return httpx.Response(200, json={"model": "test", "answers": []})
    async def collect():
        provider = config.make_client(transport=httpx.MockTransport(transport))
        try:
            await provider.create_decision({"model": "gpt-6-luna", "questions": []})
            await provider.create_response({"model": "gpt-6.1-sol", "reasoning": {"effort": "high"}})
        finally:
            await provider.close()
    asyncio.run(collect())
    assert [str(r.url).split("/")[-1] for r in seen] == ["decisions", "responses"]
    assert json.loads(seen[1].content)["reasoning"] == {"effort": "high"}


@pytest.mark.parametrize("response", [httpx.Response(404), httpx.Response(200, text="bad-json"),
                                     httpx.Response(200, json={"error": {"message": "private upstream details"}})])
def test_decisions_gateway_failures_do_not_expose_upstream_data(monkeypatch, response):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "test-account")
    monkeypatch.setenv("CLOUDFLARE_AI_GATEWAY_ID", "test-gateway")
    monkeypatch.setenv("CLOUDFLARE_AI_GATEWAY_API_TOKEN", "test-token")
    async def collect():
        provider = config.make_client(transport=httpx.MockTransport(lambda _: response))
        try:
            with pytest.raises(RuntimeError) as error:
                await provider.create_decision({})
            assert "private upstream details" not in str(error.value)
        finally:
            await provider.close()
    asyncio.run(collect())
