from __future__ import annotations

from contextlib import contextmanager
import gc
import os
from pathlib import Path
import shutil
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from gamehub_server.main import IndexRepository, app
import gamehub_server.main as server_main

TMP_ROOT = Path(__file__).resolve().parents[1] / ".pytest_tmp_local"
TMP_ROOT.mkdir(parents=True, exist_ok=True)


def _write_file(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _remove_readonly_and_retry(func, path, _exc_info) -> None:
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    try:
        func(path)
    except OSError:
        pass


def _cleanup_tree(path: Path) -> None:
    for _ in range(10):
        try:
            shutil.rmtree(path, onexc=_remove_readonly_and_retry)
            return
        except FileNotFoundError:
            return
        except OSError:
            gc.collect()
            time.sleep(0.05)


@contextmanager
def _workspace_tempdir(prefix: str):
    path = TMP_ROOT / f"{prefix}{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        _cleanup_tree(path)


@pytest.fixture
def api_client():
    with _workspace_tempdir(prefix="gamehub-api-") as temp_dir:
        root = temp_dir
        _write_file(root / "roms" / "NES" / "SuperMarioBros.nes", b"rom-bytes")
        _write_file(root / "firmware" / "NES" / "dummy.bin", b"firmware-bytes")

        original_data_root = server_main.DATA_ROOT
        original_repo = server_main.INDEX_REPO
        server_main.DATA_ROOT = root.resolve()
        server_main.INDEX_REPO = IndexRepository(server_main.DATA_ROOT)

        with TestClient(app) as client:
            yield client

        server_main.DATA_ROOT = original_data_root
        server_main.INDEX_REPO = original_repo


def test_health_endpoint(api_client: TestClient) -> None:
    response = api_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_and_files_endpoints(api_client: TestClient) -> None:
    index_response = api_client.get("/v1/index")
    assert index_response.status_code == 200
    payload = index_response.json()
    assert payload["index_version"] == 1
    assert len(payload["titles"]) == 1

    title = payload["titles"][0]
    file_id = title["rom"]["file_id"]
    assert title["assets"] == []

    file_response = api_client.get(f"/v1/files/{file_id}")
    assert file_response.status_code == 200
    assert file_response.content == b"rom-bytes"


def test_unknown_file_and_asset_ids_return_404(api_client: TestClient) -> None:
    file_response = api_client.get("/v1/files/file_missing")
    assert file_response.status_code == 404
    assert file_response.json()["detail"] == "Unknown file_id: file_missing"

    asset_response = api_client.get("/v1/assets/asset_missing")
    assert asset_response.status_code == 404
    assert asset_response.json()["detail"] == "Unknown asset_id: asset_missing"


def test_firmware_endpoint_returns_file_and_404_for_missing(api_client: TestClient) -> None:
    ok_response = api_client.get("/v1/firmware/NES/dummy.bin")
    assert ok_response.status_code == 200
    assert ok_response.content == b"firmware-bytes"

    missing_response = api_client.get("/v1/firmware/NES/missing.bin")
    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == "Firmware file not found: NES/missing.bin"


def test_firmware_endpoint_blocks_traversal(api_client: TestClient) -> None:
    traversal_filename = api_client.get("/v1/firmware/NES/..%5Csecret.bin")
    assert traversal_filename.status_code == 404
    assert traversal_filename.json()["detail"] == "Firmware file not found"

    traversal_system = api_client.get("/v1/firmware/..%5C..%5CWindows/dummy.bin")
    assert traversal_system.status_code == 404
    assert traversal_system.json()["detail"] == "Firmware file not found"
