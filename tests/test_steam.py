from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import re
import shutil
from uuid import uuid4

from gamehub_cli.steam import (
    SteamContext,
    SteamArtworkAssignment,
    backup_steam_configs,
    copy_grid_art_placeholder,
    discover_steam_id,
    wait_for_steam_exit,
)


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


def test_discover_steam_id_uses_lowest_numeric_dir() -> None:
    with _workspace_tempdir("gamehub-steam-") as temp_root:
        (temp_root / "not-a-steamid").mkdir()
        (temp_root / "76561198000000010").mkdir()
        (temp_root / "76561198000000002").mkdir()

        steam_id = discover_steam_id(temp_root)

        assert steam_id == "76561198000000002"


def test_backup_steam_configs_creates_timestamped_files() -> None:
    with _workspace_tempdir("gamehub-steam-") as temp_root:
        config_dir = temp_root / "userdata" / "76561198000000001" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        shortcuts = config_dir / "shortcuts.vdf"
        localconfig = config_dir / "localconfig.vdf"
        shortcuts.write_bytes(b"shortcuts")
        localconfig.write_bytes(b"localconfig")
        context = SteamContext(
            userdata_dir=temp_root / "userdata",
            steam_id="76561198000000001",
            shortcuts_path=shortcuts,
            localconfig_path=localconfig,
            steam_exe=None,
        )

        backups = backup_steam_configs(context)

        assert len(backups) == 2
        for backup_path in backups:
            assert backup_path.exists()
            assert re.match(r".+\.\d{14}\.bak$", backup_path.name)


def test_wait_for_steam_exit_returns_true_when_process_stops(monkeypatch) -> None:
    states = iter([True, True, False])
    monkeypatch.setattr("gamehub_cli.steam.is_steam_running", lambda: next(states))
    monkeypatch.setattr("gamehub_cli.steam.time.sleep", lambda _seconds: None)

    assert wait_for_steam_exit(timeout_seconds=2) is True


def test_copy_grid_art_placeholder_copies_existing_and_skips_missing() -> None:
    with _workspace_tempdir("gamehub-steam-") as temp_root:
        config_dir = temp_root / "userdata" / "76561198000000001" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        source_grid = temp_root / "cache" / "grid.png"
        source_grid.parent.mkdir(parents=True, exist_ok=True)
        source_grid.write_bytes(b"grid")
        source_icon = temp_root / "cache" / "icon.png"
        source_icon.write_bytes(b"icon")
        missing_hero = temp_root / "cache" / "missing_hero.png"
        context = SteamContext(
            userdata_dir=temp_root / "userdata",
            steam_id="76561198000000001",
            shortcuts_path=config_dir / "shortcuts.vdf",
            localconfig_path=config_dir / "localconfig.vdf",
            steam_exe=None,
        )
        assignments = [
            SteamArtworkAssignment(
                steam_app_id="123456",
                assets_by_kind={"grid": source_grid, "hero": missing_hero, "icon": source_icon},
            )
        ]

        copied = copy_grid_art_placeholder(context, assignments)

        copied_names = sorted(path.name for path in copied)
        assert copied_names == ["123456_icon.png", "123456p.png"]
