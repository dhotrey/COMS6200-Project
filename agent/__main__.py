import os

import uvicorn

from . import config

if __name__ == "__main__":
    config.ensure_mininet_privileges()
    user = os.environ.get("ONOS_USER", "")
    print(f"ONOS REST user={user} (password not printed); uid={os.geteuid()}", flush=True)
    uvicorn.run("agent.server:app", host="127.0.0.1", port=8000)
