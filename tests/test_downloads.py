from __future__ import annotations

from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import threading
from uuid import uuid4

import pytest

from gamehub_cli.downloads import download_with_atomic_write




@contextmanager
def _http_file_server(path: str, payload: bytes):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path != path:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            for index in range(0, len(payload), 13):
                self.wfile.write(payload[index : index + 13])

        def log_message(self, *_args) -> None:  # noqa: D401
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_download_with_atomic_write_success() -> None:
    payload = b"download-payload" * 4096
    expected_sha = hashlib.sha256(payload).hexdigest()
    with _workspace_tempdir("gamehub-download-") as temp_root:
        destination = temp_root / "roms" / "NES" / "SuperMarioBros.nes"
        with _http_file_server("/v1/files/file_mario", payload) as server_url:
            download_with_atomic_write(
                server_url=server_url,
                url="/v1/files/file_mario",
                destination=destination,
                expected_sha256=expected_sha,
            )

        assert destination.read_bytes() == payload
        part_path = destination.with_suffix(f"{destination.suffix}.part")
        if part_path.exists():
            assert part_path.stat().st_size == 0


def test_download_with_atomic_write_checksum_mismatch_cleans_partial() -> None:
    payload = b"bad-payload" * 1024
    with _workspace_tempdir("gamehub-download-") as temp_root:
        destination = temp_root / "firmware" / "PSX" / "scph5501.bin"
        with _http_file_server("/v1/firmware/PSX/scph5501.bin", payload) as server_url:
            with pytest.raises(ValueError, match="Checksum mismatch"):
                download_with_atomic_write(
                    server_url=server_url,
                    url="/v1/firmware/PSX/scph5501.bin",
                    destination=destination,
                    expected_sha256="0" * 64,
                )

        assert not destination.exists()
        part_path = destination.with_suffix(f"{destination.suffix}.part")
        if part_path.exists():
            assert part_path.stat().st_size == 0
