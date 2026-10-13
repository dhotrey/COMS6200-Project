from .limits import runtime_limits
"""Local settings. OpenAI uses Cloudflare BYOK; TypeSafe's key stays server-side."""
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
load_dotenv(REPO_ROOT / ".env")
# Reference lab ONOS REST. Override with env or root .env; never sent to the model.
if not os.environ.get("ONOS_USER", "").strip():
    os.environ["ONOS_USER"] = "onos"
if os.environ.get("ONOS_PASSWORD", "") == "":
    os.environ["ONOS_PASSWORD"] = "rocks"
_SUDO_ENV = (
    "ONOS_USER", "ONOS_PASSWORD", "ONOS_URL", "ONOS_HOST", "ONOS_OF_PORT",
    "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_D1_DATABASE_ID",
    "CLOUDFLARE_AI_GATEWAY_ID", "CLOUDFLARE_AI_GATEWAY_API_TOKEN",
    "CLOUDFLARE_BYOK_ALIAS", "LOGFIRE_TOKEN", "TYPESAFE_API_KEY",
    "TOOL_DELAY_MIN_SECONDS", "TOOL_DELAY_MAX_SECONDS",
    "MAX_TOOL_CALLS", "MAX_TURN_SECONDS", "MAX_TURN_TOKENS",
    "PYTHONPATH",
    # Without it the root server falls back to main6s8h tools on any topology.
    "COMS6200_TOPOLOGY", "COMS6200_AGENT_DEV",
)
EFFORTS = ["none", "low", "medium", "high", "xhigh", "max"]
MODELS = [
    {"id": "gpt-6.1-sol", "label": "GPT-6.1 Sol", "efforts": EFFORTS[1:]},
    {"id": "gpt-6-luna", "label": "GPT-6 Luna", "efforts": EFFORTS},
    {"id": "gpt-6-astra", "label": "GPT-6 Astra", "efforts": EFFORTS[1:]},
    {"id": "gpt-4.1-mini", "label": "GPT-4.1 Mini", "efforts": ["none"], "reasoning": False},
    {"id": "gpt-4.1-nano", "label": "GPT-4.1 Nano", "efforts": ["none"], "reasoning": False},
    {"id": "gpt-5.6-luna", "label": "GPT-5.6 Luna", "efforts": EFFORTS, "deprecated": True},
    {"id": "gpt-5.6-terra", "label": "GPT-5.6 Terra", "efforts": EFFORTS, "deprecated": True},
    {"id": "gpt-5.6-sol", "label": "GPT-5.6 Sol", "efforts": EFFORTS, "deprecated": True},
]
# USD per million input, cached input, output tokens; reviewed 2026-09-10.
PRICES = {"gpt-5.6-luna": (.2, .02, 1.2), "gpt-5.6-terra": (2, .2, 12),
          "gpt-5.6-sol": (4, .4, 20), "gpt-6-astra": (10, 1, 50)}
# New model Standard prices reviewed 2026-10-11 against the OpenAI model pages.
PRICES.update({"gpt-6.1-sol": (2, .1, 10), "gpt-6-luna": (.1, .01, .5)})
PRICES["gpt-4.1-mini"] = (.4, .1, 1.6)
# Standard price checked 2026-10-13 via trackers citing the OpenAI pricing page
# (cached input at 25% of input, as for gpt-4.1-mini).
PRICES["gpt-4.1-nano"] = (.1, .025, .4)
# The GPT-4.1 family is priced flat; no long-context surcharge.
FLAT_PRICED = {"gpt-4.1-mini", "gpt-4.1-nano"}
# TypeSafe model pricing reviewed 2026-10-11; output is free, no cache discount.
PRICES["jev-1.13.0"] = (.042, .042, 0)


def model_option(model: str) -> dict:
    """The MODELS entry for a model id ({} if unknown)."""
    return next((option for option in MODELS if option["id"] == model), {})


def dev_mode():
    return os.getenv("COMS6200_AGENT_DEV", "") == "1"


def d1_settings() -> tuple[str, str, str]:
    return (
        os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip(),
        os.getenv("CLOUDFLARE_API_TOKEN", "").strip(),
        os.getenv("CLOUDFLARE_D1_DATABASE_ID", "").strip(),
    )


def configured():
    return all(os.getenv(k, "").strip() for k in (
        "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_AI_GATEWAY_ID", "CLOUDFLARE_AI_GATEWAY_API_TOKEN"))


def ensure_mininet_privileges() -> None:
    """Re-exec with sudo so tools can enter Mininet host namespaces."""
    if os.geteuid() == 0:
        return
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("COMS6200_AGENT_NO_SUDO"):
        return
    pythonpath = os.environ.get("PYTHONPATH", "")
    root = str(REPO_ROOT)
    os.environ["PYTHONPATH"] = root if not pythonpath else f"{root}:{pythonpath}"
    print("Re-executing with sudo so tools can enter Mininet host namespaces.", flush=True)
    os.execvp("sudo", [
        "sudo", f"--preserve-env={','.join(_SUDO_ENV)}",
        sys.executable, "-m", "agent",
    ])


class GatewayClient:
    def __init__(self, http_client):
        self.http = http_client

    async def create_response(self, payload):
        return await self._json_request("responses", payload)

    async def _json_request(self, endpoint, payload):
        response = await self.http.post(endpoint, json=payload)
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f"Gateway {endpoint} request failed with status {response.status_code}.")
        try:
            result = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Gateway returned malformed {endpoint} data.") from exc
        if not isinstance(result, dict) or result.get("error"):
            raise RuntimeError(f"Gateway returned invalid {endpoint} data.")
        return result

    async def stream_events(self, payload):
        async with self.http.stream("POST", "responses", json=payload) as response:
            if not 200 <= response.status_code < 300:
                raise RuntimeError(f"Gateway request failed with status {response.status_code}.")
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    event = json.loads(data)
                except ValueError as exc:
                    raise RuntimeError("Gateway returned malformed stream data.") from exc
                if not isinstance(event, dict):
                    raise RuntimeError("Gateway returned malformed stream data.")
                if event.get("type") == "error":
                    raise RuntimeError("Gateway returned an error event.")
                yield event

    async def close(self):
        await self.http.aclose()


def make_client(transport=None):
    account = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    gateway = os.environ["CLOUDFLARE_AI_GATEWAY_ID"]
    headers = {"cf-aig-authorization": "Bearer " + os.environ["CLOUDFLARE_AI_GATEWAY_API_TOKEN"],
               "cf-aig-skip-cache": "true"}
    if alias := os.getenv("CLOUDFLARE_BYOK_ALIAS"):
        headers["cf-aig-byok-alias"] = alias
    http_client = httpx.AsyncClient(
        base_url=f"https://gateway.ai.cloudflare.com/v1/{account}/{gateway}/openai/",
        headers=headers,
        timeout=120,
        transport=transport,
    )
    return GatewayClient(http_client)


class TypeSafeClient:
    """Direct Jev grading, isolated from the diagnosis gateway and its credentials."""
    def __init__(self, http_client):
        self.http = http_client

    async def create_judgment(self, payload):
        for attempt in range(3):
            response = await self.http.post("systemone", json=payload)
            if response.status_code not in {429, 529} or attempt == 2:
                break
            delay = 2 ** attempt
            try:
                delay = max(delay, float(response.headers.get("retry-after", delay)))
            except ValueError:
                pass
            await asyncio.sleep(min(delay, 120))
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f"TypeSafe judgment request failed with status {response.status_code}.")
        try:
            result = response.json()
        except ValueError as exc:
            raise RuntimeError("TypeSafe returned malformed judgment data.") from exc
        if not isinstance(result, dict) or result.get("error"):
            raise RuntimeError("TypeSafe returned invalid judgment data.")
        return result

    async def close(self):
        await self.http.aclose()


def make_judge_client(transport=None):
    key = os.getenv("TYPESAFE_API_KEY", "").strip()
    if not key:
        return None
    return TypeSafeClient(httpx.AsyncClient(
        base_url="https://api.typesafe.ai/v1/",
        headers={"Authorization": "Bearer " + key},
        timeout=120,
        transport=transport,
    ))
