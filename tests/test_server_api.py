from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from gamehub_server.main import IndexRepository, app
import gamehub_server.main as server_main
from gamehub_common.models import LibraryIndex


def _write_file(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


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


def _empty_index_bundle() -> server_main.IndexBundle:
    return server_main.IndexBundle(
        index=LibraryIndex(index_version=1, systems=(), titles=()),
        file_paths={},
        asset_paths={},
    )


def test_index_repository_caches_without_ttl(monkeypatch) -> None:
    calls = {"count": 0}

    def fake_build_index(_data_root: Path) -> server_main.IndexBundle:
        calls["count"] += 1
        return _empty_index_bundle()

    monkeypatch.setattr(server_main, "build_index", fake_build_index)
    repo = IndexRepository(Path("unused"), refresh_seconds=0)

    repo.load()
    repo.load()
    repo.load()

    assert calls["count"] == 1


def test_index_repository_refreshes_when_ttl_expires(monkeypatch) -> None:
    calls = {"count": 0}
    monotonic_values = iter([100.0, 105.0, 111.0, 112.0, 113.0])

    def fake_build_index(_data_root: Path) -> server_main.IndexBundle:
        calls["count"] += 1
        return _empty_index_bundle()

    monkeypatch.setattr(server_main, "build_index", fake_build_index)
    monkeypatch.setattr(server_main.time, "monotonic", lambda: next(monotonic_values))
    repo = IndexRepository(Path("unused"), refresh_seconds=10)

    repo.load()
    repo.load()
    repo.load()

    assert calls["count"] == 2


def test_index_endpoint_refresh_query_forces_reload(api_client: TestClient, monkeypatch) -> None:
    original_build_index = server_main.build_index
    calls = {"count": 0}

    def counting_build_index(data_root: Path) -> server_main.IndexBundle:
        calls["count"] += 1
        return original_build_index(data_root)

    monkeypatch.setattr(server_main, "build_index", counting_build_index)
    server_main.INDEX_REPO = IndexRepository(server_main.DATA_ROOT, refresh_seconds=0)

    first = api_client.get("/v1/index")
    second = api_client.get("/v1/index")
    third = api_client.get("/v1/index?refresh=1")

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 200
    assert calls["count"] == 2


def test_file_and_asset_routes_use_cached_snapshot(api_client: TestClient, monkeypatch) -> None:
    original_build_index = server_main.build_index
    calls = {"count": 0}

    def counting_build_index(data_root: Path) -> server_main.IndexBundle:
        calls["count"] += 1
        return original_build_index(data_root)

    monkeypatch.setattr(server_main, "build_index", counting_build_index)
    server_main.INDEX_REPO = IndexRepository(server_main.DATA_ROOT, refresh_seconds=0)

    index_response = api_client.get("/v1/index")
    file_id = index_response.json()["titles"][0]["rom"]["file_id"]
    file_response = api_client.get(f"/v1/files/{file_id}")
    asset_response = api_client.get("/v1/assets/asset_missing")

    assert index_response.status_code == 200
    assert file_response.status_code == 200
    assert asset_response.status_code == 404
    assert calls["count"] == 1


def test_warm_index_cache_logs_start_and_completion(monkeypatch, caplog) -> None:
    bundle = SimpleNamespace(index=SimpleNamespace(systems=("NES", "SNES"), titles=("A", "B", "C")))

    class _Repo:
        def load(self, force_refresh: bool = False):
            assert force_refresh is True
            return bundle

    monotonic_values = iter([100.0, 102.25])
    monkeypatch.setattr(server_main, "INDEX_REPO", _Repo())
    monkeypatch.setattr(server_main.time, "monotonic", lambda: next(monotonic_values))

    with caplog.at_level("INFO", logger=server_main.__name__):
        server_main.warm_index_cache()

    messages = [record.getMessage() for record in caplog.records]
    assert any("index warmup started" in message for message in messages)
    assert any("index warmup completed elapsed_seconds=2.250 systems=2 titles=3" in message for message in messages)


def test_warm_index_cache_logs_error_and_reraises(monkeypatch, caplog) -> None:
    class _FailingRepo:
        def load(self, force_refresh: bool = False):
            assert force_refresh is True
            raise RuntimeError("boom")

    monotonic_values = iter([200.0, 201.5])
    monkeypatch.setattr(server_main, "INDEX_REPO", _FailingRepo())
    monkeypatch.setattr(server_main.time, "monotonic", lambda: next(monotonic_values))

    with caplog.at_level("INFO", logger=server_main.__name__):
        with pytest.raises(RuntimeError, match="boom"):
            server_main.warm_index_cache()

    start_logs = [record for record in caplog.records if "index warmup started" in record.getMessage()]
    error_logs = [
        record for record in caplog.records if "index warmup failed elapsed_seconds=1.500" in record.getMessage()
    ]
    assert start_logs
    assert error_logs
    assert error_logs[0].exc_info is not None
