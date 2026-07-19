"""Test-only HTTP status bridge for a running Qt window."""
from __future__ import annotations

import json
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any


def start_http_bridge(window_ref: list[Any], port: int):
    class BridgeHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def do_GET(self):
            window = window_ref[0] if window_ref else None
            if self.path == "/status":
                response = {
                    "status": window._status_label.text() if window else "Unknown",
                    "last_error": "",
                    "active_objective_id": (
                        window._pending_specs[0].get("objective_id", "")
                        if window and window._pending_specs else ""
                    ),
                }
            elif self.path == "/run_info":
                response = {
                    "pending_request": window._pending_request if window else "",
                    "n_pending_specs": len(window._pending_specs) if window else 0,
                }
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode("utf-8"))

    class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
        allow_reuse_address = True

    server = ThreadedHTTPServer(("localhost", port), BridgeHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
