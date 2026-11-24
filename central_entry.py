#!/usr/bin/env python3
"""Run LiuliDNS as a central control plane (accounts, review, DNS/ingress).

Put this behind a Cloudflare Tunnel (for example api.asnia.cc and
admin.asnia.cc). The desktop client connects to /api/v1; each desktop runs its
own local Go tunnel agent because cloudflared must run on the user's network.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    port = int(os.environ.get("LIULI_CENTRAL_PORT", "8000"))
    host = os.environ.get("LIULI_CENTRAL_HOST", "127.0.0.1")
    data = os.environ.get("LIULI_CENTRAL_DATA", "")
    if data:
        Path(data).expanduser().mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import uvicorn
    from backend.app.main import app  # noqa: E402

    print(f"LiuliDNS control plane on http://{host}:{port}", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="info", access_log=False)


if __name__ == "__main__":
    main()
