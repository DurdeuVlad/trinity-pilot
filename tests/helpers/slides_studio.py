"""Lifecycle and evidence helpers for the local browser-demo fixture."""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "tests" / "fixtures" / "slides_studio_server.js"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class SlidesStudio:
    process: subprocess.Popen[str]
    base_url: str

    def reset(self) -> None:
        request = urllib.request.Request(f"{self.base_url}/_test/reset", method="POST")
        with urllib.request.urlopen(request, timeout=5):
            pass

    def audit(self) -> dict:
        with urllib.request.urlopen(f"{self.base_url}/_test/audit", timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()


def start_slides_studio() -> SlidesStudio:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node.js is required for Slides Studio browser demos")
    port = _free_port()
    process = subprocess.Popen(
        [node, str(SERVER)],
        cwd=str(ROOT),
        env={**__import__("os").environ, "SLIDES_STUDIO_PORT": str(port)},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    fixture = SlidesStudio(process, f"http://127.0.0.1:{port}")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            raise RuntimeError(f"Slides Studio exited during startup: {output}")
        try:
            with urllib.request.urlopen(f"{fixture.base_url}/health", timeout=1):
                fixture.reset()
                return fixture
        except OSError:
            time.sleep(0.1)
    fixture.close()
    raise RuntimeError("Slides Studio did not become healthy within 10 seconds")
