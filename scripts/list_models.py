#!/usr/bin/env python3
"""List the model IDs the project's Cloudflare AI Gateway key can reach.

Read-only: one GET to the provider's models endpoint through the same gateway
the agent uses. Reads CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_AI_GATEWAY_ID,
CLOUDFLARE_AI_GATEWAY_API_TOKEN and optional CLOUDFLARE_BYOK_ALIAS from the
environment or the repository .env. Prints model IDs only, never credentials.

  python3 scripts/list_models.py          # text/chat models
  python3 scripts/list_models.py --all    # every model the endpoint returns

To use a listed model in the agent or the sweep, add it to MODELS and PRICES
in agent/config.py (prices from the provider's pricing page).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEYS = (
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_AI_GATEWAY_ID",
    "CLOUDFLARE_AI_GATEWAY_API_TOKEN",
    "CLOUDFLARE_BYOK_ALIAS",
)
_CHAT = re.compile(r"^(gpt-|o\d)")
_NOT_CHAT = re.compile(r"audio|realtime|transcribe|tts|image|search|embedding|moderation|dall-e|whisper")


def read_env_file(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE reader (comments, `export` and quotes allowed)."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def settings(env_file: Path = ROOT / ".env") -> dict[str, str]:
    from_file = read_env_file(env_file)
    return {key: os.environ.get(key, "").strip() or from_file.get(key, "").strip() for key in KEYS}


def configured_ids(config_path: Path = ROOT / "agent" / "config.py") -> set[str]:
    text = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    return set(re.findall(r'"id":\s*"([^"]+)"', text))


def chat_models(ids: list[str]) -> list[str]:
    return [model for model in ids if _CHAT.match(model) and not _NOT_CHAT.search(model)]


def fetch_ids(values: dict[str, str]) -> list[str]:
    url = (
        f"https://gateway.ai.cloudflare.com/v1/{values['CLOUDFLARE_ACCOUNT_ID']}/"
        f"{values['CLOUDFLARE_AI_GATEWAY_ID']}/openai/models"
    )
    headers = {
        "cf-aig-authorization": "Bearer " + values["CLOUDFLARE_AI_GATEWAY_API_TOKEN"],
        "cf-aig-skip-cache": "true",
        "Accept": "application/json",
        # Cloudflare rejects urllib's default "Python-urllib/x.y" signature (error 1010).
        "User-Agent": "coms6200-list-models/1.0",
    }
    if values.get("CLOUDFLARE_BYOK_ALIAS"):
        headers["cf-aig-byok-alias"] = values["CLOUDFLARE_BYOK_ALIAS"]
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    return sorted(str(item.get("id")) for item in payload.get("data") or [] if item.get("id"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true", help="include non-chat models")
    args = parser.parse_args(argv)
    values = settings()
    missing = [key for key in KEYS[:3] if not values[key]]
    if missing:
        print(f"ERROR: missing {', '.join(missing)} (environment or .env); values are never printed.")
        return 1
    try:
        ids = fetch_ids(values)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        print(f"ERROR: gateway returned HTTP {exc.code}: {body}")
        return 1
    except urllib.error.URLError as exc:
        print(f"ERROR: could not reach the gateway: {exc.reason}")
        return 1
    shown = ids if args.all else chat_models(ids)
    known = configured_ids()
    print(f"{len(shown)} model(s){'' if args.all else ' (chat/text; --all for every model)'}:")
    for model in shown:
        print(f"  {model}{'   [already in agent/config.py]' if model in known else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
