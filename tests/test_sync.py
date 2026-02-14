from __future__ import annotations

from pathlib import Path

from gamehub_cli.config import GamehubConfig
from gamehub_cli.planner import PlanAction, SyncPlan
from gamehub_cli.state import SyncState
from gamehub_cli.sync import _apply_downloads, _apply_steam_updates, run_sync


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
    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("library"),
        firmware_dir=Path("firmware"),
        state_path=Path("state.json"),
        steam_userdata_dir=Path("userdata"),
        steam_exe=Path("steam.exe"),
        sgdb_api_key=None,
        sgdb_cache_dir=Path("artwork_cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
    )

    monkeypatch.setattr("gamehub_cli.sync.discover_userdata_dir", lambda explicit: Path("userdata"))
    monkeypatch.setattr("gamehub_cli.sync.discover_steam_id", lambda userdata: "76561198000000001")
    monkeypatch.setattr("gamehub_cli.sync.build_context", lambda userdata, steam_id, steam_exe: object())
    monkeypatch.setattr("gamehub_cli.sync.is_steam_running", lambda: True)
    monkeypatch.setattr("gamehub_cli.sync.close_steam_best_effort", lambda: order.append("close"))
    monkeypatch.setattr("gamehub_cli.sync.wait_for_steam_exit", lambda: order.append("wait") or True)
    monkeypatch.setattr("gamehub_cli.sync.backup_steam_configs", lambda context: order.append("backup") or [])
    monkeypatch.setattr("gamehub_cli.sync.upsert_shortcuts_placeholder", lambda: order.append("shortcuts"))
    monkeypatch.setattr("gamehub_cli.sync.update_collections_placeholder", lambda: order.append("collections"))
    monkeypatch.setattr("gamehub_cli.sync.copy_grid_art_placeholder", lambda context, assignments: order.append("art") or [])
    monkeypatch.setattr("gamehub_cli.sync.reopen_steam", lambda context: order.append("reopen"))

    _apply_steam_updates(config, require_steam_closed=True, artwork_assignments=[])

    assert order == ["close", "wait", "backup", "shortcuts", "collections", "art", "reopen"]


def test_apply_steam_updates_skips_when_steam_cannot_close(monkeypatch, capsys) -> None:
    order: list[str] = []
    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("library"),
        firmware_dir=Path("firmware"),
        state_path=Path("state.json"),
        steam_userdata_dir=Path("userdata"),
        steam_exe=Path("steam.exe"),
        sgdb_api_key=None,
        sgdb_cache_dir=Path("artwork_cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
    )

    monkeypatch.setattr("gamehub_cli.sync.discover_userdata_dir", lambda explicit: Path("userdata"))
    monkeypatch.setattr("gamehub_cli.sync.discover_steam_id", lambda userdata: "76561198000000001")
    monkeypatch.setattr("gamehub_cli.sync.build_context", lambda userdata, steam_id, steam_exe: object())
    monkeypatch.setattr("gamehub_cli.sync.is_steam_running", lambda: True)
    monkeypatch.setattr("gamehub_cli.sync.close_steam_best_effort", lambda: order.append("close"))
    monkeypatch.setattr("gamehub_cli.sync.wait_for_steam_exit", lambda: order.append("wait") or False)
    monkeypatch.setattr("gamehub_cli.sync.backup_steam_configs", lambda context: order.append("backup") or [])
    monkeypatch.setattr("gamehub_cli.sync.upsert_shortcuts_placeholder", lambda: order.append("shortcuts"))
    monkeypatch.setattr("gamehub_cli.sync.update_collections_placeholder", lambda: order.append("collections"))
    monkeypatch.setattr("gamehub_cli.sync.copy_grid_art_placeholder", lambda context, assignments: order.append("art") or [])
    monkeypatch.setattr("gamehub_cli.sync.reopen_steam", lambda context: order.append("reopen"))

    _apply_steam_updates(config, require_steam_closed=False, artwork_assignments=[])

    assert order == ["close", "wait"]
    assert "Steam is still running after close attempt; skipping Steam updates for safety" in capsys.readouterr().out


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
        steam_exe=Path("steam.exe"),
        sgdb_api_key=None,
        sgdb_cache_dir=Path("artwork_cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
    )
    steam_called = {"value": False}
    monkeypatch.setattr("gamehub_cli.sync.httpx", FakeHttpx)
    monkeypatch.setattr(
        "gamehub_cli.sync._apply_steam_updates",
        lambda _config, require_steam_closed, artwork_assignments: steam_called.__setitem__("value", True),
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
