import os

import uvicorn

from . import config

if __name__ == "__main__":
    config.ensure_mininet_privileges()
    user = os.environ.get("ONOS_USER", "")
    print(f"ONOS REST user={user} (password not printed); uid={os.geteuid()}", flush=True)
    uvicorn.run("agent.server:app", host="127.0.0.1", port=8000,
                reload=config.dev_mode(), reload_delay=2.0,
                reload_dirs=[str(config.REPO_ROOT / name) for name in
                             ("agent", "telemetry", "faults", "forwarding", "topologies")]
                if config.dev_mode() else None)
