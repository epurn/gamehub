from __future__ import annotations

import json
import subprocess
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_server_deploy.py"


@contextmanager
def _serve(routes: dict[str, tuple[int, bytes, str]]):
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            status, body, content_type = routes.get(self.path, (404, b"not found", "text/plain"))
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=2.0)
        server.server_close()


def test_verify_server_deploy_succeeds_for_health_index_and_file() -> None:
    routes = {
        "/health": (200, json.dumps({"status": "ok"}).encode("utf-8"), "application/json"),
        "/v1/index": (
            200,
            json.dumps(
                {
                    "index_version": 1,
                    "titles": [{"rom": {"file_id": "file_demo"}}],
                }
            ).encode("utf-8"),
            "application/json",
        ),
        "/v1/files/file_demo": (200, b"rom-bytes", "application/octet-stream"),
    }

    with _serve(routes) as base_url:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--base-url", base_url],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )

    assert completed.returncode == 0
    assert "PASS /health" in completed.stdout
    assert "PASS /v1/index" in completed.stdout
    assert "PASS /v1/files/file_demo" in completed.stdout


def test_verify_server_deploy_fails_when_index_payload_is_invalid() -> None:
    routes = {
        "/health": (200, json.dumps({"status": "ok"}).encode("utf-8"), "application/json"),
        "/v1/index": (200, json.dumps({"titles": []}).encode("utf-8"), "application/json"),
    }

    with _serve(routes) as base_url:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--base-url", base_url],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )

    assert completed.returncode == 1
    assert "/v1/index did not return an index_version" in completed.stderr
