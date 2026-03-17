from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_server_deploy.py"


@contextmanager
def _serve(routes: dict[str, tuple[int, bytes, str]], *, reset_health_requests: int = 0):
    class _Handler(BaseHTTPRequestHandler):
        remaining_health_resets = reset_health_requests

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health" and type(self).remaining_health_resets > 0:
                type(self).remaining_health_resets -= 1
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self.connection.close()
                return
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
        "/v1/status": (
            200,
            json.dumps({"status_version": 1, "server_version": "1.6.0", "status": "ok"}).encode("utf-8"),
            "application/json",
        ),
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
    assert "PASS /v1/status" in completed.stdout
    assert "PASS /v1/index" in completed.stdout
    assert "PASS /v1/files/file_demo" in completed.stdout


def test_verify_server_deploy_retries_transient_health_connection_reset() -> None:
    routes = {
        "/health": (200, json.dumps({"status": "ok"}).encode("utf-8"), "application/json"),
        "/v1/status": (
            200,
            json.dumps({"status_version": 1, "server_version": "1.6.0", "status": "ok"}).encode("utf-8"),
            "application/json",
        ),
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

    with _serve(routes, reset_health_requests=1) as base_url:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--base-url", base_url, "--wait-seconds", "2"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )

    assert completed.returncode == 0
    assert "PASS /health" in completed.stdout


def test_verify_server_deploy_fails_when_index_payload_is_invalid() -> None:
    routes = {
        "/health": (200, json.dumps({"status": "ok"}).encode("utf-8"), "application/json"),
        "/v1/status": (
            200,
            json.dumps({"status_version": 1, "server_version": "1.6.0", "status": "ok"}).encode("utf-8"),
            "application/json",
        ),
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


def test_verify_server_deploy_fails_when_status_payload_is_invalid() -> None:
    routes = {
        "/health": (200, json.dumps({"status": "ok"}).encode("utf-8"), "application/json"),
        "/v1/status": (200, json.dumps({"status_version": 2, "status": "ok"}).encode("utf-8"), "application/json"),
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
    assert "/v1/status returned unexpected status_version=2" in completed.stderr
