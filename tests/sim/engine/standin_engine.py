"""
Stand-in for the display engine in the simulator (KP-020).

The container has no screen or GPU, so the real slideshow can't start. This runs with the
engine venv's own python (~/venv_picframe/bin/python), imports picframe and pi3d from it (so
a broken venv fails here as it would on a frame), and answers on :9000 like the engine's HTTP
API, reporting which picframe version it loaded.

SIM_FAIL_VERSION: when it equals the loaded picframe version, exit at once instead, to force
a failed health check and a rollback.
"""

import http.server
import importlib.metadata
import os
import sys

import pi3d  # noqa: F401  (import test, as on a frame)
import picframe  # noqa: F401

VERSION = importlib.metadata.version("picframe")

if os.environ.get("SIM_FAIL_VERSION") == VERSION:
    print(f"standin: simulating a crash of picframe {VERSION}", file=sys.stderr)
    sys.exit(1)


class Handler(http.server.BaseHTTPRequestHandler):
    """Answers every GET with the loaded engine version."""

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        body = f"standin picframe {VERSION} from {sys.prefix}\n".encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        """Quiet."""


print(f"standin: picframe {VERSION} from {sys.prefix} on :9000", flush=True)
http.server.HTTPServer(("127.0.0.1", 9000), Handler).serve_forever()
