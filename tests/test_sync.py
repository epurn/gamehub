from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import shutil
from uuid import uuid4

from gamehub_cli.config import GamehubConfig
from gamehub_cli.planner import PlanAction, SyncPlan
from gamehub_cli.state import SyncState
from gamehub_cli.sync import (
    _apply_downloads,
    _apply_steam_updates,
    _bootstrap_firmware_dirs,
    _build_artwork_assignments,
    _build_shortcut_specs,
    run_sync,
)
from gamehub_common.models import LibraryIndex, RomSpec, SystemSpec, TitleEntry


@contextmanager
def _workspace_tempdir(prefix: str):
    root = Path(__file__).resolve().parents[1] / ".pytest_tmp_local"
    root.mkdir(parents=True, exist_ok=True)
    temp_dir = root / f"{prefix}{uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=False)
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_apply_downloads_runs_firmware_before_content(monkeypatch) -> None:
    calls: list[str] = []

    def fake_download(server_url: str, url: str, destination: Path, expected_sha256: str, timeout: float) -> None:
        calls.append(url)

    monkeypatch.setattr("gamehub_cli.sync.download_with_atomic_write", fake_download)

    firmware_action = PlanAction(
        kind="firmware",
        system="PSX",
        label="scph5501.bin",
        url="/v1/firmware/PSX/scph5501.bin",
        destination=Path("firmware/PSX/scph5501.bin"),
        expected_sha256="a" * 64,
        content_id="PSX/scph5501.bin",
    )
    rom_action = PlanAction(
        kind="rom",
        system="PSX",
        label="Metal Gear Solid ROM",
        url="/v1/files/file_mgs",
        destination=Path("roms/PSX/MetalGearSolid.bin"),
        expected_sha256="b" * 64,
        content_id="file_mgs",
    )
    state = SyncState()
    plan = SyncPlan(firmware_actions=[firmware_action], content_actions=[rom_action])

    _apply_downloads("http://localhost:8000", plan, state, timeout_seconds=20.0)

    assert calls == ["/v1/firmware/PSX/scph5501.bin", "/v1/files/file_mgs"]
    assert state.firmware_checksums["PSX/scph5501.bin"] == "a" * 64
    assert state.downloaded_checksums["file_mgs"] == "b" * 64


def test_apply_steam_updates_lifecycle_order(monkeypatch) -> None:
    order: list[str] = []
    index = LibraryIndex(index_version=1, systems=(), titles=())
    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("library"),
        firmware_dir=Path("firmware"),
        state_path=Path("state.json"),
        steam_userdata_dir=Path("userdata"),
        steam_id=None,
        steam_exe=Path("steam.exe"),
        sgdb_api_key=None,
        sgdb_cache_dir=Path("artwork_cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
    )

    monkeypatch.setattr("gamehub_cli.sync.discover_userdata_dir", lambda explicit: Path("userdata"))
    monkeypatch.setattr(
        "gamehub_cli.sync.discover_steam_id", lambda userdata, preferred_steam_id=None: "76561198000000001"
    )
    monkeypatch.setattr("gamehub_cli.sync.build_context", lambda userdata, steam_id, steam_exe: object())
    monkeypatch.setattr("gamehub_cli.sync.is_steam_running", lambda: True)
    monkeypatch.setattr("gamehub_cli.sync.close_steam_best_effort", lambda: order.append("close"))
    monkeypatch.setattr("gamehub_cli.sync.wait_for_steam_exit", lambda: order.append("wait") or True)
    monkeypatch.setattr("gamehub_cli.sync.backup_steam_configs", lambda context: order.append("backup") or [])
    monkeypatch.setattr(
        "gamehub_cli.sync.upsert_shortcuts",
        lambda context, desired_shortcuts: order.append("shortcuts")
        or type("Result", (), {"app_ids_by_title": {}, "app_ids_by_system": {}, "total_shortcuts": 0})(),
    )
    monkeypatch.setattr("gamehub_cli.sync.update_collections", lambda context, app_ids_by_system: order.append("collections") or 0)
    monkeypatch.setattr(
        "gamehub_cli.sync.update_cloud_collections",
        lambda context, app_ids_by_system: order.append("collections-cloud") or 0,
    )
    monkeypatch.setattr("gamehub_cli.sync.copy_grid_art", lambda context, assignments: order.append("art") or [])
    monkeypatch.setattr(
        "gamehub_cli.sync.prune_grid_noncanonical_variants",
        lambda context, app_ids: order.append("prune") or 0,
    )
    monkeypatch.setattr("gamehub_cli.sync.reopen_steam", lambda context: order.append("reopen") or True)

    _apply_steam_updates(
        config,
        index=index,
        require_steam_closed=True,
        artwork_by_title={},
    )

    assert order == ["close", "wait", "backup", "shortcuts", "collections", "collections-cloud", "art", "prune", "reopen"]


def test_apply_steam_updates_skips_when_steam_cannot_close(monkeypatch, capsys) -> None:
    order: list[str] = []
    index = LibraryIndex(index_version=1, systems=(), titles=())
    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("library"),
        firmware_dir=Path("firmware"),
        state_path=Path("state.json"),
        steam_userdata_dir=Path("userdata"),
        steam_id=None,
        steam_exe=Path("steam.exe"),
        sgdb_api_key=None,
        sgdb_cache_dir=Path("artwork_cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
    )

    monkeypatch.setattr("gamehub_cli.sync.discover_userdata_dir", lambda explicit: Path("userdata"))
    monkeypatch.setattr(
        "gamehub_cli.sync.discover_steam_id", lambda userdata, preferred_steam_id=None: "76561198000000001"
    )
    monkeypatch.setattr("gamehub_cli.sync.build_context", lambda userdata, steam_id, steam_exe: object())
    monkeypatch.setattr("gamehub_cli.sync.is_steam_running", lambda: True)
    monkeypatch.setattr("gamehub_cli.sync.close_steam_best_effort", lambda: order.append("close"))
    monkeypatch.setattr("gamehub_cli.sync.wait_for_steam_exit", lambda: order.append("wait") or False)
    monkeypatch.setattr("gamehub_cli.sync.backup_steam_configs", lambda context: order.append("backup") or [])
    monkeypatch.setattr(
        "gamehub_cli.sync.upsert_shortcuts",
        lambda context, desired_shortcuts: order.append("shortcuts")
        or type("Result", (), {"app_ids_by_title": {}, "app_ids_by_system": {}, "total_shortcuts": 0})(),
    )
    monkeypatch.setattr("gamehub_cli.sync.update_collections", lambda context, app_ids_by_system: order.append("collections") or 0)
    monkeypatch.setattr(
        "gamehub_cli.sync.update_cloud_collections",
        lambda context, app_ids_by_system: order.append("collections-cloud") or 0,
    )
    monkeypatch.setattr("gamehub_cli.sync.copy_grid_art", lambda context, assignments: order.append("art") or [])
    monkeypatch.setattr(
        "gamehub_cli.sync.prune_grid_noncanonical_variants",
        lambda context, app_ids: order.append("prune") or 0,
    )
    monkeypatch.setattr("gamehub_cli.sync.reopen_steam", lambda context: order.append("reopen") or True)

    _apply_steam_updates(
        config,
        index=index,
        require_steam_closed=False,
        artwork_by_title={},
    )

    assert order == ["close", "wait"]
    assert "Steam is still running after close attempt; skipping Steam updates for safety" in capsys.readouterr().out


def test_apply_steam_updates_reopens_even_if_steam_was_not_running(monkeypatch) -> None:
    order: list[str] = []
    index = LibraryIndex(index_version=1, systems=(), titles=())
    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("library"),
        firmware_dir=Path("firmware"),
        state_path=Path("state.json"),
        steam_userdata_dir=Path("userdata"),
        steam_id=None,
        steam_exe=Path("steam.exe"),
        sgdb_api_key=None,
        sgdb_cache_dir=Path("artwork_cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
    )

    monkeypatch.setattr("gamehub_cli.sync.discover_userdata_dir", lambda explicit: Path("userdata"))
    monkeypatch.setattr(
        "gamehub_cli.sync.discover_steam_id", lambda userdata, preferred_steam_id=None: "76561198000000001"
    )
    monkeypatch.setattr("gamehub_cli.sync.build_context", lambda userdata, steam_id, steam_exe: object())
    monkeypatch.setattr("gamehub_cli.sync.is_steam_running", lambda: False)
    monkeypatch.setattr("gamehub_cli.sync.backup_steam_configs", lambda context: order.append("backup") or [])
    monkeypatch.setattr(
        "gamehub_cli.sync.upsert_shortcuts",
        lambda context, desired_shortcuts: order.append("shortcuts")
        or type("Result", (), {"app_ids_by_title": {}, "app_ids_by_system": {}, "total_shortcuts": 0})(),
    )
    monkeypatch.setattr("gamehub_cli.sync.update_collections", lambda context, app_ids_by_system: order.append("collections") or 0)
    monkeypatch.setattr(
        "gamehub_cli.sync.update_cloud_collections",
        lambda context, app_ids_by_system: order.append("collections-cloud") or 0,
    )
    monkeypatch.setattr("gamehub_cli.sync.copy_grid_art", lambda context, assignments: order.append("art") or [])
    monkeypatch.setattr(
        "gamehub_cli.sync.prune_grid_noncanonical_variants",
        lambda context, app_ids: order.append("prune") or 0,
    )
    monkeypatch.setattr("gamehub_cli.sync.reopen_steam", lambda context: order.append("reopen") or True)

    _apply_steam_updates(
        config,
        index=index,
        require_steam_closed=False,
        artwork_by_title={},
    )

    assert order == ["backup", "shortcuts", "collections", "collections-cloud", "art", "prune", "reopen"]


def test_run_sync_skip_steam_avoids_steam_updates(monkeypatch, capsys) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return

        def json(self) -> dict:
            return {"index_version": 1, "systems": [], "titles": []}

    class FakeHttpx:
        @staticmethod
        def get(_url: str, timeout: float) -> FakeResponse:
            assert timeout > 0
            return FakeResponse()

    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("library"),
        firmware_dir=Path("firmware"),
        state_path=Path(".pytest_tmp_local/state-test-skip-steam.json"),
        steam_userdata_dir=Path("userdata"),
        steam_id=None,
        steam_exe=Path("steam.exe"),
        sgdb_api_key=None,
        sgdb_cache_dir=Path("artwork_cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
    )
    steam_called = {"value": False}
    monkeypatch.setattr("gamehub_cli.sync.httpx", FakeHttpx)
    monkeypatch.setattr(
        "gamehub_cli.sync._apply_steam_updates",
        lambda _config, index, require_steam_closed, artwork_by_title: steam_called.__setitem__("value", True),
    )

    exit_code = run_sync(
        config=config,
        dry_run=False,
        verbose=False,
        verify=False,
        require_steam_closed=False,
        skip_steam=True,
    )

    assert exit_code == 0
    assert steam_called["value"] is False
    assert "Skipping Steam lifecycle and config updates (--skip-steam)" in capsys.readouterr().out


def test_run_sync_invokes_retroarch_core_provisioner(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return

        def json(self) -> dict:
            return {"index_version": 1, "systems": [], "titles": []}

    class FakeHttpx:
        @staticmethod
        def get(_url: str, timeout: float) -> FakeResponse:
            assert timeout > 0
            return FakeResponse()

    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("library"),
        firmware_dir=Path("firmware"),
        state_path=Path(".pytest_tmp_local/state-test-core-provisioner.json"),
        steam_userdata_dir=Path("userdata"),
        steam_id=None,
        steam_exe=Path("steam.exe"),
        sgdb_api_key=None,
        sgdb_cache_dir=Path("artwork_cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
    )
    core_args: dict[str, object] = {}
    monkeypatch.setattr("gamehub_cli.sync.httpx", FakeHttpx)
    monkeypatch.setattr(
        "gamehub_cli.sync.ensure_retroarch_cores",
        lambda index, dry_run, verbose, **kwargs: core_args.update(
            {"index": index, "dry_run": dry_run, "verbose": verbose, **kwargs}
        ),
    )

    exit_code = run_sync(
        config=config,
        dry_run=True,
        verbose=False,
        verify=False,
        require_steam_closed=False,
        skip_steam=False,
    )

    assert exit_code == 0
    assert core_args.get("dry_run") is True
    assert core_args.get("verbose") is False


def test_run_sync_applies_steam_updates_even_when_no_downloads(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return

        def json(self) -> dict:
            return {"index_version": 1, "systems": [], "titles": []}

    class FakeHttpx:
        @staticmethod
        def get(_url: str, timeout: float) -> FakeResponse:
            assert timeout > 0
            return FakeResponse()

    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("library"),
        firmware_dir=Path("firmware"),
        state_path=Path(".pytest_tmp_local/state-test-steam-reconcile.json"),
        steam_userdata_dir=Path("userdata"),
        steam_id=None,
        steam_exe=Path("steam.exe"),
        sgdb_api_key=None,
        sgdb_cache_dir=Path("artwork_cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
    )
    steam_called = {"value": False}
    monkeypatch.setattr("gamehub_cli.sync.httpx", FakeHttpx)
    monkeypatch.setattr(
        "gamehub_cli.sync._apply_steam_updates",
        lambda _config, index, require_steam_closed, artwork_by_title: steam_called.__setitem__("value", True),
    )

    exit_code = run_sync(
        config=config,
        dry_run=False,
        verbose=False,
        verify=False,
        require_steam_closed=False,
        skip_steam=False,
    )

    assert exit_code == 0
    assert steam_called["value"] is True


def test_run_sync_dry_run_errors_for_missing_configured_steam_id(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return

        def json(self) -> dict:
            return {"index_version": 1, "systems": [], "titles": []}

    class FakeHttpx:
        @staticmethod
        def get(_url: str, timeout: float) -> FakeResponse:
            assert timeout > 0
            return FakeResponse()

    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("library"),
        firmware_dir=Path("firmware"),
        state_path=Path(".pytest_tmp_local/state-test-dry-run-steam-id.json"),
        steam_userdata_dir=Path("userdata"),
        steam_id="76561198000000001",
        steam_exe=Path("steam.exe"),
        sgdb_api_key=None,
        sgdb_cache_dir=Path("artwork_cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
    )
    monkeypatch.setattr("gamehub_cli.sync.httpx", FakeHttpx)
    monkeypatch.setattr("gamehub_cli.sync.discover_userdata_dir", lambda explicit: Path("userdata"))
    monkeypatch.setattr(
        "gamehub_cli.sync.discover_steam_id",
        lambda userdata, preferred_steam_id=None: (_ for _ in ()).throw(
            ValueError("Configured steam_id was not found in userdata: 76561198000000001")
        ),
    )

    try:
        run_sync(
            config=config,
            dry_run=True,
            verbose=False,
            verify=False,
            require_steam_closed=False,
            skip_steam=False,
        )
    except ValueError as exc:
        assert "Configured steam_id was not found in userdata" in str(exc)
    else:
        raise AssertionError("Expected ValueError when configured steam_id is missing")


def test_bootstrap_firmware_dirs_creates_system_subdirs() -> None:
    with _workspace_tempdir("gamehub-sync-layout-") as temp_root:
        config = GamehubConfig(
            server_url="http://localhost:8000",
            library_dir=temp_root / "library",
            firmware_dir=temp_root / "firmware",
            state_path=temp_root / "state.json",
            steam_userdata_dir=None,
            steam_id=None,
            steam_exe=None,
            sgdb_api_key=None,
            sgdb_cache_dir=temp_root / "cache",
            sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        )
        index = LibraryIndex(
            index_version=1,
            systems=(
                SystemSpec(
                    name="NES",
                    rom_extensions=(".nes",),
                    default_emulator="retroarch",
                    launch_template='"{emulator}" "{rom}"',
                    firmware=(),
                ),
                SystemSpec(
                    name="PSX",
                    rom_extensions=(".chd",),
                    default_emulator="retroarch",
                    launch_template='"{emulator}" "{rom}"',
                    firmware=(),
                ),
            ),
            titles=(),
        )

        _bootstrap_firmware_dirs(config=config, index=index, dry_run=False, verbose=False)

        assert (temp_root / "firmware").is_dir()
        assert (temp_root / "firmware" / "NES").is_dir()
        assert (temp_root / "firmware" / "PSX").is_dir()


def test_bootstrap_firmware_dirs_dry_run_does_not_mutate() -> None:
    with _workspace_tempdir("gamehub-sync-layout-") as temp_root:
        config = GamehubConfig(
            server_url="http://localhost:8000",
            library_dir=temp_root / "library",
            firmware_dir=temp_root / "firmware",
            state_path=temp_root / "state.json",
            steam_userdata_dir=None,
            steam_id=None,
            steam_exe=None,
            sgdb_api_key=None,
            sgdb_cache_dir=temp_root / "cache",
            sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        )
        index = LibraryIndex(
            index_version=1,
            systems=(
                SystemSpec(
                    name="NES",
                    rom_extensions=(".nes",),
                    default_emulator="retroarch",
                    launch_template='"{emulator}" "{rom}"',
                    firmware=(),
                ),
            ),
            titles=(),
        )

        _bootstrap_firmware_dirs(config=config, index=index, dry_run=True, verbose=True)

        assert not (temp_root / "firmware").exists()


def test_build_artwork_assignments_uses_cache_without_api_key() -> None:
    with _workspace_tempdir("gamehub-sync-art-cache-") as temp_root:
        cache_dir = temp_root / "sgdb-cache"
        title_id = "title_nes_mario"
        cached_grid = cache_dir / title_id / "grid-abc123.png"
        cached_grid.parent.mkdir(parents=True, exist_ok=True)
        cached_grid.write_bytes(b"grid")
        config = GamehubConfig(
            server_url="http://localhost:8000",
            library_dir=temp_root / "library",
            firmware_dir=temp_root / "firmware",
            state_path=temp_root / "state.json",
            steam_userdata_dir=None,
            steam_id=None,
            steam_exe=None,
            sgdb_api_key=None,
            sgdb_cache_dir=cache_dir,
            sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        )
        index = LibraryIndex(
            index_version=1,
            systems=(),
            titles=(
                TitleEntry(
                    title_id=title_id,
                    system="NES",
                    title_name="Super Mario Bros",
                    title_rel_dir="NES/SuperMarioBros.nes",
                    emulator="retroarch",
                    launch_template='"{emulator}" "{rom}"',
                    rom=RomSpec(
                        file_id="rom_1",
                        rel_path="roms/NES/SuperMarioBros.nes",
                        sha256="a" * 64,
                        size_bytes=3,
                        extension=".nes",
                    ),
                    assets=(),
                ),
            ),
        )

        assignments = _build_artwork_assignments(
            config=config,
            index=index,
            dry_run=False,
            timeout_seconds=5.0,
            verbose=False,
        )

        assert title_id in assignments
        assert assignments[title_id]["grid"] == cached_grid


def test_build_shortcut_specs_resolves_emulator_path(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-sync-shortcuts-") as temp_root:
        config = GamehubConfig(
            server_url="http://localhost:8000",
            library_dir=temp_root / "library",
            firmware_dir=temp_root / "firmware",
            state_path=temp_root / "state.json",
            steam_userdata_dir=None,
            steam_id=None,
            steam_exe=None,
            sgdb_api_key=None,
            sgdb_cache_dir=temp_root / "cache",
            sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        )
        title = TitleEntry(
            title_id="title_nes_mario",
            system="NES",
            title_name="Super Mario Bros",
            title_rel_dir="NES/SuperMarioBros.nes",
            emulator="retroarch",
            launch_template='"{emulator}" -L cores/fceumm_libretro.dll "{rom}"',
            rom=RomSpec(
                file_id="rom_1",
                rel_path="roms/NES/SuperMarioBros.nes",
                sha256="a" * 64,
                size_bytes=3,
                extension=".nes",
            ),
            assets=(),
        )
        index = LibraryIndex(index_version=1, systems=(), titles=(title,))
        monkeypatch.setattr("gamehub_cli.sync.resolve_emulator_executable", lambda value: "C:\\RetroArch\\retroarch.exe")

        specs = _build_shortcut_specs(index=index, config=config)

        assert len(specs) == 1
        assert specs[0].exe == '"C:\\RetroArch\\retroarch.exe"'
        assert '-L cores/fceumm_libretro.dll' in specs[0].launch_options


def test_build_shortcut_specs_uses_title_rom_path_for_all_titles(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-sync-shortcuts-") as temp_root:
        config = GamehubConfig(
            server_url="http://localhost:8000",
            library_dir=temp_root / "library",
            firmware_dir=temp_root / "firmware",
            state_path=temp_root / "state.json",
            steam_userdata_dir=None,
            steam_id=None,
            steam_exe=None,
            sgdb_api_key=None,
            sgdb_cache_dir=temp_root / "cache",
            sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        )
        title_psx = TitleEntry(
            title_id="title_psx",
            system="PSX",
            title_name="Crash Team Racing",
            title_rel_dir="PSX/Crash Team Racing.cue",
            emulator="retroarch",
            launch_template='"{emulator}" -L cores/swanstation_libretro.dll "{rom}"',
            rom=RomSpec(
                file_id="rom_psx",
                rel_path="roms/PSX/Crash Team Racing.cue",
                sha256="a" * 64,
                size_bytes=3,
                extension=".cue",
            ),
            assets=(),
        )
        title_ps2 = TitleEntry(
            title_id="title_ps2",
            system="PS2",
            title_name="Gran Turismo 4",
            title_rel_dir="PS2/Gran Turismo 4.bin",
            emulator="pcsx2",
            launch_template='"{emulator}" -fullscreen "{rom}"',
            rom=RomSpec(
                file_id="rom_ps2",
                rel_path="roms/PS2/Gran Turismo 4.bin",
                sha256="b" * 64,
                size_bytes=3,
                extension=".bin",
            ),
            assets=(),
        )
        index = LibraryIndex(index_version=1, systems=(), titles=(title_psx, title_ps2))
        monkeypatch.setattr("gamehub_cli.sync.resolve_emulator_executable", lambda value: "C:\\RetroArch\\retroarch.exe")

        specs = _build_shortcut_specs(index=index, config=config)

        assert len(specs) == 2
        by_title = {spec.title_name: spec for spec in specs}
        assert str(temp_root / "library" / "roms" / "PSX" / "Crash Team Racing.cue") in by_title[
            "Crash Team Racing"
        ].launch_options
        assert str(temp_root / "library" / "roms" / "PS2" / "Gran Turismo 4.bin") in by_title[
            "Gran Turismo 4"
        ].launch_options
