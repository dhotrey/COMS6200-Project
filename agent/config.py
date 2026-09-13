"""Local settings. Provider keys stay in Cloudflare; secrets never reach the UI."""
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
    "CLOUDFLARE_BYOK_ALIAS", "LOGFIRE_TOKEN",
    "TOOL_DELAY_MIN_SECONDS", "TOOL_DELAY_MAX_SECONDS",
    "MAX_TOOL_CALLS", "MAX_TURN_SECONDS", "MAX_TURN_TOKENS",
    "PYTHONPATH",
)
EFFORTS = ["none", "low", "medium", "high", "xhigh", "max"]
MODELS = [
    {"id": "gpt-5.6-luna", "label": "GPT-5.6 Luna", "efforts": EFFORTS},
    {"id": "gpt-5.6-terra", "label": "GPT-5.6 Terra", "efforts": EFFORTS},
    {"id": "gpt-5.6-sol", "label": "GPT-5.6 Sol", "efforts": EFFORTS},
    {"id": "gpt-6-astra", "label": "GPT-6 Astra", "efforts": EFFORTS[1:]},
]
# USD per million input, cached input, output tokens; reviewed 2026-09-10.
PRICES = {"gpt-5.6-luna": (.2, .02, 1.2), "gpt-5.6-terra": (2, .2, 12),
          "gpt-5.6-sol": (4, .4, 20), "gpt-6-astra": (10, 1, 50)}


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
    """Re-exec with sudo so ping/iperf can enter Mininet host namespaces."""
    if os.geteuid() == 0:
        return
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("COMS6200_AGENT_NO_SUDO"):
        return
    pythonpath = os.environ.get("PYTHONPATH", "")
    root = str(REPO_ROOT)
    os.environ["PYTHONPATH"] = root if not pythonpath else f"{root}:{pythonpath}"
    print("Re-executing with sudo so ping/iperf can enter Mininet host namespaces.", flush=True)
    os.execvp("sudo", [
        "sudo", f"--preserve-env={','.join(_SUDO_ENV)}",
        sys.executable, "-m", "agent",
    ])


class GatewayClient:
    def __init__(self, http_client):
        self.http = http_client

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
