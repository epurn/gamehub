from __future__ import annotations

import re
from pathlib import Path

import pytest

from gamehub_cli.common.config import ControllersConfig, GamehubConfig, SaveSyncConfig
from gamehub_cli.controllers.launch import parse_shortcut_payload
from gamehub_cli.sync.orchestrator import (
    _apply_downloads,
    _apply_steam_updates,
    _bootstrap_firmware_dirs,
    _build_artwork_assignments,
    run_sync,
)
from gamehub_cli.sync.planner import PlanAction, SavePlanAction, SyncPlan
from gamehub_cli.sync.state import SyncState
from gamehub_cli.sync.steam_stage import build_shortcut_specs as _build_shortcut_specs
from gamehub_common.models import LibraryIndex, RomSpec, SystemSpec, TitleEntry


def _normalize_path_token(value: str) -> str:
    return value.strip().strip('"').replace("\\", "/")


@pytest.fixture(autouse=True)
def _default_initialized_sync_state(monkeypatch) -> None:
    monkeypatch.setattr("gamehub_cli.sync.orchestrator.load_state", lambda _path: SyncState(bootstrap_version=1))


def test_apply_downloads_runs_firmware_before_content(monkeypatch) -> None:
    calls: list[str] = []

    def fake_download(server_url: str, url: str, destination: Path, expected_sha256: str, timeout: float) -> None:
        calls.append(url)

    monkeypatch.setattr("gamehub_cli.sync.transfer_stage.download_with_atomic_write", fake_download)

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
        controllers=ControllersConfig(launch_autoconfig=False),
    )

    monkeypatch.setattr("gamehub_cli.sync.steam_stage.discover_userdata_dir", lambda explicit: Path("userdata"))
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.discover_steam_id", lambda userdata, preferred_steam_id=None: "76561198000000001"
    )
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.build_context", lambda userdata, steam_id, steam_exe: object())
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.is_steam_deck_linux", lambda: False)
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.is_steam_running", lambda: True)
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.close_steam_best_effort", lambda: order.append("close"))
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.wait_for_steam_exit", lambda: order.append("wait") or True)
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.backup_steam_configs", lambda context: order.append("backup") or []
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.upsert_shortcuts",
        lambda context, desired_shortcuts: (
            order.append("shortcuts")
            or type("Result", (), {"app_ids_by_title": {}, "app_ids_by_system": {}, "total_shortcuts": 0})()
        ),
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.update_collections",
        lambda context, app_ids_by_system: order.append("collections") or 0,
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.update_cloud_collections",
        lambda context, app_ids_by_system: order.append("collections-cloud") or 0,
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.copy_grid_art", lambda context, assignments: order.append("art") or []
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.prune_grid_noncanonical_variants",
        lambda context, app_ids: order.append("prune") or 0,
    )
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.reopen_steam", lambda context: order.append("reopen") or True)

    _apply_steam_updates(
        config,
        index=index,
        require_steam_closed=True,
        artwork_by_title={},
    )

    assert order == [
        "close",
        "wait",
        "backup",
        "shortcuts",
        "collections",
        "collections-cloud",
        "art",
        "prune",
        "reopen",
    ]


def test_apply_steam_updates_deck_repairs_steam_input_overrides(monkeypatch) -> None:
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
        controllers=ControllersConfig(launch_autoconfig=False),
    )

    monkeypatch.setattr("gamehub_cli.sync.steam_stage.discover_userdata_dir", lambda explicit: Path("userdata"))
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.discover_steam_id", lambda userdata, preferred_steam_id=None: "76561198000000001"
    )
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.build_context", lambda userdata, steam_id, steam_exe: object())
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.is_steam_running", lambda: False)
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.sys.platform", "linux")
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.is_steam_deck_linux", lambda: True)
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.backup_steam_configs", lambda context: [])
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.apply_deck_steam_input_templates",
        lambda context, index, shortcut_result, overwrite_existing=False: type(
            "TemplateSyncResult",
            (),
            {"targets": 1, "written": 1, "unchanged": 0, "systems_applied": ("Wii",)},
        )(),
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.upsert_shortcuts",
        lambda context, desired_shortcuts: type(
            "Result",
            (),
            {
                "app_ids_by_title": {"title_wii_mario": "-602952253"},
                "app_ids_by_system": {"Wii": ["-602952253"]},
                "total_shortcuts": 1,
            },
        )(),
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.update_collections",
        lambda context, app_ids_by_system: order.append("collections") or 0,
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.update_cloud_collections",
        lambda context, app_ids_by_system: order.append("collections-cloud") or 0,
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.repair_managed_steam_input_overrides",
        lambda context, app_ids, disable_cloud=False, disable_cloud_exclude_app_ids=None: (
            order.append(
                "repair:"
                f"{','.join(app_ids)}:disable_cloud={disable_cloud}:"
                f"exclude={','.join(sorted(disable_cloud_exclude_app_ids or []))}"
            )
            or 1
        ),
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.copy_grid_art",
        lambda context, assignments: order.append("art") or [],
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.prune_grid_noncanonical_variants",
        lambda context, app_ids: order.append("prune") or 0,
    )
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.reopen_steam", lambda context: order.append("reopen") or True)

    _apply_steam_updates(
        config,
        index=index,
        require_steam_closed=False,
        artwork_by_title={},
    )

    assert "collections" in order
    assert "collections-cloud" in order
    assert "repair:-602952253:disable_cloud=True:exclude=" in order


def test_apply_steam_updates_deck_always_repairs_steam_input_overrides(monkeypatch) -> None:
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
        controllers=ControllersConfig(launch_autoconfig=False),
    )

    monkeypatch.setattr("gamehub_cli.sync.steam_stage.discover_userdata_dir", lambda explicit: Path("userdata"))
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.discover_steam_id", lambda userdata, preferred_steam_id=None: "76561198000000001"
    )
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.build_context", lambda userdata, steam_id, steam_exe: object())
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.is_steam_running", lambda: False)
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.sys.platform", "linux")
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.is_steam_deck_linux", lambda: True)
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.backup_steam_configs", lambda context: [])
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.apply_deck_steam_input_templates",
        lambda context, index, shortcut_result, overwrite_existing=False: type(
            "TemplateSyncResult",
            (),
            {"targets": 1, "written": 0, "unchanged": 1, "systems_applied": ("Wii",)},
        )(),
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.upsert_shortcuts",
        lambda context, desired_shortcuts: type(
            "Result",
            (),
            {
                "app_ids_by_title": {"title_wii_mario": "-602952253"},
                "app_ids_by_system": {"Wii": ["-602952253"]},
                "total_shortcuts": 1,
            },
        )(),
    )
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.update_collections", lambda context, app_ids_by_system: 0)
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.update_cloud_collections", lambda context, app_ids_by_system: 0)
    repair_calls: list[str] = []
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.repair_managed_steam_input_overrides",
        lambda context, app_ids, disable_cloud=False, disable_cloud_exclude_app_ids=None: (
            repair_calls.append(",".join(app_ids)) or 1
        ),
    )
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.copy_grid_art", lambda context, assignments: [])
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.prune_grid_noncanonical_variants",
        lambda context, app_ids: 0,
    )
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.reopen_steam", lambda context: True)

    _apply_steam_updates(
        config,
        index=index,
        require_steam_closed=False,
        artwork_by_title={},
    )
    assert repair_calls


def test_apply_steam_updates_deck_runs_template_sync_pass(monkeypatch) -> None:
    order: list[str] = []
    overwrite_flags: list[bool] = []
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
        controllers=ControllersConfig(launch_autoconfig=False),
    )

    monkeypatch.setattr("gamehub_cli.sync.steam_stage.discover_userdata_dir", lambda explicit: Path("userdata"))
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.discover_steam_id", lambda userdata, preferred_steam_id=None: "76561198000000001"
    )
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.build_context", lambda userdata, steam_id, steam_exe: object())
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.is_steam_running", lambda: False)
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.sys.platform", "linux")
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.is_steam_deck_linux", lambda: True)
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.backup_steam_configs", lambda context: [])
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.upsert_shortcuts",
        lambda context, desired_shortcuts: type(
            "Result",
            (),
            {
                "app_ids_by_title": {"title_wii_mario": "-602952253"},
                "app_ids_by_system": {"Wii": ["-602952253"]},
                "total_shortcuts": 1,
            },
        )(),
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.apply_deck_steam_input_templates",
        lambda context, index, shortcut_result, overwrite_existing=False: (
            overwrite_flags.append(overwrite_existing)
            or order.append("template-sync")
            or type(
                "TemplateSyncResult",
                (),
                {"targets": 1, "written": 1, "unchanged": 0, "systems_applied": ("Wii",)},
            )()
        ),
    )
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.update_collections", lambda context, app_ids_by_system: 0)
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.update_cloud_collections", lambda context, app_ids_by_system: 0)
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.repair_managed_steam_input_overrides",
        lambda context, app_ids, disable_cloud=False, disable_cloud_exclude_app_ids=None: 0,
    )
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.copy_grid_art", lambda context, assignments: [])
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.prune_grid_noncanonical_variants", lambda context, app_ids: 0)
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.reopen_steam", lambda context: True)

    _apply_steam_updates(
        config,
        index=index,
        require_steam_closed=False,
        artwork_by_title={},
    )

    assert "template-sync" in order
    assert overwrite_flags == [False]


def test_apply_steam_updates_deck_template_sync_overwrites_when_reseed_enabled(monkeypatch) -> None:
    overwrite_flags: list[bool] = []
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
        controllers=ControllersConfig(launch_autoconfig=False),
    )

    monkeypatch.setattr("gamehub_cli.sync.steam_stage.discover_userdata_dir", lambda explicit: Path("userdata"))
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.discover_steam_id", lambda userdata, preferred_steam_id=None: "76561198000000001"
    )
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.build_context", lambda userdata, steam_id, steam_exe: object())
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.is_steam_running", lambda: False)
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.sys.platform", "linux")
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.is_steam_deck_linux", lambda: True)
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.backup_steam_configs", lambda context: [])
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.upsert_shortcuts",
        lambda context, desired_shortcuts: type(
            "Result",
            (),
            {
                "app_ids_by_title": {"title_wii_mario": "-602952253"},
                "app_ids_by_system": {"Wii": ["-602952253"]},
                "total_shortcuts": 1,
            },
        )(),
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.apply_deck_steam_input_templates",
        lambda context, index, shortcut_result, overwrite_existing=False: (
            overwrite_flags.append(overwrite_existing)
            or type(
                "TemplateSyncResult",
                (),
                {"targets": 1, "written": 1, "unchanged": 0, "systems_applied": ("Wii",)},
            )()
        ),
    )
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.update_collections", lambda context, app_ids_by_system: 0)
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.update_cloud_collections", lambda context, app_ids_by_system: 0)
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.repair_managed_steam_input_overrides",
        lambda context, app_ids, disable_cloud=False, disable_cloud_exclude_app_ids=None: 0,
    )
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.copy_grid_art", lambda context, assignments: [])
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.prune_grid_noncanonical_variants", lambda context, app_ids: 0)
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.reopen_steam", lambda context: True)

    _apply_steam_updates(
        config,
        index=index,
        require_steam_closed=False,
        artwork_by_title={},
        reseed_profiles=True,
    )

    assert overwrite_flags == [True]


def test_apply_steam_updates_deck_always_runs_template_sync(monkeypatch) -> None:
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
        controllers=ControllersConfig(launch_autoconfig=False),
    )

    monkeypatch.setattr("gamehub_cli.sync.steam_stage.discover_userdata_dir", lambda explicit: Path("userdata"))
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.discover_steam_id", lambda userdata, preferred_steam_id=None: "76561198000000001"
    )
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.build_context", lambda userdata, steam_id, steam_exe: object())
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.is_steam_running", lambda: False)
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.sys.platform", "linux")
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.is_steam_deck_linux", lambda: True)
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.backup_steam_configs", lambda context: [])
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.upsert_shortcuts",
        lambda context, desired_shortcuts: type(
            "Result",
            (),
            {
                "app_ids_by_title": {"title_wii_mario": "-602952253"},
                "app_ids_by_system": {"Wii": ["-602952253"]},
                "total_shortcuts": 1,
            },
        )(),
    )
    template_sync_called: list[str] = []
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.apply_deck_steam_input_templates",
        lambda context, index, shortcut_result, overwrite_existing=False: (
            template_sync_called.append("called")
            or type(
                "TemplateSyncResult", (), {"targets": 1, "written": 0, "unchanged": 1, "systems_applied": ("Wii",)}
            )()
        ),
    )
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.update_collections", lambda context, app_ids_by_system: 0)
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.update_cloud_collections", lambda context, app_ids_by_system: 0)
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.repair_managed_steam_input_overrides",
        lambda context, app_ids, disable_cloud=False, disable_cloud_exclude_app_ids=None: 0,
    )
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.copy_grid_art", lambda context, assignments: [])
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.prune_grid_noncanonical_variants", lambda context, app_ids: 0)
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.reopen_steam", lambda context: True)

    _apply_steam_updates(
        config,
        index=index,
        require_steam_closed=False,
        artwork_by_title={},
    )
    assert template_sync_called == ["called"]


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
        controllers=ControllersConfig(launch_autoconfig=False),
    )

    monkeypatch.setattr("gamehub_cli.sync.steam_stage.discover_userdata_dir", lambda explicit: Path("userdata"))
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.discover_steam_id", lambda userdata, preferred_steam_id=None: "76561198000000001"
    )
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.build_context", lambda userdata, steam_id, steam_exe: object())
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.is_steam_deck_linux", lambda: False)
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.is_steam_running", lambda: True)
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.close_steam_best_effort", lambda: order.append("close"))
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.wait_for_steam_exit", lambda: order.append("wait") or False)
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.backup_steam_configs", lambda context: order.append("backup") or []
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.upsert_shortcuts",
        lambda context, desired_shortcuts: (
            order.append("shortcuts")
            or type("Result", (), {"app_ids_by_title": {}, "app_ids_by_system": {}, "total_shortcuts": 0})()
        ),
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.update_collections",
        lambda context, app_ids_by_system: order.append("collections") or 0,
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.update_cloud_collections",
        lambda context, app_ids_by_system: order.append("collections-cloud") or 0,
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.copy_grid_art", lambda context, assignments: order.append("art") or []
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.prune_grid_noncanonical_variants",
        lambda context, app_ids: order.append("prune") or 0,
    )
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.reopen_steam", lambda context: order.append("reopen") or True)

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
        controllers=ControllersConfig(launch_autoconfig=False),
    )

    monkeypatch.setattr("gamehub_cli.sync.steam_stage.discover_userdata_dir", lambda explicit: Path("userdata"))
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.discover_steam_id", lambda userdata, preferred_steam_id=None: "76561198000000001"
    )
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.build_context", lambda userdata, steam_id, steam_exe: object())
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.is_steam_deck_linux", lambda: False)
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.is_steam_running", lambda: False)
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.backup_steam_configs", lambda context: order.append("backup") or []
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.upsert_shortcuts",
        lambda context, desired_shortcuts: (
            order.append("shortcuts")
            or type("Result", (), {"app_ids_by_title": {}, "app_ids_by_system": {}, "total_shortcuts": 0})()
        ),
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.update_collections",
        lambda context, app_ids_by_system: order.append("collections") or 0,
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.update_cloud_collections",
        lambda context, app_ids_by_system: order.append("collections-cloud") or 0,
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.copy_grid_art", lambda context, assignments: order.append("art") or []
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.prune_grid_noncanonical_variants",
        lambda context, app_ids: order.append("prune") or 0,
    )
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.reopen_steam", lambda context: order.append("reopen") or True)

    _apply_steam_updates(
        config,
        index=index,
        require_steam_closed=False,
        artwork_by_title={},
    )

    assert order == ["backup", "shortcuts", "collections", "collections-cloud", "art", "prune", "reopen"]


def test_apply_steam_updates_skip_relaunch_still_updates_steam(monkeypatch, capsys) -> None:
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
        controllers=ControllersConfig(launch_autoconfig=False),
    )

    monkeypatch.setattr("gamehub_cli.sync.steam_stage.discover_userdata_dir", lambda explicit: Path("userdata"))
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.discover_steam_id", lambda userdata, preferred_steam_id=None: "76561198000000001"
    )
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.build_context", lambda userdata, steam_id, steam_exe: object())
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.is_steam_deck_linux", lambda: False)
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.is_steam_running", lambda: False)
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.backup_steam_configs", lambda context: order.append("backup") or []
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.upsert_shortcuts",
        lambda context, desired_shortcuts: (
            order.append("shortcuts")
            or type("Result", (), {"app_ids_by_title": {}, "app_ids_by_system": {}, "total_shortcuts": 0})()
        ),
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.update_collections",
        lambda context, app_ids_by_system: order.append("collections") or 0,
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.update_cloud_collections",
        lambda context, app_ids_by_system: order.append("collections-cloud") or 0,
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.copy_grid_art", lambda context, assignments: order.append("art") or []
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.prune_grid_noncanonical_variants",
        lambda context, app_ids: order.append("prune") or 0,
    )
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.reopen_steam", lambda context: order.append("reopen") or True)

    _apply_steam_updates(
        config,
        index=index,
        require_steam_closed=False,
        artwork_by_title={},
        reopen_steam_after_update=False,
    )

    assert order == ["backup", "shortcuts", "collections", "collections-cloud", "art", "prune"]
    assert "Skipping Steam relaunch (--skip-steam-relaunch)" in capsys.readouterr().out


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
        controllers=ControllersConfig(launch_autoconfig=False),
    )
    steam_called = {"value": False}
    monkeypatch.setattr("gamehub_cli.sync.index.httpx", FakeHttpx)
    monkeypatch.setattr(
        "gamehub_cli.sync.orchestrator._apply_steam_updates",
        lambda _config, index, require_steam_closed, artwork_by_title, reopen_steam_after_update=True, reseed_profiles=False: (
            steam_called.__setitem__("value", True)
        ),
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


def test_run_sync_skip_steam_relaunch_still_applies_steam_updates(monkeypatch) -> None:
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
        state_path=Path(".pytest_tmp_local/state-test-skip-steam-relaunch.json"),
        steam_userdata_dir=Path("userdata"),
        steam_id=None,
        steam_exe=Path("steam.exe"),
        sgdb_api_key=None,
        sgdb_cache_dir=Path("artwork_cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        controllers=ControllersConfig(launch_autoconfig=False),
    )
    received: dict[str, object] = {}
    monkeypatch.setattr("gamehub_cli.sync.index.httpx", FakeHttpx)
    monkeypatch.setattr(
        "gamehub_cli.sync.orchestrator._apply_steam_updates",
        lambda _config, index, require_steam_closed, artwork_by_title, reopen_steam_after_update=True, reseed_profiles=False: (
            received.update({"called": True, "reopen": reopen_steam_after_update, "reseed_profiles": reseed_profiles})
        ),
    )

    exit_code = run_sync(
        config=config,
        dry_run=False,
        verbose=False,
        verify=False,
        require_steam_closed=False,
        skip_steam=False,
        skip_steam_relaunch=True,
    )

    assert exit_code == 0
    assert received.get("called") is True
    assert received.get("reopen") is False
    assert received.get("reseed_profiles") is False


def test_run_sync_reseed_profiles_propagates_to_steam_updates(monkeypatch) -> None:
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
        state_path=Path(".pytest_tmp_local/state-test-reseed-steam-updates.json"),
        steam_userdata_dir=Path("userdata"),
        steam_id=None,
        steam_exe=Path("steam.exe"),
        sgdb_api_key=None,
        sgdb_cache_dir=Path("artwork_cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        controllers=ControllersConfig(launch_autoconfig=False),
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr("gamehub_cli.sync.index.httpx", FakeHttpx)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator.ensure_emulators", lambda **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator.ensure_retroarch_cores", lambda **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator._bootstrap_firmware_dirs", lambda *args, **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator._apply_downloads", lambda *args, **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator.deploy_firmware_to_emulators", lambda *args, **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator._build_artwork_assignments", lambda *args, **kwargs: {})
    monkeypatch.setattr("gamehub_cli.sync.orchestrator._resolve_steam_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "gamehub_cli.sync.orchestrator._apply_steam_updates",
        lambda _config, index, require_steam_closed, artwork_by_title, reopen_steam_after_update=True, reseed_profiles=False: (
            captured.update({"reseed_profiles": reseed_profiles})
        ),
    )

    exit_code = run_sync(
        config=config,
        dry_run=False,
        verbose=False,
        verify=False,
        require_steam_closed=False,
        skip_steam=False,
        reseed_profiles=True,
    )

    assert exit_code == 0
    assert captured.get("reseed_profiles") is True


def test_run_sync_converges_controllers_before_steam_updates(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return

        def json(self) -> dict:
            return {
                "index_version": 1,
                "systems": [],
                "titles": [
                    {
                        "title_id": "title_ps2_gt4",
                        "system": "PS2",
                        "title_name": "Gran Turismo 4",
                        "title_rel_dir": "PS2/Gran Turismo 4.iso",
                        "emulator": "pcsx2",
                        "launch_template": '"{emulator}" "{rom}"',
                        "rom": {
                            "file_id": "rom_ps2_gt4",
                            "rel_path": "roms/PS2/Gran Turismo 4.iso",
                            "sha256": "a" * 64,
                            "size_bytes": 3,
                            "extension": ".iso",
                        },
                        "assets": [],
                    }
                ],
            }

    class FakeHttpx:
        @staticmethod
        def get(_url: str, timeout: float) -> FakeResponse:
            assert timeout > 0
            return FakeResponse()

    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("library"),
        firmware_dir=Path("firmware"),
        state_path=Path(".pytest_tmp_local/state-test-controller-stage-order.json"),
        steam_userdata_dir=Path("userdata"),
        steam_id=None,
        steam_exe=Path("steam.exe"),
        sgdb_api_key=None,
        sgdb_cache_dir=Path("artwork_cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        controllers=ControllersConfig(launch_autoconfig=True),
    )
    order: list[str] = []
    monkeypatch.setattr("gamehub_cli.sync.index.httpx", FakeHttpx)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator.ensure_emulators", lambda **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator.ensure_retroarch_cores", lambda **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator._bootstrap_firmware_dirs", lambda *args, **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator._apply_downloads", lambda *args, **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator.deploy_firmware_to_emulators", lambda *args, **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator._build_artwork_assignments", lambda *args, **kwargs: {})
    monkeypatch.setattr("gamehub_cli.sync.orchestrator._resolve_steam_context", lambda *args, **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator.seed_default_profiles", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "gamehub_cli.sync.orchestrator._converge_controller_state",
        lambda *args, **kwargs: order.append("converge"),
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.orchestrator._apply_steam_updates",
        lambda *args, **kwargs: order.append("steam"),
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
    assert order == ["converge", "steam"]


def test_run_sync_reseed_profiles_forces_defaults(monkeypatch) -> None:
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
        state_path=Path(".pytest_tmp_local/state-test-reseed.json"),
        steam_userdata_dir=None,
        steam_id=None,
        steam_exe=None,
        sgdb_api_key=None,
        sgdb_cache_dir=Path("artwork_cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        controllers=ControllersConfig(launch_autoconfig=True),
    )
    called: dict[str, object] = {}
    monkeypatch.setattr("gamehub_cli.sync.index.httpx", FakeHttpx)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator.ensure_emulators", lambda **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator.ensure_retroarch_cores", lambda **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator._bootstrap_firmware_dirs", lambda *args, **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator._apply_downloads", lambda *args, **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator.deploy_firmware_to_emulators", lambda *args, **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator._build_artwork_assignments", lambda *args, **kwargs: {})
    monkeypatch.setattr("gamehub_cli.sync.orchestrator._resolve_steam_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "gamehub_cli.sync.orchestrator.seed_default_profiles",
        lambda *args, **kwargs: (
            called.update(
                {
                    "force": kwargs.get("force"),
                    "allow_custom": kwargs.get("allow_custom"),
                }
            )
            or []
        ),
    )

    exit_code = run_sync(
        config=config,
        dry_run=False,
        verbose=False,
        verify=False,
        require_steam_closed=False,
        skip_steam=True,
        reseed_profiles=True,
    )

    assert exit_code == 0
    assert called.get("force") is True
    assert called.get("allow_custom") is True


def test_run_sync_profile_seed_allows_configured_profiles_dir(monkeypatch) -> None:
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
        state_path=Path(".pytest_tmp_local/state-test-seed-custom-dir.json"),
        steam_userdata_dir=None,
        steam_id=None,
        steam_exe=None,
        sgdb_api_key=None,
        sgdb_cache_dir=Path("artwork_cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        controllers=ControllersConfig(
            launch_autoconfig=True,
            profiles_dir=Path(".pytest_tmp_local/custom-profiles"),
        ),
    )
    called: dict[str, object] = {}
    monkeypatch.setattr("gamehub_cli.sync.index.httpx", FakeHttpx)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator.ensure_emulators", lambda **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator.ensure_retroarch_cores", lambda **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator._bootstrap_firmware_dirs", lambda *args, **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator._apply_downloads", lambda *args, **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator.deploy_firmware_to_emulators", lambda *args, **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator._build_artwork_assignments", lambda *args, **kwargs: {})
    monkeypatch.setattr("gamehub_cli.sync.orchestrator._resolve_steam_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "gamehub_cli.sync.orchestrator.seed_default_profiles",
        lambda *args, **kwargs: (
            called.update(
                {
                    "force": kwargs.get("force"),
                    "allow_custom": kwargs.get("allow_custom"),
                }
            )
            or []
        ),
    )

    exit_code = run_sync(
        config=config,
        dry_run=False,
        verbose=False,
        verify=False,
        require_steam_closed=False,
        skip_steam=True,
        reseed_profiles=False,
    )

    assert exit_code == 0
    assert called.get("force") is False
    assert called.get("allow_custom") is True


def test_run_sync_skips_profile_seed_when_autoconfig_disabled(monkeypatch) -> None:
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
        state_path=Path(".pytest_tmp_local/state-test-no-seed.json"),
        steam_userdata_dir=None,
        steam_id=None,
        steam_exe=None,
        sgdb_api_key=None,
        sgdb_cache_dir=Path("artwork_cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        controllers=ControllersConfig(launch_autoconfig=False),
    )
    monkeypatch.setattr("gamehub_cli.sync.index.httpx", FakeHttpx)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator.ensure_emulators", lambda **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator.ensure_retroarch_cores", lambda **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator._bootstrap_firmware_dirs", lambda *args, **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator._apply_downloads", lambda *args, **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator.deploy_firmware_to_emulators", lambda *args, **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator._build_artwork_assignments", lambda *args, **kwargs: {})
    monkeypatch.setattr("gamehub_cli.sync.orchestrator._resolve_steam_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "gamehub_cli.sync.orchestrator.seed_default_profiles",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("seed_default_profiles should not be called")),
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


def test_run_sync_retries_index_fetch_after_timeout(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return

        def json(self) -> dict:
            return {"index_version": 1, "systems": [], "titles": []}

    attempts: list[float] = []

    class FakeHttpx:
        @staticmethod
        def get(_url: str, timeout: float) -> FakeResponse:
            attempts.append(timeout)
            if len(attempts) < 3:
                raise TimeoutError("timed out")
            return FakeResponse()

    sleeps: list[float] = []
    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("library"),
        firmware_dir=Path("firmware"),
        state_path=Path(".pytest_tmp_local/state-test-index-retry.json"),
        steam_userdata_dir=Path("userdata"),
        steam_id=None,
        steam_exe=Path("steam.exe"),
        sgdb_api_key=None,
        sgdb_cache_dir=Path("artwork_cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        index_fetch_attempts=3,
        index_retry_backoff_seconds=0.25,
    )
    monkeypatch.setattr("gamehub_cli.sync.index.httpx", FakeHttpx)
    monkeypatch.setattr("gamehub_cli.sync.orchestrator.time.sleep", lambda seconds: sleeps.append(seconds))

    exit_code = run_sync(
        config=config,
        dry_run=True,
        verbose=False,
        verify=False,
        require_steam_closed=False,
        skip_steam=True,
    )

    assert exit_code == 0
    assert len(attempts) == 3
    assert sleeps == [0.25, 0.5]


def test_run_sync_fails_fast_on_non_retryable_index_error(monkeypatch) -> None:
    class FakeHttpx:
        calls = 0

        @staticmethod
        def get(_url: str, timeout: float):
            del timeout
            FakeHttpx.calls += 1
            raise ValueError("bad payload")

    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("library"),
        firmware_dir=Path("firmware"),
        state_path=Path(".pytest_tmp_local/state-test-index-fail-fast.json"),
        steam_userdata_dir=Path("userdata"),
        steam_id=None,
        steam_exe=Path("steam.exe"),
        sgdb_api_key=None,
        sgdb_cache_dir=Path("artwork_cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        index_fetch_attempts=5,
        index_retry_backoff_seconds=0.1,
    )
    monkeypatch.setattr("gamehub_cli.sync.index.httpx", FakeHttpx)
    monkeypatch.setattr(
        "gamehub_cli.sync.orchestrator.time.sleep", lambda seconds: (_ for _ in ()).throw(AssertionError(seconds))
    )

    try:
        run_sync(
            config=config,
            dry_run=True,
            verbose=False,
            verify=False,
            require_steam_closed=False,
            skip_steam=True,
        )
    except ValueError as exc:
        assert "bad payload" in str(exc)
    else:
        raise AssertionError("Expected ValueError for non-retryable index fetch error")

    assert FakeHttpx.calls == 1


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
        controllers=ControllersConfig(launch_autoconfig=False),
    )
    core_args: dict[str, object] = {}
    monkeypatch.setattr("gamehub_cli.sync.index.httpx", FakeHttpx)
    monkeypatch.setattr(
        "gamehub_cli.sync.orchestrator.ensure_retroarch_cores",
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
        controllers=ControllersConfig(launch_autoconfig=False),
    )
    steam_called = {"value": False}
    monkeypatch.setattr("gamehub_cli.sync.index.httpx", FakeHttpx)
    monkeypatch.setattr(
        "gamehub_cli.sync.orchestrator._apply_steam_updates",
        lambda _config, index, require_steam_closed, artwork_by_title, reopen_steam_after_update=True, reseed_profiles=False: (
            steam_called.__setitem__("value", True)
        ),
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
        controllers=ControllersConfig(launch_autoconfig=False),
    )
    monkeypatch.setattr("gamehub_cli.sync.index.httpx", FakeHttpx)
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.discover_userdata_dir", lambda explicit: Path("userdata"))
    monkeypatch.setattr(
        "gamehub_cli.sync.steam_stage.discover_steam_id",
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


def test_bootstrap_firmware_dirs_creates_system_subdirs(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-sync-layout-") as temp_root:
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
            controllers=ControllersConfig(launch_autoconfig=False),
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


def test_bootstrap_firmware_dirs_dry_run_does_not_mutate(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-sync-layout-") as temp_root:
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
            controllers=ControllersConfig(launch_autoconfig=False),
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


def test_build_artwork_assignments_uses_cache_without_api_key(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-sync-art-cache-") as temp_root:
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
            controllers=ControllersConfig(launch_autoconfig=False),
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


def test_build_shortcut_specs_resolves_emulator_path(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-sync-shortcuts-") as temp_root:
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
            controllers=ControllersConfig(launch_autoconfig=False),
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
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_emulator_executable", lambda value: "C:\\RetroArch\\retroarch.exe"
        )

        specs = _build_shortcut_specs(index=index, config=config)

        assert len(specs) == 1
        assert specs[0].exe == '"C:\\RetroArch\\retroarch.exe"'
        assert "-L cores/fceumm_libretro.dll" in specs[0].launch_options


def test_build_shortcut_specs_retroarch_injects_fullscreen_when_missing(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-sync-shortcuts-retroarch-fs-") as temp_root:
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
            controllers=ControllersConfig(launch_autoconfig=False),
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
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_emulator_executable", lambda value: "C:\\RetroArch\\retroarch.exe"
        )

        specs = _build_shortcut_specs(index=index, config=config)

        assert len(specs) == 1
        assert re.search(r"(^|\s)-f(\s|$)", specs[0].launch_options) is not None
        assert len(re.findall(r"(^|\s)-f(\s|$)", specs[0].launch_options)) == 1


def test_build_shortcut_specs_linux_normalizes_retroarch_core_token(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-sync-shortcuts-linux-") as temp_root:
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
            controllers=ControllersConfig(launch_autoconfig=False),
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
                rel_path="roms/NES/Super Mario Bros.nes",
                sha256="a" * 64,
                size_bytes=3,
                extension=".nes",
            ),
            assets=(),
        )
        index = LibraryIndex(index_version=1, systems=(), titles=(title,))
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_emulator_executable",
            lambda value: "/home/deck/.local/share/flatpak/exports/bin/org.libretro.RetroArch",
        )
        monkeypatch.setattr("gamehub_cli.sync.steam_stage.sys.platform", "linux")
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_retroarch_paths",
            lambda **kwargs: type(
                "Paths",
                (),
                {
                    "cores_dir": Path("/var/home/deck/.var/app/org.libretro.RetroArch/config/retroarch/cores"),
                    "info_dir": Path("/var/home/deck/.var/app/org.libretro.RetroArch/config/retroarch/info"),
                },
            )(),
        )

        specs = _build_shortcut_specs(index=index, config=config)

        assert len(specs) == 1
        assert specs[0].exe == "flatpak"
        assert "run --file-forwarding org.libretro.RetroArch" in specs[0].launch_options
        assert "@@" in specs[0].launch_options
        assert ".dll" not in specs[0].launch_options
        assert "fceumm_libretro.so" in specs[0].launch_options
        assert "cores/fceumm_libretro.so" in specs[0].launch_options


def test_build_shortcut_specs_linux_flatpak_pcsx2_uses_file_forwarding(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-sync-shortcuts-linux-ps2-") as temp_root:
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
            controllers=ControllersConfig(launch_autoconfig=False),
        )
        title = TitleEntry(
            title_id="title_ps2_gt4",
            system="PS2",
            title_name="Gran Turismo 4",
            title_rel_dir="PS2/Gran Turismo 4.iso",
            emulator="pcsx2",
            launch_template='"{emulator}" -fullscreen "{rom}"',
            rom=RomSpec(
                file_id="rom_ps2",
                rel_path="roms/PS2/Gran Turismo 4.iso",
                sha256="a" * 64,
                size_bytes=3,
                extension=".iso",
            ),
            assets=(),
        )
        index = LibraryIndex(index_version=1, systems=(), titles=(title,))
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_emulator_executable",
            lambda value: "/home/deck/.local/share/flatpak/exports/bin/net.pcsx2.PCSX2",
        )
        monkeypatch.setattr("gamehub_cli.sync.steam_stage.sys.platform", "linux")
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_rom_destination",
            lambda **kwargs: Path("/var/home/deck/GameHub/roms/PS2/Gran Turismo 4.iso"),
        )

        specs = _build_shortcut_specs(index=index, config=config)

        assert len(specs) == 1
        assert specs[0].exe == "flatpak"
        assert "run --file-forwarding net.pcsx2.PCSX2 -fullscreen -- @@" in specs[0].launch_options
        assert "/var/home/deck/GameHub/roms/PS2/Gran Turismo 4.iso" in specs[0].launch_options


def test_build_shortcut_specs_wraps_pcsx2_when_controller_autoconfig_enabled(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-sync-shortcuts-linux-ps2-wrap-") as temp_root:
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
            controllers=ControllersConfig(launch_autoconfig=True),
            config_path=temp_root / "custom-config.toml",
        )
        title = TitleEntry(
            title_id="title_ps2_gt4",
            system="PS2",
            title_name="Gran Turismo 4",
            title_rel_dir="PS2/Gran Turismo 4.iso",
            emulator="pcsx2",
            launch_template='"{emulator}" -fullscreen "{rom}"',
            rom=RomSpec(
                file_id="rom_ps2",
                rel_path="roms/PS2/Gran Turismo 4.iso",
                sha256="a" * 64,
                size_bytes=3,
                extension=".iso",
            ),
            assets=(),
        )
        index = LibraryIndex(index_version=1, systems=(), titles=(title,))
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_emulator_executable",
            lambda value: "/home/deck/.local/share/flatpak/exports/bin/net.pcsx2.PCSX2",
        )
        monkeypatch.setattr("gamehub_cli.sync.steam_stage.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.sync.steam_stage.sys.executable", "/usr/bin/python3")
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_rom_destination",
            lambda **kwargs: Path("/var/home/deck/GameHub/roms/PS2/Gran Turismo 4.iso"),
        )

        specs = _build_shortcut_specs(index=index, config=config)

        assert len(specs) == 1
        assert _normalize_path_token(specs[0].exe) == "/usr/bin/python3"
        assert specs[0].launch_options.startswith("-m gamehub_cli.main shortcut-launch --payload ")
        assert "shortcut-launch --payload" in specs[0].launch_options
        payload_token = specs[0].launch_options.rsplit(" ", 1)[-1]
        payload = parse_shortcut_payload(payload_token)
        assert payload.emulator == "pcsx2"
        assert payload.config_path == str(temp_root / "custom-config.toml")
        assert payload.target_exe == "flatpak"
        assert "net.pcsx2.PCSX2" in " ".join(payload.target_args)


def test_build_shortcut_specs_wrapper_uses_direct_command_for_frozen_exe(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-sync-shortcuts-win-ps2-wrap-") as temp_root:
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
            controllers=ControllersConfig(launch_autoconfig=True),
        )
        title = TitleEntry(
            title_id="title_ps2_gt4",
            system="PS2",
            title_name="Gran Turismo 4",
            title_rel_dir="PS2/Gran Turismo 4.iso",
            emulator="pcsx2",
            launch_template='"{emulator}" -fullscreen "{rom}"',
            rom=RomSpec(
                file_id="rom_ps2",
                rel_path="roms/PS2/Gran Turismo 4.iso",
                sha256="a" * 64,
                size_bytes=3,
                extension=".iso",
            ),
            assets=(),
        )
        index = LibraryIndex(index_version=1, systems=(), titles=(title,))
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_emulator_executable", lambda value: "C:\\PCSX2\\pcsx2-qt.exe"
        )
        monkeypatch.setattr("gamehub_cli.sync.steam_stage.sys.executable", "C:\\GameHub\\gamehub-windows-amd64.exe")
        monkeypatch.setattr("gamehub_cli.sync.steam_stage.sys.frozen", True, raising=False)

        specs = _build_shortcut_specs(index=index, config=config)

        assert len(specs) == 1
        assert _normalize_path_token(specs[0].exe) == "C:/GameHub/gamehub-windows-amd64.exe"
        assert specs[0].launch_options.startswith("shortcut-launch --payload ")
        payload_token = specs[0].launch_options.rsplit(" ", 1)[-1]
        payload = parse_shortcut_payload(payload_token)
        assert payload.emulator == "pcsx2"
        assert _normalize_path_token(payload.target_exe) == "C:/PCSX2/pcsx2-qt.exe"


def test_build_shortcut_specs_wraps_retroarch_with_controller_autoconfig(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-sync-shortcuts-retroarch-wrap-") as temp_root:
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
            controllers=ControllersConfig(launch_autoconfig=True),
        )
        title = TitleEntry(
            title_id="title_nes_mario",
            system="NES",
            title_name="Super Mario Bros",
            title_rel_dir="NES/Super Mario Bros.nes",
            emulator="retroarch",
            launch_template='"{emulator}" -L cores/fceumm_libretro.dll "{rom}"',
            rom=RomSpec(
                file_id="rom_nes",
                rel_path="roms/NES/Super Mario Bros.nes",
                sha256="a" * 64,
                size_bytes=3,
                extension=".nes",
            ),
            assets=(),
        )
        index = LibraryIndex(index_version=1, systems=(), titles=(title,))
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_emulator_executable", lambda value: "C:\\RetroArch\\retroarch.exe"
        )
        monkeypatch.setattr("gamehub_cli.sync.steam_stage.sys.executable", "C:\\Python\\python.exe")

        specs = _build_shortcut_specs(index=index, config=config)

        assert len(specs) == 1
        assert _normalize_path_token(specs[0].exe) == "C:/Python/python.exe"
        assert specs[0].launch_options.startswith("-m gamehub_cli.main shortcut-launch --payload ")
        payload_token = specs[0].launch_options.rsplit(" ", 1)[-1]
        payload = parse_shortcut_payload(payload_token)
        assert payload.emulator == "retroarch"
        assert _normalize_path_token(payload.target_exe) == "C:/RetroArch/retroarch.exe"


def test_build_shortcut_specs_wraps_retroarch_when_save_sync_enabled(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-sync-shortcuts-retroarch-save-sync-wrap-") as temp_root:
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
            controllers=ControllersConfig(launch_autoconfig=False),
            save_sync=SaveSyncConfig(enabled=True),
        )
        title = TitleEntry(
            title_id="title_gbc_pokemon",
            system="GBC",
            title_name="Pokemon Crystal",
            title_rel_dir="GBC/Pokemon Crystal.gbc",
            emulator="retroarch",
            launch_template='"{emulator}" -L cores/gambatte_libretro.dll "{rom}"',
            rom=RomSpec(
                file_id="rom_gbc",
                rel_path="roms/GBC/Pokemon Crystal.gbc",
                sha256="b" * 64,
                size_bytes=3,
                extension=".gbc",
            ),
            assets=(),
        )
        index = LibraryIndex(index_version=1, systems=(), titles=(title,))
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_emulator_executable", lambda value: "C:\\RetroArch\\retroarch.exe"
        )
        monkeypatch.setattr("gamehub_cli.sync.steam_stage.sys.executable", "C:\\Python\\python.exe")

        specs = _build_shortcut_specs(index=index, config=config)

        assert len(specs) == 1
        assert _normalize_path_token(specs[0].exe) == "C:/Python/python.exe"
        assert specs[0].launch_options.startswith("-m gamehub_cli.main shortcut-launch --payload ")


def test_build_shortcut_specs_windows_azahar_uses_native_launch_template(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-sync-shortcuts-n3ds-win-") as temp_root:
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
            controllers=ControllersConfig(launch_autoconfig=False),
        )
        title = TitleEntry(
            title_id="title_n3ds_pilotwings",
            system="N3DS",
            title_name="Pilotwings Resort",
            title_rel_dir="N3DS/Pilotwings Resort.3ds",
            emulator="azahar",
            launch_template='"{emulator}" "{rom}"',
            rom=RomSpec(
                file_id="rom_n3ds_pilotwings",
                rel_path="roms/N3DS/Pilotwings Resort.3ds",
                sha256="a" * 64,
                size_bytes=3,
                extension=".3ds",
            ),
            assets=(),
        )
        index = LibraryIndex(index_version=1, systems=(), titles=(title,))
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_emulator_executable", lambda value: "C:\\Azahar\\azahar.exe"
        )

        specs = _build_shortcut_specs(index=index, config=config)

        assert len(specs) == 1
        assert specs[0].exe == '"C:\\Azahar\\azahar.exe"'
        assert re.search(r"(^|\s)-f(\s|$)", specs[0].launch_options) is not None
        assert len(re.findall(r"(^|\s)-f(\s|$)", specs[0].launch_options)) == 1
        assert f'"{temp_root / "library" / "roms" / "N3DS" / "Pilotwings Resort.3ds"}"' in specs[0].launch_options


def test_build_shortcut_specs_linux_flatpak_azahar_uses_file_forwarding(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-sync-shortcuts-n3ds-linux-") as temp_root:
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
            controllers=ControllersConfig(launch_autoconfig=False),
        )
        title = TitleEntry(
            title_id="title_n3ds_pilotwings",
            system="N3DS",
            title_name="Pilotwings Resort",
            title_rel_dir="N3DS/Pilotwings Resort.3ds",
            emulator="azahar",
            launch_template='"{emulator}" "{rom}"',
            rom=RomSpec(
                file_id="rom_n3ds_pilotwings",
                rel_path="roms/N3DS/Pilotwings Resort.3ds",
                sha256="a" * 64,
                size_bytes=3,
                extension=".3ds",
            ),
            assets=(),
        )
        index = LibraryIndex(index_version=1, systems=(), titles=(title,))
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_emulator_executable",
            lambda value: "/home/deck/.local/share/flatpak/exports/bin/org.azahar_emu.Azahar",
        )
        monkeypatch.setattr("gamehub_cli.sync.steam_stage.sys.platform", "linux")
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_rom_destination",
            lambda **kwargs: Path("/var/home/deck/GameHub/roms/N3DS/Pilotwings Resort.3ds"),
        )
        monkeypatch.setattr("gamehub_cli.sync.steam_stage.sys.executable", "/usr/bin/python3")

        specs = _build_shortcut_specs(index=index, config=config)

        assert len(specs) == 1
        assert specs[0].exe == '"/usr/bin/python3"'
        assert "-m gamehub_cli.controllers.azahar_exit_hook" in specs[0].launch_options
        assert "--app-id org.azahar_emu.Azahar" in specs[0].launch_options
        assert "/var/home/deck/GameHub/roms/N3DS/Pilotwings Resort.3ds" in specs[0].launch_options


def test_build_shortcut_specs_linux_flatpak_azahar_can_disable_exit_hook(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-sync-shortcuts-n3ds-linux-") as temp_root:
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
            controllers=ControllersConfig(launch_autoconfig=False),
        )
        title = TitleEntry(
            title_id="title_n3ds_pilotwings",
            system="N3DS",
            title_name="Pilotwings Resort",
            title_rel_dir="N3DS/Pilotwings Resort.3ds",
            emulator="azahar",
            launch_template='"{emulator}" "{rom}"',
            rom=RomSpec(
                file_id="rom_n3ds_pilotwings",
                rel_path="roms/N3DS/Pilotwings Resort.3ds",
                sha256="a" * 64,
                size_bytes=3,
                extension=".3ds",
            ),
            assets=(),
        )
        index = LibraryIndex(index_version=1, systems=(), titles=(title,))
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_emulator_executable",
            lambda value: "/home/deck/.local/share/flatpak/exports/bin/org.azahar_emu.Azahar",
        )
        monkeypatch.setattr("gamehub_cli.sync.steam_stage.sys.platform", "linux")
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_rom_destination",
            lambda **kwargs: Path("/var/home/deck/GameHub/roms/N3DS/Pilotwings Resort.3ds"),
        )
        monkeypatch.setenv("GAMEHUB_AZAHAR_LINUX_EXIT_HOOK", "false")

        specs = _build_shortcut_specs(index=index, config=config)

        assert len(specs) == 1
        assert specs[0].exe == "flatpak"
        assert "run --device=all --file-forwarding org.azahar_emu.Azahar -f -- @@" in specs[0].launch_options


def test_build_shortcut_specs_pcsx2_injects_fullscreen_when_missing(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-sync-shortcuts-pcsx2-fs-") as temp_root:
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
            controllers=ControllersConfig(launch_autoconfig=False),
        )
        title = TitleEntry(
            title_id="title_ps2_gt4",
            system="PS2",
            title_name="Gran Turismo 4",
            title_rel_dir="PS2/Gran Turismo 4.iso",
            emulator="pcsx2",
            launch_template='"{emulator}" "{rom}"',
            rom=RomSpec(
                file_id="rom_ps2",
                rel_path="roms/PS2/Gran Turismo 4.iso",
                sha256="a" * 64,
                size_bytes=3,
                extension=".iso",
            ),
            assets=(),
        )
        index = LibraryIndex(index_version=1, systems=(), titles=(title,))
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_emulator_executable", lambda value: "C:\\PCSX2\\pcsx2-qt.exe"
        )

        specs = _build_shortcut_specs(index=index, config=config)

        assert len(specs) == 1
        assert re.search(r"(^|\s)-fullscreen(\s|$)", specs[0].launch_options) is not None
        assert len(re.findall(r"(^|\s)-fullscreen(\s|$)", specs[0].launch_options)) == 1


def test_build_shortcut_specs_uses_title_rom_path_for_all_titles(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-sync-shortcuts-") as temp_root:
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
            controllers=ControllersConfig(launch_autoconfig=False),
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
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_emulator_executable", lambda value: "C:\\RetroArch\\retroarch.exe"
        )

        specs = _build_shortcut_specs(index=index, config=config)

        assert len(specs) == 2
        by_title = {spec.title_name: spec for spec in specs}
        assert (
            str(temp_root / "library" / "roms" / "PSX" / "Crash Team Racing.cue")
            in by_title["Crash Team Racing"].launch_options
        )
        assert (
            str(temp_root / "library" / "roms" / "PS2" / "Gran Turismo 4.bin")
            in by_title["Gran Turismo 4"].launch_options
        )


def test_build_shortcut_specs_uses_configurable_roms_dir_for_all_titles(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-sync-shortcuts-roms-dir-") as temp_root:
        config = GamehubConfig(
            server_url="http://localhost:8000",
            library_dir=temp_root / "library",
            firmware_dir=temp_root / "firmware",
            state_path=temp_root / "state.json",
            roms_dir=temp_root / "sdcard" / "roms",
            steam_userdata_dir=None,
            steam_id=None,
            steam_exe=None,
            sgdb_api_key=None,
            sgdb_cache_dir=temp_root / "cache",
            sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
            controllers=ControllersConfig(launch_autoconfig=False),
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
        title_nes = TitleEntry(
            title_id="title_nes",
            system="NES",
            title_name="Super Mario Bros",
            title_rel_dir="NES/Super Mario Bros.nes",
            emulator="retroarch",
            launch_template='"{emulator}" -L cores/fceumm_libretro.dll "{rom}"',
            rom=RomSpec(
                file_id="rom_nes",
                rel_path="roms/NES/Super Mario Bros.nes",
                sha256="b" * 64,
                size_bytes=3,
                extension=".nes",
            ),
            assets=(),
        )
        index = LibraryIndex(index_version=1, systems=(), titles=(title_psx, title_nes))
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_emulator_executable", lambda value: "C:\\RetroArch\\retroarch.exe"
        )

        specs = _build_shortcut_specs(index=index, config=config)

        assert len(specs) == 2
        by_title = {spec.title_name: spec for spec in specs}
        assert (
            str(temp_root / "sdcard" / "roms" / "PSX" / "Crash Team Racing.cue")
            in by_title["Crash Team Racing"].launch_options
        )
        assert (
            str(temp_root / "sdcard" / "roms" / "NES" / "Super Mario Bros.nes")
            in by_title["Super Mario Bros"].launch_options
        )


def test_build_shortcut_specs_deck_sets_allow_desktop_config_false_by_default(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-sync-shortcuts-deck-policy-") as temp_root:
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
            controllers=ControllersConfig(launch_autoconfig=False),
        )
        title = TitleEntry(
            title_id="title_nes_mario",
            system="NES",
            title_name="Super Mario Bros",
            title_rel_dir="NES/Super Mario Bros.nes",
            emulator="retroarch",
            launch_template='"{emulator}" -L cores/fceumm_libretro.dll "{rom}"',
            rom=RomSpec(
                file_id="rom_nes",
                rel_path="roms/NES/Super Mario Bros.nes",
                sha256="a" * 64,
                size_bytes=3,
                extension=".nes",
            ),
            assets=(),
        )
        index = LibraryIndex(index_version=1, systems=(), titles=(title,))
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_emulator_executable", lambda value: "/usr/bin/retroarch"
        )
        monkeypatch.setattr("gamehub_cli.sync.steam_stage.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.sync.steam_stage.is_steam_deck_linux", lambda: True)

        specs = _build_shortcut_specs(index=index, config=config)

        assert len(specs) == 1
        assert specs[0].allow_desktop_config is False


def test_build_shortcut_specs_non_deck_keeps_allow_desktop_config_unspecified(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-sync-shortcuts-nondeck-policy-") as temp_root:
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
            controllers=ControllersConfig(launch_autoconfig=False),
        )
        title = TitleEntry(
            title_id="title_nes_mario",
            system="NES",
            title_name="Super Mario Bros",
            title_rel_dir="NES/Super Mario Bros.nes",
            emulator="retroarch",
            launch_template='"{emulator}" -L cores/fceumm_libretro.dll "{rom}"',
            rom=RomSpec(
                file_id="rom_nes",
                rel_path="roms/NES/Super Mario Bros.nes",
                sha256="a" * 64,
                size_bytes=3,
                extension=".nes",
            ),
            assets=(),
        )
        index = LibraryIndex(index_version=1, systems=(), titles=(title,))
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_emulator_executable", lambda value: "/usr/bin/retroarch"
        )
        monkeypatch.setattr("gamehub_cli.sync.steam_stage.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.sync.steam_stage.is_steam_deck_linux", lambda: False)

        specs = _build_shortcut_specs(index=index, config=config)

        assert len(specs) == 1
        assert specs[0].allow_desktop_config is None


def test_build_shortcut_specs_deck_wrapped_shortcuts_preserve_allow_desktop_config(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-sync-shortcuts-deck-wrapped-policy-") as temp_root:
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
            controllers=ControllersConfig(launch_autoconfig=True),
        )
        title = TitleEntry(
            title_id="title_ps2_gt4",
            system="PS2",
            title_name="Gran Turismo 4",
            title_rel_dir="PS2/Gran Turismo 4.iso",
            emulator="pcsx2",
            launch_template='"{emulator}" "{rom}"',
            rom=RomSpec(
                file_id="rom_ps2_gt4",
                rel_path="roms/PS2/Gran Turismo 4.iso",
                sha256="a" * 64,
                size_bytes=3,
                extension=".iso",
            ),
            assets=(),
        )
        index = LibraryIndex(index_version=1, systems=(), titles=(title,))
        monkeypatch.setattr("gamehub_cli.sync.steam_stage.resolve_emulator_executable", lambda value: "/usr/bin/pcsx2")
        monkeypatch.setattr("gamehub_cli.sync.steam_stage.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.sync.steam_stage.is_steam_deck_linux", lambda: True)

        specs = _build_shortcut_specs(index=index, config=config)

        assert len(specs) == 1
        assert "shortcut-launch --payload" in specs[0].launch_options
        assert specs[0].allow_desktop_config is False


def test_build_shortcut_specs_allow_desktop_config_env_override(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-sync-shortcuts-allow-desktop-override-") as temp_root:
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
            controllers=ControllersConfig(launch_autoconfig=False),
        )
        title = TitleEntry(
            title_id="title_nes_mario",
            system="NES",
            title_name="Super Mario Bros",
            title_rel_dir="NES/Super Mario Bros.nes",
            emulator="retroarch",
            launch_template='"{emulator}" -L cores/fceumm_libretro.dll "{rom}"',
            rom=RomSpec(
                file_id="rom_nes",
                rel_path="roms/NES/Super Mario Bros.nes",
                sha256="a" * 64,
                size_bytes=3,
                extension=".nes",
            ),
            assets=(),
        )
        index = LibraryIndex(index_version=1, systems=(), titles=(title,))
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_emulator_executable", lambda value: "/usr/bin/retroarch"
        )
        monkeypatch.setattr("gamehub_cli.sync.steam_stage.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.sync.steam_stage.is_steam_deck_linux", lambda: True)
        monkeypatch.setenv("GAMEHUB_STEAM_ALLOW_DESKTOP_CONFIG", "true")

        specs = _build_shortcut_specs(index=index, config=config)

        assert len(specs) == 1
        assert specs[0].allow_desktop_config is True


def test_build_shortcut_specs_dolphin_uses_batch_exec_and_quoted_rvz_path(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-sync-shortcuts-dolphin-") as temp_root:
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
            controllers=ControllersConfig(launch_autoconfig=False),
        )
        title = TitleEntry(
            title_id="title_wii_mg",
            system="Wii",
            title_name="Super Mario Galaxy",
            title_rel_dir="Wii/Super Mario Galaxy.rvz",
            emulator="dolphin",
            launch_template='"{emulator}" -b -e "{rom}"',
            rom=RomSpec(
                file_id="rom_wii_mg",
                rel_path="roms/Wii/Super Mario Galaxy.rvz",
                sha256="a" * 64,
                size_bytes=3,
                extension=".rvz",
            ),
            assets=(),
        )
        index = LibraryIndex(index_version=1, systems=(), titles=(title,))
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_emulator_executable", lambda value: "C:\\Dolphin\\Dolphin.exe"
        )
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_dolphin_runtime_user_dir",
            lambda config=None: temp_root / "Dolphin Emulator" / "User",
        )

        specs = _build_shortcut_specs(index=index, config=config)

        assert len(specs) == 1
        assert specs[0].exe == '"C:\\Dolphin\\Dolphin.exe"'
        assert "-b -u " in specs[0].launch_options
        assert "Dolphin.Display.Fullscreen=True" in specs[0].launch_options
        assert str(temp_root / "Dolphin Emulator" / "User") in specs[0].launch_options
        assert "-e" in specs[0].launch_options
        assert f'"{temp_root / "library" / "roms" / "Wii" / "Super Mario Galaxy.rvz"}"' in specs[0].launch_options


def test_build_shortcut_specs_dolphin_does_not_duplicate_fullscreen_config(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-sync-shortcuts-dolphin-fullscreen-") as temp_root:
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
            controllers=ControllersConfig(launch_autoconfig=False),
        )
        title = TitleEntry(
            title_id="title_gc_double_dash",
            system="GC",
            title_name="Mario Kart Double Dash",
            title_rel_dir="GC/Mario Kart Double Dash.iso",
            emulator="dolphin",
            launch_template='"{emulator}" -b -C Dolphin.Display.Fullscreen=True -e "{rom}"',
            rom=RomSpec(
                file_id="rom_gc_double_dash",
                rel_path="roms/GC/Mario Kart Double Dash.iso",
                sha256="a" * 64,
                size_bytes=3,
                extension=".iso",
            ),
            assets=(),
        )
        index = LibraryIndex(index_version=1, systems=(), titles=(title,))
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_emulator_executable", lambda value: "C:\\Dolphin\\Dolphin.exe"
        )

        specs = _build_shortcut_specs(index=index, config=config)

        assert len(specs) == 1
        assert specs[0].launch_options.count("Dolphin.Display.Fullscreen=True") == 1
        assert " -u " in specs[0].launch_options


def test_build_shortcut_specs_linux_flatpak_dolphin_uses_file_forwarding_and_device_access(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-sync-shortcuts-dolphin-flatpak-") as temp_root:
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
            controllers=ControllersConfig(launch_autoconfig=False),
        )
        title = TitleEntry(
            title_id="title_wii_mg",
            system="Wii",
            title_name="Super Mario Galaxy",
            title_rel_dir="Wii/Super Mario Galaxy.rvz",
            emulator="dolphin",
            launch_template='"{emulator}" -b -e "{rom}"',
            rom=RomSpec(
                file_id="rom_wii_mg",
                rel_path="roms/Wii/Super Mario Galaxy.rvz",
                sha256="a" * 64,
                size_bytes=3,
                extension=".rvz",
            ),
            assets=(),
        )
        index = LibraryIndex(index_version=1, systems=(), titles=(title,))
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_emulator_executable",
            lambda value: "/home/deck/.local/share/flatpak/exports/bin/org.DolphinEmu.dolphin-emu",
        )
        monkeypatch.setattr("gamehub_cli.sync.steam_stage.sys.platform", "linux")
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_rom_destination",
            lambda **kwargs: Path("/var/home/deck/GameHub/roms/Wii/Super Mario Galaxy.rvz"),
        )
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_dolphin_runtime_user_dir",
            lambda config=None: Path("/var/home/deck/.var/app/org.DolphinEmu.dolphin-emu/data/dolphin-emu"),
        )

        specs = _build_shortcut_specs(index=index, config=config)

        assert len(specs) == 1
        assert specs[0].exe == "flatpak"
        assert "run --device=all --file-forwarding org.DolphinEmu.dolphin-emu -b -u " in specs[0].launch_options
        assert "/var/home/deck/.var/app/org.DolphinEmu.dolphin-emu/data/dolphin-emu" in specs[0].launch_options
        assert '-e @@ "/var/home/deck/GameHub/roms/Wii/Super Mario Galaxy.rvz" @@' in specs[0].launch_options


def test_build_shortcut_specs_windows_dolphin_does_not_probe_help_output(monkeypatch, workspace_tempdir) -> None:
    import gamehub_cli.sync.steam_stage as sync_steam_stage

    with workspace_tempdir("gamehub-sync-shortcuts-dolphin-win-probe-") as temp_root:
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
            controllers=ControllersConfig(launch_autoconfig=False),
        )
        title = TitleEntry(
            title_id="title_wii_mg",
            system="Wii",
            title_name="Super Mario Galaxy",
            title_rel_dir="Wii/Super Mario Galaxy.rvz",
            emulator="dolphin",
            launch_template='"{emulator}" -b -e "{rom}"',
            rom=RomSpec(
                file_id="rom_wii_mg",
                rel_path="roms/Wii/Super Mario Galaxy.rvz",
                sha256="a" * 64,
                size_bytes=3,
                extension=".rvz",
            ),
            assets=(),
        )
        index = LibraryIndex(index_version=1, systems=(), titles=(title,))
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_emulator_executable", lambda value: "C:\\Dolphin\\Dolphin.exe"
        )
        monkeypatch.setattr("gamehub_cli.sync.steam_stage.sys.platform", "win32")

        sync_steam_stage._supports_dolphin_inline_config.cache_clear()
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.subprocess.run",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Unexpected Dolphin help probe")),
        )

        specs = _build_shortcut_specs(index=index, config=config)

        assert len(specs) == 1
        assert "Dolphin.Display.Fullscreen=True" in specs[0].launch_options


def test_build_shortcut_specs_dolphin_skips_config_arg_when_parser_is_legacy(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-sync-shortcuts-dolphin-legacy-") as temp_root:
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
            controllers=ControllersConfig(launch_autoconfig=False),
        )
        title = TitleEntry(
            title_id="title_gc_double_dash",
            system="GC",
            title_name="Mario Kart Double Dash",
            title_rel_dir="GC/Mario Kart Double Dash.iso",
            emulator="dolphin",
            launch_template='"{emulator}" -b -C Dolphin.Display.Fullscreen=True -e "{rom}"',
            rom=RomSpec(
                file_id="rom_gc_double_dash",
                rel_path="roms/GC/Mario Kart Double Dash.iso",
                sha256="a" * 64,
                size_bytes=3,
                extension=".iso",
            ),
            assets=(),
        )
        index = LibraryIndex(index_version=1, systems=(), titles=(title,))
        monkeypatch.setattr(
            "gamehub_cli.sync.steam_stage.resolve_emulator_executable", lambda value: "C:\\Dolphin\\Dolphin.exe"
        )
        monkeypatch.setattr("gamehub_cli.sync.steam_stage._supports_dolphin_inline_config", lambda _exe: False)

        specs = _build_shortcut_specs(index=index, config=config)

        assert len(specs) == 1
        assert "Dolphin.Display.Fullscreen=True" not in specs[0].launch_options
        assert "-b -u" in specs[0].launch_options
        assert "-e" in specs[0].launch_options


def test_run_sync_dry_run_executes_save_stage_without_writes(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return

        def json(self) -> dict:
            return {"index_version": 1, "systems": [], "titles": [], "saves": []}

    class FakeHttpx:
        @staticmethod
        def get(_url: str, timeout: float) -> FakeResponse:
            assert timeout > 0
            return FakeResponse()

    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("library"),
        firmware_dir=Path("firmware"),
        state_path=Path(".pytest_tmp_local/state-test-dry-run-save-stage.json"),
        steam_userdata_dir=Path("userdata"),
        steam_id=None,
        steam_exe=Path("steam.exe"),
        sgdb_api_key=None,
        sgdb_cache_dir=Path("artwork_cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        controllers=ControllersConfig(launch_autoconfig=False),
    )
    received: dict[str, object] = {}
    monkeypatch.setattr("gamehub_cli.sync.index.httpx", FakeHttpx)
    monkeypatch.setattr(
        "gamehub_cli.sync.save_stage.apply_save_stage",
        lambda **kwargs: received.update(kwargs),
    )

    exit_code = run_sync(
        config=config,
        dry_run=True,
        verbose=False,
        verify=False,
        require_steam_closed=False,
        skip_steam=True,
    )

    assert exit_code == 0
    assert received["dry_run"] is True


def test_run_sync_save_stage_failure_skips_state_write(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return

        def json(self) -> dict:
            return {"index_version": 1, "systems": [], "titles": [], "saves": []}

    class FakeHttpx:
        @staticmethod
        def get(_url: str, timeout: float) -> FakeResponse:
            assert timeout > 0
            return FakeResponse()

    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("library"),
        firmware_dir=Path("firmware"),
        state_path=Path(".pytest_tmp_local/state-test-save-stage-fail.json"),
        steam_userdata_dir=Path("userdata"),
        steam_id=None,
        steam_exe=Path("steam.exe"),
        sgdb_api_key=None,
        sgdb_cache_dir=Path("artwork_cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        controllers=ControllersConfig(launch_autoconfig=False),
    )
    monkeypatch.setattr("gamehub_cli.sync.index.httpx", FakeHttpx)
    monkeypatch.setattr(
        "gamehub_cli.sync.save_stage.apply_save_stage",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("save transfer failed")),
    )

    with pytest.raises(RuntimeError, match="save transfer failed"):
        run_sync(
            config=config,
            dry_run=False,
            verbose=False,
            verify=False,
            require_steam_closed=False,
            skip_steam=True,
        )

    assert not config.state_path.exists()


def test_apply_save_stage_uploads_and_updates_state(monkeypatch, workspace_tempdir) -> None:
    from gamehub_cli.sync import save_stage

    state = SyncState()
    with workspace_tempdir("gamehub-save-stage-upload-") as temp_root:
        destination = temp_root / "upload.sav"
        destination.write_bytes(b"local-upload")
        plan = SyncPlan(
            save_actions=[
                SavePlanAction(
                    save_id="save_upload",
                    binding_id="savebind_upload",
                    title_id="title_upload",
                    system="N64",
                    kind="battery",
                    decision="upload_existing",
                    reason="local-changed-remote-unchanged",
                    url="/v1/saves/upload",
                    destination=destination,
                    canonical_suffix="upload.sav",
                    expected_sha256="c" * 64,
                    size_bytes=1,
                    remote_updated_at="2026-01-01T00:00:00+00:00",
                )
            ]
        )

        remote_sha = "d" * 64
        upload_calls: list[str] = []

        def _fake_upload(**kwargs) -> dict[str, object]:
            upload_calls.append(kwargs["url"])
            assert kwargs["binding_id"] == "savebind_upload"
            assert kwargs["canonical_suffix"] == "upload.sav"
            assert kwargs["expected_remote_sha256"] == "c" * 64
            return {
                "save_id": "save_upload",
                "title_id": "title_upload",
                "system": "N64",
                "kind": "battery",
                "rel_path": "saves/N64/Example/battery/upload.sav",
                "sha256": remote_sha,
                "size_bytes": 12,
                "updated_at": "2026-01-02T00:00:00+00:00",
                "portable": True,
            }

        monkeypatch.setattr("gamehub_cli.sync.save_stage.upload_file_to_server", _fake_upload)

        result = save_stage.apply_save_stage(
            server_url="http://localhost:8000",
            plan=plan,
            state=state,
            timeout_seconds=20.0,
            dry_run=False,
            verbose=False,
        )

        assert result.uploaded == 1
        assert upload_calls == ["/v1/saves/upload"]
        assert state.save_checksums == {"save_upload": save_stage.local_file_sha256(destination)}
        assert state.save_lineage["save_upload"]["remote_sha256"] == remote_sha
        assert "save_upload" not in state.unresolved_save_conflicts


def test_apply_save_stage_updates_state_only_for_successful_downloads(monkeypatch, workspace_tempdir) -> None:
    from gamehub_cli.sync import save_stage

    state = SyncState()
    with workspace_tempdir("gamehub-save-stage-") as temp_root:
        plan = SyncPlan(
            save_actions=[
                SavePlanAction(
                    save_id="save_a",
                    binding_id="savebind_a",
                    title_id="title_a",
                    system="N64",
                    kind="battery",
                    decision="download",
                    reason="local-missing",
                    url="/v1/saves/a",
                    destination=temp_root / "a.sav",
                    canonical_suffix="a.sav",
                    expected_sha256="a" * 64,
                    size_bytes=1,
                    remote_updated_at="2026-01-01T00:00:00+00:00",
                ),
                SavePlanAction(
                    save_id="save_b",
                    binding_id="savebind_b",
                    title_id="title_b",
                    system="N64",
                    kind="battery",
                    decision="download",
                    reason="local-missing",
                    url="/v1/saves/b",
                    destination=temp_root / "b.sav",
                    canonical_suffix="b.sav",
                    expected_sha256="b" * 64,
                    size_bytes=1,
                    remote_updated_at="2026-01-01T00:00:00+00:00",
                ),
            ]
        )

    calls: list[str] = []

    def _fake_transfer(**kwargs) -> None:
        calls.append(kwargs["url"])
        if kwargs["url"].endswith("/b"):
            raise RuntimeError("boom")

    monkeypatch.setattr("gamehub_cli.sync.save_stage.stream_to_destination_atomic", _fake_transfer)

    with pytest.raises(save_stage.SaveStageError, match="Save sync failed"):
        save_stage.apply_save_stage(
            server_url="http://localhost:8000",
            plan=plan,
            state=state,
            timeout_seconds=20.0,
            dry_run=False,
            verbose=False,
        )

    assert calls == ["/v1/saves/a", "/v1/saves/b"]
    assert state.save_checksums == {"save_a": "a" * 64}
    assert "save_b" not in state.save_checksums
