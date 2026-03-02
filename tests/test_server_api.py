from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import gamehub_server.index_repository as repo_module
import gamehub_server.main as server_main
from gamehub_common.models import LibraryIndex
from gamehub_server.index_repository import IndexRepository
from gamehub_server.indexer import IndexBundle
from gamehub_server.main import app


def _write_file(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


@pytest.fixture
def api_client(workspace_tempdir):
    with workspace_tempdir(prefix="gamehub-api-") as temp_dir:
        root = temp_dir
        _write_file(root / "roms" / "NES" / "SuperMarioBros.nes", b"rom-bytes")
        _write_file(root / "firmware" / "NES" / "dummy.bin", b"firmware-bytes")
        _write_file(root / "saves" / "NES" / "SuperMarioBros" / "battery" / "slot1.sav", b"save-bytes")

        original_data_root = server_main.DATA_ROOT
        original_repo = server_main.INDEX_REPO
        server_main.DATA_ROOT = root.resolve()
        server_main.INDEX_REPO = IndexRepository(server_main.DATA_ROOT, poll_seconds=0)

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


def test_index_endpoint_auto_refreshes_when_rom_and_firmware_are_added(api_client: TestClient) -> None:
    server_main.INDEX_REPO = IndexRepository(server_main.DATA_ROOT, poll_seconds=0, stable_seconds=0)
    first = api_client.get("/v1/index")
    assert first.status_code == 200
    first_payload = first.json()
    assert len(first_payload["titles"]) == 1

    nes_first = next(system for system in first_payload["systems"] if system["name"] == "NES")
    assert {entry["filename"] for entry in nes_first["firmware"]} == {"dummy.bin"}

    _write_file(server_main.DATA_ROOT / "roms" / "NES" / "MegaMan2.nes", b"rom-2")
    _write_file(server_main.DATA_ROOT / "firmware" / "NES" / "addon.bin", b"fw-addon")

    second = api_client.get("/v1/index")
    assert second.status_code == 200
    second_payload = second.json()
    assert len(second_payload["titles"]) == 2
    assert {entry["title_name"] for entry in second_payload["titles"]} == {"SuperMarioBros", "MegaMan2"}

    nes_second = next(system for system in second_payload["systems"] if system["name"] == "NES")
    assert {entry["filename"] for entry in nes_second["firmware"]} == {"dummy.bin", "addon.bin"}


def test_save_endpoint_returns_file_and_404_for_unknown(api_client: TestClient) -> None:
    index_response = api_client.get("/v1/index")
    assert index_response.status_code == 200

    payload = index_response.json()
    assert len(payload["saves"]) == 1

    save_id = payload["saves"][0]["save_id"]
    save_response = api_client.get(f"/v1/saves/{save_id}")
    assert save_response.status_code == 200
    assert save_response.content == b"save-bytes"

    missing_response = api_client.get("/v1/saves/save_missing")
    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == "Unknown save_id: save_missing"


def test_save_endpoint_blocks_traversal_style_targets_with_id_lookup(api_client: TestClient) -> None:
    traversal_response = api_client.get("/v1/saves/..%5Csecret.sav")
    assert traversal_response.status_code == 404
    assert traversal_response.json()["detail"] == r"Unknown save_id: ..\secret.sav"


def test_save_upload_route_updates_existing_save_and_returns_refreshed_metadata(api_client: TestClient) -> None:
    index_response = api_client.get("/v1/index")
    assert index_response.status_code == 200

    original_save = index_response.json()["saves"][0]
    save_id = original_save["save_id"]
    save_path = server_main.DATA_ROOT / "saves" / "NES" / "SuperMarioBros" / "battery" / "slot1.sav"

    response = api_client.put(f"/v1/saves/{save_id}", content=b"new-save")

    assert response.status_code == 200
    payload = response.json()
    assert payload["save_id"] == save_id
    assert payload["sha256"] != original_save["sha256"]

    save_response = api_client.get(f"/v1/saves/{save_id}")
    assert save_response.status_code == 200
    assert save_response.content == b"new-save"
    backups = list(save_path.parent.glob(f"{save_path.name}.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"save-bytes"


def test_save_upload_route_returns_404_for_unknown_save(api_client: TestClient) -> None:
    response = api_client.put("/v1/saves/save_missing", content=b"new-save")

    assert response.status_code == 404
    assert response.json()["detail"] == "Unknown save_id: save_missing"


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


def _empty_index_bundle() -> IndexBundle:
    return IndexBundle(
        index=LibraryIndex(index_version=1, systems=(), titles=()),
        file_paths={},
        asset_paths={},
    )


def test_index_repository_caches_without_ttl(monkeypatch) -> None:
    calls = {"count": 0}

    def fake_build_index(_data_root: Path) -> IndexBundle:
        calls["count"] += 1
        return _empty_index_bundle()

    monkeypatch.setattr(repo_module, "build_index", fake_build_index)
    repo = IndexRepository(Path("unused"), refresh_seconds=0, poll_seconds=0)

    repo.load()
    repo.load()
    repo.load()

    assert calls["count"] == 1


def test_index_repository_refreshes_when_ttl_expires(monkeypatch) -> None:
    calls = {"count": 0}
    monotonic_values = iter([100.0, 100.0, 100.0, 105.0, 111.0, 111.0, 111.0])

    def fake_build_index(_data_root: Path) -> IndexBundle:
        calls["count"] += 1
        return _empty_index_bundle()

    monkeypatch.setattr(repo_module, "build_index", fake_build_index)
    monkeypatch.setattr(repo_module, "_snapshot_data_signature", lambda _data_root: "sig-a")
    monkeypatch.setattr(repo_module.time, "monotonic", lambda: next(monotonic_values))
    repo = IndexRepository(Path("unused"), refresh_seconds=10, poll_seconds=0)

    repo.load()
    repo.load()
    repo.load()

    assert calls["count"] == 2


def test_index_repository_refreshes_when_data_signature_changes(monkeypatch) -> None:
    calls = {"count": 0}
    signatures = iter(["sig-a", "sig-b", "sig-b"])
    monotonic_values = iter([100.0, 100.0, 100.0, 101.0, 101.0, 101.0, 102.0])

    def fake_build_index(_data_root: Path) -> IndexBundle:
        calls["count"] += 1
        return _empty_index_bundle()

    monkeypatch.setattr(repo_module, "build_index", fake_build_index)
    monkeypatch.setattr(repo_module, "_snapshot_data_signature", lambda _data_root: next(signatures))
    monkeypatch.setattr(repo_module.time, "monotonic", lambda: next(monotonic_values))
    repo = IndexRepository(Path("unused"), refresh_seconds=0, poll_seconds=0, stable_seconds=0)

    repo.load()
    repo.load()
    repo.load()

    assert calls["count"] == 2


def test_index_repository_waits_for_stable_signature_before_refreshing(monkeypatch) -> None:
    calls = {"count": 0}
    signatures = iter(["sig-a", "sig-b", "sig-b", "sig-b"])
    monotonic_values = iter([100.0, 100.0, 100.0, 101.0, 102.0, 104.0, 104.0, 104.0])

    def fake_build_index(_data_root: Path) -> IndexBundle:
        calls["count"] += 1
        return _empty_index_bundle()

    monkeypatch.setattr(repo_module, "build_index", fake_build_index)
    monkeypatch.setattr(repo_module, "_snapshot_data_signature", lambda _data_root: next(signatures))
    monkeypatch.setattr(repo_module.time, "monotonic", lambda: next(monotonic_values))
    repo = IndexRepository(Path("unused"), refresh_seconds=0, poll_seconds=0, stable_seconds=2.5)

    repo.load()
    repo.load()
    repo.load()
    repo.load()

    assert calls["count"] == 2


def test_index_repository_does_not_double_rebuild_when_loads_overlap(monkeypatch) -> None:
    calls = {"count": 0}
    first_started = threading.Event()
    second_checked_sources = threading.Event()
    allow_finish = threading.Event()
    results: list[IndexBundle] = []
    errors: list[Exception] = []

    def fake_build_index(_data_root: Path) -> IndexBundle:
        calls["count"] += 1
        if calls["count"] == 1:
            first_started.set()
            assert allow_finish.wait(timeout=2.0)
        return _empty_index_bundle()

    def fake_snapshot(_data_root: Path) -> str:
        if threading.current_thread().name == "second-load":
            second_checked_sources.set()
        return "sig-a"

    def load_worker() -> None:
        try:
            results.append(repo.load())
        except Exception as exc:  # pragma: no cover - failure path asserted below
            errors.append(exc)

    monkeypatch.setattr(repo_module, "build_index", fake_build_index)
    monkeypatch.setattr(repo_module, "_snapshot_data_signature", fake_snapshot)
    repo = IndexRepository(Path("unused"), refresh_seconds=0, poll_seconds=0)

    first_thread = threading.Thread(target=load_worker, name="first-load")
    second_thread = threading.Thread(target=load_worker, name="second-load")

    first_thread.start()
    assert first_started.wait(timeout=2.0)
    second_thread.start()
    assert second_checked_sources.wait(timeout=2.0)
    allow_finish.set()

    first_thread.join(timeout=2.0)
    second_thread.join(timeout=2.0)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert not errors
    assert len(results) == 2
    assert calls["count"] == 1


def test_index_repository_logs_new_files_when_source_change_refreshes(workspace_tempdir, caplog) -> None:
    with workspace_tempdir(prefix="gamehub-index-log-") as root:
        _write_file(root / "roms" / "NES" / "SuperMarioBros.nes", b"rom-1")
        _write_file(root / "firmware" / "NES" / "dummy.bin", b"fw-1")
        repo = IndexRepository(root.resolve(), refresh_seconds=0, poll_seconds=0, stable_seconds=0)
        repo.load()

        _write_file(root / "roms" / "NES" / "MegaMan2.nes", b"rom-2")
        _write_file(root / "firmware" / "NES" / "addon.bin", b"fw-2")

        with caplog.at_level("INFO", logger=repo_module.logger.name):
            repo.load()

    messages = [record.getMessage() for record in caplog.records]
    assert any("index contents changed reason=source_change" in message for message in messages)
    assert any("indexed new rom file" in message and "MegaMan2" in message for message in messages)
    assert any("indexed new firmware file" in message and "addon.bin" in message for message in messages)


def test_index_endpoint_refresh_query_forces_reload(api_client: TestClient, monkeypatch) -> None:
    original_build_index = repo_module.build_index
    calls = {"count": 0}

    def counting_build_index(data_root: Path) -> IndexBundle:
        calls["count"] += 1
        return original_build_index(data_root)

    monkeypatch.setattr(repo_module, "build_index", counting_build_index)
    server_main.INDEX_REPO = IndexRepository(server_main.DATA_ROOT, refresh_seconds=0, poll_seconds=0, stable_seconds=0)

    first = api_client.get("/v1/index")
    second = api_client.get("/v1/index")
    third = api_client.get("/v1/index?refresh=1")

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 200
    assert calls["count"] == 2


def test_file_and_asset_routes_use_cached_snapshot(api_client: TestClient, monkeypatch) -> None:
    original_build_index = repo_module.build_index
    original_snapshot = repo_module._snapshot_data_signature
    calls = {"count": 0}
    signature_calls = {"count": 0}

    def counting_build_index(data_root: Path) -> IndexBundle:
        calls["count"] += 1
        return original_build_index(data_root)

    def counting_snapshot(data_root: Path) -> str:
        signature_calls["count"] += 1
        return original_snapshot(data_root)

    monkeypatch.setattr(repo_module, "build_index", counting_build_index)
    monkeypatch.setattr(repo_module, "_snapshot_data_signature", counting_snapshot)
    server_main.INDEX_REPO = IndexRepository(server_main.DATA_ROOT, refresh_seconds=0, poll_seconds=0)

    index_response = api_client.get("/v1/index")
    file_id = index_response.json()["titles"][0]["rom"]["file_id"]
    file_response = api_client.get(f"/v1/files/{file_id}")
    asset_response = api_client.get("/v1/assets/asset_missing")

    assert index_response.status_code == 200
    assert file_response.status_code == 200
    assert asset_response.status_code == 404
    assert calls["count"] == 1
    assert signature_calls["count"] == 1


def test_start_and_stop_index_poller_delegate_to_repo(monkeypatch) -> None:
    calls = {"start": 0, "stop": 0}

    class _Repo:
        def start_polling(self) -> None:
            calls["start"] += 1

        def stop_polling(self) -> None:
            calls["stop"] += 1

    monkeypatch.setattr(server_main, "INDEX_REPO", _Repo())

    server_main.start_index_poller()
    server_main.stop_index_poller()

    assert calls == {"start": 1, "stop": 1}


def test_warm_index_cache_logs_start_and_completion(monkeypatch, caplog) -> None:
    bundle = SimpleNamespace(index=SimpleNamespace(systems=("NES", "SNES"), titles=("A", "B", "C")))

    class _Repo:
        def load(self, force_refresh: bool = False):
            assert force_refresh is True
            return bundle

    monotonic_values = iter([100.0, 102.25])
    monkeypatch.setattr(server_main, "INDEX_REPO", _Repo())
    monkeypatch.setattr(server_main.time, "monotonic", lambda: next(monotonic_values))

    with caplog.at_level("INFO", logger=server_main.logger.name):
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

    with caplog.at_level("INFO", logger=server_main.logger.name):
        with pytest.raises(RuntimeError, match="boom"):
            server_main.warm_index_cache()

    start_logs = [record for record in caplog.records if "index warmup started" in record.getMessage()]
    error_logs = [
        record for record in caplog.records if "index warmup failed elapsed_seconds=1.500" in record.getMessage()
    ]
    assert start_logs
    assert error_logs
    assert error_logs[0].exc_info is not None
