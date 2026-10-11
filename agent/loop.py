"""The complete model → tools → model loop, streamed as small UI events."""
import asyncio
import hashlib
import json
import os
import time

import logfire

from .config import MODELS, PRICES, ROOT
from .limits import runtime_limits
from .tools import TOOLS, execute_tool


async def run(client, history, model, effort, state, *, tool_executor=None, prompt=None, limits=None, on_usage=None):
    supports_reasoning = next((m for m in MODELS if m["id"] == model), {}).get("reasoning", True)
    started = time.perf_counter()
    prompt = prompt if prompt is not None else (ROOT / "prompt.md").read_text()
    tool_executor = tool_executor or execute_tool
    stats = state["stats"]
    stats.update(model=model, effort=effort, prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                 input_tokens=0, output_tokens=0, cached_tokens=0, reasoning_tokens=0,
                 total_tokens=0, model_calls=0, tool_calls=0, invalid_tool_calls=0,
                 cost_usd=0.0, first_token_seconds=None, requests=[], usage_complete=True)
    limits = limits if limits is not None else runtime_limits()
    max_calls = int(limits["max_tool_calls"])
    max_tokens = int(limits.get("max_turn_tokens", os.getenv("MAX_TURN_TOKENS", "0")))
    try:
        async with asyncio.timeout(float(limits["max_turn_seconds"])):
            while True:
                if stats["model_calls"] >= max_calls + 2:
                    raise RuntimeError("Model request limit reached.")
                if max_tokens > 0 and stats["total_tokens"] >= max_tokens:
                    raise RuntimeError("Turn token budget reached.")
                call_started = time.perf_counter()
                stats["model_calls"] += 1
                response = None
                with logfire.span("model request", model=model, effort=effort) as span:
                    output_limit = 8192
                    if max_tokens > 0:
                        output_limit = min(8192, max(1, max_tokens - stats["total_tokens"]))
                    payload = {
                        "model": model, "instructions": prompt,
                        "input": history, "tools": TOOLS, "parallel_tool_calls": False, "store": False,
                        "stream": True,
                        "tool_choice": "none" if stats["tool_calls"] >= max_calls else "auto",
                        "max_output_tokens": output_limit,
                    }
                    if supports_reasoning:
                        payload["reasoning"] = {"effort": effort}
                        payload["include"] = ["reasoning.encrypted_content"]
                    async for event in client.stream_events(payload):
                        if event.get("type") in ("response.output_text.delta", "response.refusal.delta"):
                            if stats["first_token_seconds"] is None:
                                stats["first_token_seconds"] = time.perf_counter() - started
                            delta = event.get("delta", "")
                            state["content"] += delta
                            yield {"type": "text", "text": delta}
                        elif event.get("type") == "response.completed":
                            response = event.get("response")
                    if not response:
                        raise RuntimeError("Gateway stream ended without a completed response.")
                    usage = response.get("usage")
                    record = {"response_id": response.get("id"), "model": response.get("model", model),
                              "duration_seconds": time.perf_counter() - call_started}
                    if usage:
                        if "input_tokens" not in usage or "output_tokens" not in usage:
                            stats["usage_complete"] = False
                        cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0) or 0
                        reasoning = (usage.get("output_tokens_details") or {}).get("reasoning_tokens", 0) or 0
                        record.update(input_tokens=usage.get("input_tokens", 0),
                                      output_tokens=usage.get("output_tokens", 0), cached_tokens=cached,
                                      reasoning_tokens=reasoning, total_tokens=usage.get("total_tokens", 0))
                        for key in ("input_tokens", "output_tokens", "cached_tokens", "reasoning_tokens", "total_tokens"):
                            stats[key] += record[key]
                        inp, cache, out = PRICES[model]
                        if model != "gpt-4.1-mini" and record["input_tokens"] > 272000:
                            inp, cache, out = inp * 2, cache * 2, out * 1.5
                        stats["cost_usd"] += ((record["input_tokens"]-cached)*inp + cached*cache + record["output_tokens"]*out)/1e6
                    else:
                        stats["usage_complete"] = False
                    stats["requests"].append(record)
                    span.set_attributes(record)
                if on_usage is not None:
                    await on_usage()
                if response.get("status") != "completed":
                    raise RuntimeError(f"Model response ended with status {response.get('status')}.")
                history.extend(response.get("output", []))
                calls = [item for item in response.get("output", []) if item.get("type") == "function_call"]
                if not calls:
                    return
                for call in calls:
                    if stats["tool_calls"] >= max_calls:
                        result = {"ok": False, "error": "Tool budget reached", "name": call["name"]}
                    else:
                        stats["tool_calls"] += 1
                        yield {"type": "tool_start", "name": call["name"], "call_id": call["call_id"], "arguments": call["arguments"]}
                        with logfire.span("tool {name}", name=call["name"]) as span:
                            result = await tool_executor(call["name"], call["arguments"])
                            span.set_attributes(result)
                        stats["invalid_tool_calls"] += int(result.get("invalid", False))
                        state["tools"].append({"call_id": call["call_id"], **result})
                        yield {"type": "tool_end", "call_id": call["call_id"], **result}
                    # Only observations go to the model, not artificial delay or harness metrics.
                    observation = {k: result.get(k) for k in ("ok", "data", "error")}
                    history.append({"type": "function_call_output", "call_id": call["call_id"],
                                    "output": json.dumps(observation)})
                yield {"type": "stats", "stats": {**stats, "duration_seconds": time.perf_counter()-started}}
    finally:
        stats["duration_seconds"] = time.perf_counter() - started
