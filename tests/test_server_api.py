from __future__ import annotations

import asyncio
import errno
import threading
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import gamehub_server.index_repository as repo_module
import gamehub_server.main as server_main
import gamehub_server.save_api as save_api
from gamehub_common.ids import make_save_id
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


def test_file_endpoint_rejects_cached_symlink_escape(api_client: TestClient, make_symlink) -> None:
    index_response = api_client.get("/v1/index")
    file_id = index_response.json()["titles"][0]["rom"]["file_id"]
    rom_path = server_main.DATA_ROOT / "roms" / "NES" / "SuperMarioBros.nes"
    escaped_path = server_main.DATA_ROOT.parent / "outside-rom.nes"
    _write_file(escaped_path, b"secret-rom")
    rom_path.unlink()
    make_symlink(rom_path, escaped_path)

    response = api_client.get(f"/v1/files/{file_id}")

    assert response.status_code == 404
    assert response.json()["detail"] == f"Unknown file_id: {file_id}"


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


def test_save_endpoint_rejects_cached_symlink_escape(api_client: TestClient, make_symlink) -> None:
    index_response = api_client.get("/v1/index")
    save_id = index_response.json()["saves"][0]["save_id"]
    save_path = server_main.DATA_ROOT / "saves" / "NES" / "SuperMarioBros" / "battery" / "slot1.sav"
    escaped_path = server_main.DATA_ROOT.parent / "outside-save.sav"
    _write_file(escaped_path, b"secret-save")
    save_path.unlink()
    make_symlink(save_path, escaped_path)

    response = api_client.get(f"/v1/saves/{save_id}")

    assert response.status_code == 404
    assert response.json()["detail"] == f"Unknown save_id: {save_id}"


def test_save_endpoint_blocks_traversal_style_targets_with_id_lookup(api_client: TestClient) -> None:
    traversal_response = api_client.get("/v1/saves/..%5Csecret.sav")
    assert traversal_response.status_code == 404
    assert traversal_response.json()["detail"] == r"Unknown save_id: ..\secret.sav"


def test_get_save_bindings_returns_catalog(api_client: TestClient) -> None:
    response = api_client.get("/v1/save-bindings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["bindings"]
    assert payload["bindings"][0]["binding_id"].startswith("savebind_")


def test_save_upload_route_updates_existing_save_and_returns_refreshed_metadata(api_client: TestClient) -> None:
    index_response = api_client.get("/v1/index")
    assert index_response.status_code == 200

    original_save = index_response.json()["saves"][0]
    save_id = original_save["save_id"]
    save_path = server_main.DATA_ROOT / "saves" / "NES" / "SuperMarioBros" / "battery" / "slot1.sav"
    binding_id = api_client.get("/v1/save-bindings").json()["bindings"][0]["binding_id"]
    canonical_suffix = "slot1.sav"

    response = api_client.put(
        f"/v1/saves/{save_id}",
        data={
            "binding_id": binding_id,
            "canonical_suffix": canonical_suffix,
            "expected_remote_sha256": original_save["sha256"],
        },
        files={"file": ("slot1.sav", b"new-save", "application/octet-stream")},
    )

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


def test_save_upload_route_prunes_older_backups_after_repeated_updates(api_client: TestClient) -> None:
    index_response = api_client.get("/v1/index")
    assert index_response.status_code == 200

    payload = index_response.json()
    save_id = payload["saves"][0]["save_id"]
    expected_sha = payload["saves"][0]["sha256"]
    binding_id = api_client.get("/v1/save-bindings").json()["bindings"][0]["binding_id"]
    save_path = server_main.DATA_ROOT / "saves" / "NES" / "SuperMarioBros" / "battery" / "slot1.sav"

    for content in (b"new-save-1", b"new-save-2", b"new-save-3", b"new-save-4"):
        response = api_client.put(
            f"/v1/saves/{save_id}",
            data={
                "binding_id": binding_id,
                "canonical_suffix": "slot1.sav",
                "expected_remote_sha256": expected_sha,
            },
            files={"file": ("slot1.sav", content, "application/octet-stream")},
        )
        assert response.status_code == 200
        expected_sha = response.json()["sha256"]

    backups = sorted(save_path.parent.glob(f"{save_path.name}.*.bak"))
    assert len(backups) == 3
    assert sorted(candidate.read_bytes() for candidate in backups) == [b"new-save-1", b"new-save-2", b"new-save-3"]


def test_save_upload_route_creates_unknown_save_from_binding(api_client: TestClient) -> None:
    binding = api_client.get("/v1/save-bindings").json()["bindings"][0]
    save_id = make_save_id("saves/NES/SuperMarioBros/battery/SuperMarioBros.srm")
    save_path = server_main.DATA_ROOT / "saves" / "NES" / "SuperMarioBros" / "battery" / "SuperMarioBros.srm"

    response = api_client.put(
        f"/v1/saves/{save_id}",
        data={
            "binding_id": binding["binding_id"],
            "canonical_suffix": "SuperMarioBros.srm",
        },
        files={"file": ("SuperMarioBros.srm", b"first-save", "application/octet-stream")},
    )

    assert response.status_code == 201
    assert save_path.read_bytes() == b"first-save"


def test_save_upload_route_creates_gc_learned_tree_save_from_binding(api_client: TestClient) -> None:
    _write_file(server_main.DATA_ROOT / "roms" / "GC" / "WindWaker.iso", b"gc-rom")
    server_main.INDEX_REPO.load(force_refresh=True)

    bindings = api_client.get("/v1/save-bindings").json()["bindings"]
    binding = next(item for item in bindings if item["system"] == "GC" and item["kind"] == "per_game")
    save_rel = "saves/GC/WindWaker/per_game/USA/Card A/01-GZLE-gczelda.gci"
    save_id = make_save_id(save_rel)
    save_path = (
        server_main.DATA_ROOT / "saves" / "GC" / "WindWaker" / "per_game" / "USA" / "Card A" / "01-GZLE-gczelda.gci"
    )

    response = api_client.put(
        f"/v1/saves/{save_id}",
        data={
            "binding_id": binding["binding_id"],
            "canonical_suffix": "USA/Card A/01-GZLE-gczelda.gci",
        },
        files={"file": ("01-GZLE-gczelda.gci", b"gc-save", "application/octet-stream")},
    )

    assert response.status_code == 201
    assert save_path.read_bytes() == b"gc-save"


def test_save_upload_route_rejects_gamehub_backup_suffix_for_learned_tree_binding(api_client: TestClient) -> None:
    _write_file(server_main.DATA_ROOT / "roms" / "GC" / "WindWaker.iso", b"gc-rom")
    server_main.INDEX_REPO.load(force_refresh=True)

    bindings = api_client.get("/v1/save-bindings").json()["bindings"]
    binding = next(item for item in bindings if item["system"] == "GC" and item["kind"] == "per_game")
    canonical_suffix = "USA/Card A/01-GZLE-gczelda.gci.20260308175422.bak"
    save_rel = f"saves/GC/WindWaker/per_game/{canonical_suffix}"
    save_id = make_save_id(save_rel)
    save_path = (
        server_main.DATA_ROOT
        / "saves"
        / "GC"
        / "WindWaker"
        / "per_game"
        / "USA"
        / "Card A"
        / "01-GZLE-gczelda.gci.20260308175422.bak"
    )

    response = api_client.put(
        f"/v1/saves/{save_id}",
        data={
            "binding_id": binding["binding_id"],
            "canonical_suffix": canonical_suffix,
        },
        files={"file": ("01-GZLE-gczelda.gci.20260308175422.bak", b"gc-backup", "application/octet-stream")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "canonical_suffix cannot target a GAMEHUB backup file"
    assert not save_path.exists()


def test_save_upload_route_rejects_expected_sha_mismatch(api_client: TestClient) -> None:
    index_response = api_client.get("/v1/index")
    save = index_response.json()["saves"][0]
    binding_id = api_client.get("/v1/save-bindings").json()["bindings"][0]["binding_id"]

    response = api_client.put(
        f"/v1/saves/{save['save_id']}",
        data={
            "binding_id": binding_id,
            "canonical_suffix": "slot1.sav",
            "expected_remote_sha256": "0" * 64,
        },
        files={"file": ("slot1.sav", b"new-save", "application/octet-stream")},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "remote-sha-mismatch"


def test_save_upload_route_rejects_stale_remote_mutation(api_client: TestClient) -> None:
    index_response = api_client.get("/v1/index")
    save = index_response.json()["saves"][0]
    binding_id = api_client.get("/v1/save-bindings").json()["bindings"][0]["binding_id"]
    save_path = server_main.DATA_ROOT / "saves" / "NES" / "SuperMarioBros" / "battery" / "slot1.sav"

    _write_file(save_path, b"externally-mutated")

    response = api_client.put(
        f"/v1/saves/{save['save_id']}",
        data={
            "binding_id": binding_id,
            "canonical_suffix": "slot1.sav",
            "expected_remote_sha256": save["sha256"],
        },
        files={"file": ("slot1.sav", b"new-save", "application/octet-stream")},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "remote-sha-mismatch"
    assert save_path.read_bytes() == b"externally-mutated"


def test_save_upload_route_rejects_existing_indexed_save_without_expected_sha(api_client: TestClient) -> None:
    binding = api_client.get("/v1/save-bindings").json()["bindings"][0]
    save_id = make_save_id("saves/NES/SuperMarioBros/battery/SuperMarioBros.srm")
    save_path = server_main.DATA_ROOT / "saves" / "NES" / "SuperMarioBros" / "battery" / "SuperMarioBros.srm"

    _write_file(save_path, b"existing-out-of-band")

    response = api_client.put(
        f"/v1/saves/{save_id}",
        data={
            "binding_id": binding["binding_id"],
            "canonical_suffix": "SuperMarioBros.srm",
        },
        files={"file": ("SuperMarioBros.srm", b"first-save", "application/octet-stream")},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "target-exists"
    assert response.json()["detail"]["current"]["save_id"] == save_id
    assert save_path.read_bytes() == b"existing-out-of-band"


def test_save_upload_route_rejects_target_exists_unindexed_conflict(api_client: TestClient, monkeypatch) -> None:
    binding = api_client.get("/v1/save-bindings").json()["bindings"][0]
    save_id = make_save_id("saves/NES/SuperMarioBros/battery/SuperMarioBros.srm")
    save_path = server_main.DATA_ROOT / "saves" / "NES" / "SuperMarioBros" / "battery" / "SuperMarioBros.srm"
    _write_file(save_path, b"existing-out-of-band")

    monkeypatch.setattr(save_api, "_save_spec_from_bundle", lambda bundle, lookup_save_id: None)

    response = api_client.put(
        f"/v1/saves/{save_id}",
        data={
            "binding_id": binding["binding_id"],
            "canonical_suffix": "SuperMarioBros.srm",
        },
        files={"file": ("SuperMarioBros.srm", b"first-save", "application/octet-stream")},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "target-exists-unindexed"
    assert save_path.read_bytes() == b"existing-out-of-band"


def test_save_upload_lock_cleans_up_unused_entries(monkeypatch) -> None:
    monkeypatch.setattr(save_api, "_SAVE_UPLOAD_LOCKS", {})
    monkeypatch.setattr(save_api, "_SAVE_UPLOAD_LOCK_REFS", {})

    async def _exercise() -> None:
        async with save_api._save_upload_lock("save_a"):
            assert len(save_api._SAVE_UPLOAD_LOCKS) == 1
            assert next(iter(save_api._SAVE_UPLOAD_LOCK_REFS.values())) == 1
        assert save_api._SAVE_UPLOAD_LOCKS == {}
        assert save_api._SAVE_UPLOAD_LOCK_REFS == {}

    asyncio.run(_exercise())


def test_save_upload_route_serializes_concurrent_existing_updates(api_client: TestClient, monkeypatch) -> None:
    index_response = api_client.get("/v1/index")
    original_save = index_response.json()["saves"][0]
    save_id = original_save["save_id"]
    binding_id = api_client.get("/v1/save-bindings").json()["bindings"][0]["binding_id"]
    save_path = server_main.DATA_ROOT / "saves" / "NES" / "SuperMarioBros" / "battery" / "slot1.sav"
    original_write = save_api._write_save_upload
    first_started = threading.Event()
    allow_finish = threading.Event()
    write_calls: list[str] = []
    responses: dict[str, tuple[int, dict[str, object]]] = {}
    errors: list[BaseException] = []

    async def _delayed_write(*args, **kwargs):
        write_calls.append(kwargs["save_id"])
        if len(write_calls) == 1:
            first_started.set()
            if not await asyncio.to_thread(allow_finish.wait, 2.0):
                raise AssertionError("timed out waiting to release first save upload")
        return await original_write(*args, **kwargs)

    def _request(name: str, payload: bytes) -> None:
        try:
            response = api_client.put(
                f"/v1/saves/{save_id}",
                data={
                    "binding_id": binding_id,
                    "canonical_suffix": "slot1.sav",
                    "expected_remote_sha256": original_save["sha256"],
                },
                files={"file": ("slot1.sav", payload, "application/octet-stream")},
            )
            responses[name] = (response.status_code, response.json())
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    monkeypatch.setattr(save_api, "_write_save_upload", _delayed_write)

    first_thread = threading.Thread(target=_request, args=("first", b"first-write"), name="save-update-first")
    second_thread = threading.Thread(target=_request, args=("second", b"second-write"), name="save-update-second")

    first_thread.start()
    assert first_started.wait(timeout=2.0)
    second_thread.start()
    allow_finish.set()
    first_thread.join(timeout=2.0)
    second_thread.join(timeout=2.0)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert not errors
    assert write_calls == [save_id]
    assert responses["first"][0] == 200
    assert responses["second"][0] == 409
    assert responses["second"][1]["detail"]["reason"] == "remote-sha-mismatch"
    assert responses["second"][1]["detail"]["current"]["sha256"] == responses["first"][1]["sha256"]
    assert save_path.read_bytes() == b"first-write"


def test_save_upload_route_serializes_concurrent_creates(api_client: TestClient, monkeypatch) -> None:
    binding = api_client.get("/v1/save-bindings").json()["bindings"][0]
    save_id = make_save_id("saves/NES/SuperMarioBros/battery/SuperMarioBros.srm")
    save_path = server_main.DATA_ROOT / "saves" / "NES" / "SuperMarioBros" / "battery" / "SuperMarioBros.srm"
    original_write = save_api._write_save_upload
    first_started = threading.Event()
    allow_finish = threading.Event()
    write_calls: list[str] = []
    responses: dict[str, tuple[int, dict[str, object]]] = {}
    errors: list[BaseException] = []

    async def _delayed_write(*args, **kwargs):
        write_calls.append(kwargs["save_id"])
        if len(write_calls) == 1:
            first_started.set()
            if not await asyncio.to_thread(allow_finish.wait, 2.0):
                raise AssertionError("timed out waiting to release first save upload")
        return await original_write(*args, **kwargs)

    def _request(name: str, payload: bytes) -> None:
        try:
            response = api_client.put(
                f"/v1/saves/{save_id}",
                data={
                    "binding_id": binding["binding_id"],
                    "canonical_suffix": "SuperMarioBros.srm",
                },
                files={"file": ("SuperMarioBros.srm", payload, "application/octet-stream")},
            )
            responses[name] = (response.status_code, response.json())
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    monkeypatch.setattr(save_api, "_write_save_upload", _delayed_write)

    first_thread = threading.Thread(target=_request, args=("first", b"first-create"), name="save-create-first")
    second_thread = threading.Thread(target=_request, args=("second", b"second-create"), name="save-create-second")

    first_thread.start()
    assert first_started.wait(timeout=2.0)
    second_thread.start()
    allow_finish.set()
    first_thread.join(timeout=2.0)
    second_thread.join(timeout=2.0)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert not errors
    assert write_calls == [save_id]
    assert responses["first"][0] == 201
    assert responses["second"][0] == 409
    assert responses["second"][1]["detail"]["reason"] == "target-exists"
    assert responses["second"][1]["detail"]["current"]["save_id"] == save_id
    assert responses["second"][1]["detail"]["current"]["sha256"] == responses["first"][1]["sha256"]
    assert save_path.read_bytes() == b"first-create"


def test_save_upload_route_enforces_upload_size_limit(api_client: TestClient, monkeypatch) -> None:
    binding = api_client.get("/v1/save-bindings").json()["bindings"][0]
    save_id = make_save_id("saves/NES/SuperMarioBros/battery/SuperMarioBros.srm")
    save_path = server_main.DATA_ROOT / "saves" / "NES" / "SuperMarioBros" / "battery" / "SuperMarioBros.srm"
    monkeypatch.setattr(server_main, "MAX_SAVE_UPLOAD_BYTES", 4)

    response = api_client.put(
        f"/v1/saves/{save_id}",
        data={
            "binding_id": binding["binding_id"],
            "canonical_suffix": "SuperMarioBros.srm",
        },
        files={"file": ("SuperMarioBros.srm", b"too-large", "application/octet-stream")},
    )

    assert response.status_code == 413
    assert "Save upload exceeds maximum allowed size" in response.json()["detail"]
    assert not save_path.exists()


def test_write_save_upload_reports_read_only_volume_clearly(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir(prefix="gamehub-api-") as temp_dir:
        target = temp_dir / "saves" / "NES" / "SuperMarioBros" / "battery" / "slot1.sav"
        path_cls = type(target.parent)

        def _readonly_mkdir(self, mode=0o777, parents=False, exist_ok=False):
            raise OSError(errno.EROFS, "Read-only file system")

        monkeypatch.setattr(path_cls, "mkdir", _readonly_mkdir)
        upload = save_api.UploadFile(file=BytesIO(b"save"), filename="slot1.sav")

        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(
                save_api._write_save_upload(
                    target,
                    upload,
                    save_id="save_test",
                    create=True,
                    max_upload_bytes=1024,
                )
            )

        assert excinfo.value.status_code == 500
        assert excinfo.value.detail == (
            "Server data volume is read-only; save uploads require a writable GAMEHUB_DATA_DIR mount"
        )


def test_unknown_file_and_asset_ids_return_404(api_client: TestClient) -> None:
    file_response = api_client.get("/v1/files/file_missing")
    assert file_response.status_code == 404
    assert file_response.json()["detail"] == "Unknown file_id: file_missing"

    asset_response = api_client.get("/v1/assets/asset_missing")
    assert asset_response.status_code == 404
    assert asset_response.json()["detail"] == "Unknown asset_id: asset_missing"


def test_asset_endpoint_rejects_cached_symlink_escape(workspace_tempdir, make_symlink) -> None:
    with workspace_tempdir(prefix="gamehub-api-") as root:
        asset_path = root / "assets" / "cover.png"
        escaped_path = root.parent / "outside-asset.bin"
        _write_file(asset_path, b"asset-bytes")
        _write_file(escaped_path, b"secret-asset")
        bundle = IndexBundle(
            index=LibraryIndex(index_version=1, systems=(), titles=()),
            file_paths={},
            asset_paths={"asset_demo": asset_path},
        )

        class _Repo:
            def load(self, force_refresh: bool = False, *, check_sources: bool = True) -> IndexBundle:
                return bundle

            def start_polling(self) -> None:
                return None

            def stop_polling(self) -> None:
                return None

            def resolve_asset_path(self, asset_id: str) -> Path | None:
                path = bundle.asset_paths.get(asset_id)
                if path is None:
                    return None
                return repo_module.validate_served_file_path(path, allowed_root=root.resolve())

        original_data_root = server_main.DATA_ROOT
        original_repo = server_main.INDEX_REPO
        server_main.DATA_ROOT = root.resolve()
        server_main.INDEX_REPO = _Repo()

        asset_path.unlink()
        make_symlink(asset_path, escaped_path)

        with TestClient(app) as client:
            response = client.get("/v1/assets/asset_demo")

        server_main.DATA_ROOT = original_data_root
        server_main.INDEX_REPO = original_repo

        assert response.status_code == 404
        assert response.json()["detail"] == "Unknown asset_id: asset_demo"


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


def test_firmware_endpoint_rejects_symlink_escape(api_client: TestClient, make_symlink) -> None:
    firmware_path = server_main.DATA_ROOT / "firmware" / "NES" / "dummy.bin"
    escaped_path = server_main.DATA_ROOT.parent / "outside-firmware.bin"
    _write_file(escaped_path, b"secret-firmware")
    firmware_path.unlink()
    make_symlink(firmware_path, escaped_path)

    response = api_client.get("/v1/firmware/NES/dummy.bin")

    assert response.status_code == 404
    assert response.json()["detail"] == "Firmware file not found: NES/dummy.bin"


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


def test_index_repository_refreshes_when_nested_save_tree_changes(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir(prefix="gamehub-index-save-tree-") as root:
        _write_file(root / "roms" / "Wii" / "SuperMarioGalaxy.iso", b"rom-bytes")
        nested_save = root / "saves" / "Wii" / "SuperMarioGalaxy" / "per_game" / "profiles" / "slot1.bin"
        _write_file(nested_save, b"save-a")

        original_build_index = repo_module.build_index
        calls = {"count": 0}

        def counting_build_index(data_root: Path) -> IndexBundle:
            calls["count"] += 1
            return original_build_index(data_root)

        monkeypatch.setattr(repo_module, "build_index", counting_build_index)
        repo = IndexRepository(root.resolve(), refresh_seconds=0, poll_seconds=0, stable_seconds=0)

        first = repo.load()
        first_sha = first.index.saves[0].sha256

        nested_save.write_bytes(b"save-b-updated")

        second = repo.load()

        assert calls["count"] == 2
        assert second.index.saves[0].sha256 != first_sha


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


def test_run_defaults_to_loopback_host(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(app_path: str, *, host: str, port: int, reload: bool) -> None:
        captured.update({"app_path": app_path, "host": host, "port": port, "reload": reload})

    monkeypatch.delenv("GAMEHUB_SERVER_LISTEN_HOST", raising=False)
    monkeypatch.setattr(server_main.uvicorn, "run", fake_run)

    server_main.run()

    assert captured == {
        "app_path": "gamehub_server.main:app",
        "host": "127.0.0.1",
        "port": 8000,
        "reload": False,
    }


def test_run_honors_gamehub_server_listen_host(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(app_path: str, *, host: str, port: int, reload: bool) -> None:
        captured.update({"app_path": app_path, "host": host, "port": port, "reload": reload})

    monkeypatch.setenv("GAMEHUB_SERVER_LISTEN_HOST", "192.168.1.40")
    monkeypatch.setattr(server_main.uvicorn, "run", fake_run)

    server_main.run()

    assert captured["host"] == "192.168.1.40"
