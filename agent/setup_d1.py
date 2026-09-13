"""Create and verify the agent's schema in its configured Cloudflare D1 database."""

from __future__ import annotations

import json

from . import store


def main() -> None:
    try:
        summary = store.initialize()
    except store.D1StoreError as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        store.close()
    print(json.dumps({"ok": True, **summary}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
