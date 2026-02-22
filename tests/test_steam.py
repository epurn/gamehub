from __future__ import annotations

import json
import os
import re
from pathlib import Path

import vdf

from gamehub_cli.steam import (
    LINUX_STEAM_PROCESS_NAMES,
    SteamArtworkAssignment,
    SteamContext,
    SteamShortcutSpec,
    backup_steam_configs,
    close_steam_best_effort,
    copy_grid_art,
    discover_steam_id,
    discover_userdata_dir,
    is_steam_running,
    prune_grid_noncanonical_variants,
    reopen_steam,
    steam_id64_from_userdata_id,
    update_cloud_collections,
    update_collections,
    upsert_shortcuts,
    wait_for_steam_exit,
)


def test_discover_steam_id_uses_lowest_numeric_dir(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-steam-") as temp_root:
        (temp_root / "not-a-steamid").mkdir()
        (temp_root / "76561198000000010").mkdir()
        (temp_root / "76561198000000002").mkdir()

        steam_id = discover_steam_id(temp_root)

        assert steam_id == "76561198000000002"


def test_discover_userdata_dir_does_not_fallback_when_explicit_missing(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-steam-") as temp_root:
        existing = temp_root / "detected" / "userdata"
        existing.mkdir(parents=True, exist_ok=True)
        missing = temp_root / "missing" / "userdata"
        monkeypatch.setattr("gamehub_cli.steam.lifecycle._candidate_userdata_dirs", lambda: [existing])

        resolved = discover_userdata_dir(missing)

        assert resolved is None


def test_discover_userdata_dir_uses_explicit_path(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-steam-") as temp_root:
        env_path = temp_root / "env" / "userdata"
        env_path.mkdir(parents=True, exist_ok=True)
        explicit = temp_root / "explicit" / "userdata"
        explicit.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("GAMEHUB_STEAM_USERDATA_DIR", str(env_path))

        resolved = discover_userdata_dir(explicit)

        assert resolved == explicit




def test_candidate_userdata_dirs_include_steam_deck_paths(monkeypatch) -> None:
    from gamehub_cli.steam import lifecycle as steam_lifecycle

    monkeypatch.setattr(steam_lifecycle.Path, "home", staticmethod(lambda: Path("/home/deck")))

    candidates = steam_lifecycle._candidate_userdata_dirs()
    normalized_values = [candidate.as_posix().replace("\\", "/").lower() for candidate in candidates]

    assert any(value.endswith("/home/deck/.steam/root/userdata") for value in normalized_values)
    assert any(value.endswith("/home/deck/.local/share/steam/userdata") for value in normalized_values)
    assert any(
        value.endswith("/home/deck/.var/app/com.valvesoftware.steam/.local/share/steam/userdata")
        for value in normalized_values
    )


def test_discover_steam_id_prefers_most_recent_profile(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-steam-") as temp_root:
        older = temp_root / "76561198000000002"
        newer = temp_root / "76561198000000010"
        (older / "config").mkdir(parents=True, exist_ok=True)
        (newer / "config").mkdir(parents=True, exist_ok=True)
        older_cfg = older / "config" / "localconfig.vdf"
        newer_cfg = newer / "config" / "localconfig.vdf"
        older_cfg.write_text("old", encoding="utf-8")
        newer_cfg.write_text("new", encoding="utf-8")
        os.utime(older_cfg, (1_700_000_000, 1_700_000_000))
        os.utime(newer_cfg, (1_800_000_000, 1_800_000_000))

        steam_id = discover_steam_id(temp_root)

        assert steam_id == "76561198000000010"


def test_discover_steam_id_uses_preferred_when_present(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-steam-") as temp_root:
        (temp_root / "76561198000000010").mkdir()
        (temp_root / "76561198000000002").mkdir()

        steam_id = discover_steam_id(temp_root, preferred_steam_id="76561198000000010")

        assert steam_id == "76561198000000010"


def test_discover_steam_id_accepts_preferred_steamid64(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-steam-") as temp_root:
        account_id = "37747392"
        (temp_root / account_id).mkdir()

        steam_id = discover_steam_id(temp_root, preferred_steam_id="76561197998013120")

        assert steam_id == account_id


def test_discover_steam_id_raises_for_missing_preferred(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-steam-") as temp_root:
        (temp_root / "76561198000000010").mkdir()

        try:
            discover_steam_id(temp_root, preferred_steam_id="76561198000000001")
        except ValueError as exc:
            assert "Configured steam_id was not found" in str(exc)
        else:
            raise AssertionError("Expected ValueError for missing configured steam_id")


def test_steam_id64_from_userdata_id_converts_account_id() -> None:
    assert steam_id64_from_userdata_id("37747392") == "76561197998013120"
    assert steam_id64_from_userdata_id("76561197998013120") == "76561197998013120"


def test_backup_steam_configs_creates_timestamped_files(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-steam-") as temp_root:
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
    monkeypatch.setattr("gamehub_cli.steam.lifecycle.is_steam_running", lambda: next(states))
    monkeypatch.setattr("gamehub_cli.steam.lifecycle.time.sleep", lambda _seconds: None)

    assert wait_for_steam_exit(timeout_seconds=2) is True


def test_is_steam_running_linux_checks_exact_process_names(monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], check: bool, capture_output: bool, text: bool):
        del check, capture_output, text
        commands.append(cmd)
        process_name = cmd[-1]
        return type("Completed", (), {"returncode": 0 if process_name == "steam" else 1, "stdout": ""})()

    monkeypatch.setattr("gamehub_cli.steam.lifecycle.os.name", "posix")
    monkeypatch.setattr("gamehub_cli.steam.lifecycle.subprocess.run", fake_run)

    running = is_steam_running()

    assert running is True
    assert commands[0][:2] == ["pgrep", "-x"]
    assert commands[0][2] in LINUX_STEAM_PROCESS_NAMES


def test_close_steam_best_effort_linux_uses_exact_process_names(monkeypatch) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr("gamehub_cli.steam.lifecycle.os.name", "posix")
    monkeypatch.setattr(
        "gamehub_cli.steam.lifecycle._run_process_best_effort",
        lambda cmd, timeout_seconds=10: commands.append(cmd),
    )

    close_steam_best_effort()

    graceful = commands[: len(LINUX_STEAM_PROCESS_NAMES)]
    forced = commands[len(LINUX_STEAM_PROCESS_NAMES) :]
    assert graceful == [["pkill", "-x", name] for name in LINUX_STEAM_PROCESS_NAMES]
    assert forced == [["pkill", "-9", "-x", name] for name in LINUX_STEAM_PROCESS_NAMES]


def test_copy_grid_art_copies_existing_and_skips_missing(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-steam-") as temp_root:
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

        copied = copy_grid_art(context, assignments)

        copied_names = sorted(path.name for path in copied)
        assert copied_names == ["123456.png", "123456_icon.png", "123456p.png"]


def test_copy_grid_art_prefers_dedicated_landscape_grid_when_present(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-steam-") as temp_root:
        config_dir = temp_root / "userdata" / "76561198000000001" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        source_grid = temp_root / "cache" / "grid.png"
        source_grid_landscape = temp_root / "cache" / "grid_landscape.png"
        source_grid.parent.mkdir(parents=True, exist_ok=True)
        source_grid.write_bytes(b"portrait")
        source_grid_landscape.write_bytes(b"landscape")
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
                assets_by_kind={"grid": source_grid, "grid_landscape": source_grid_landscape},
            )
        ]

        copied = copy_grid_art(context, assignments)

        copied_names = sorted(path.name for path in copied)
        assert copied_names == ["123456.png", "123456p.png"]
        grid_dir = config_dir / "grid"
        assert (grid_dir / "123456p.png").read_bytes() == b"portrait"
        assert (grid_dir / "123456.png").read_bytes() == b"landscape"


def test_upsert_shortcuts_round_trip_and_idempotent(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-steam-") as temp_root:
        config_dir = temp_root / "userdata" / "76561198000000001" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        context = SteamContext(
            userdata_dir=temp_root / "userdata",
            steam_id="76561198000000001",
            shortcuts_path=config_dir / "shortcuts.vdf",
            localconfig_path=config_dir / "localconfig.vdf",
            steam_exe=None,
        )
        unmanaged = {
            "AppName": "Manual Shortcut",
            "Exe": "C:\\manual.exe",
            "LaunchOptions": "",
            "tags": {"0": "Manual"},
        }
        context.shortcuts_path.write_bytes(vdf.binary_dumps({"shortcuts": {"0": unmanaged}}))
        desired = [
            SteamShortcutSpec(
                title_id="title_nes_mario",
                system="NES",
                title_name="Super Mario Bros",
                exe="retroarch.exe",
                launch_options='"roms\\NES\\SuperMarioBros.nes"',
                start_dir="C:\\Emulators",
                icon_path="",
            )
        ]

        first = upsert_shortcuts(context, desired)
        second = upsert_shortcuts(context, desired)

        assert first.total_shortcuts == 2
        assert second.total_shortcuts == 2
        assert first.app_ids_by_title["title_nes_mario"] == second.app_ids_by_title["title_nes_mario"]
        persisted = vdf.binary_loads(context.shortcuts_path.read_bytes())
        table = persisted["shortcuts"]
        names = sorted(str(entry.get("AppName", "")) for entry in table.values())
        assert names == ["Manual Shortcut", "Super Mario Bros"]
        managed_entry = next(entry for entry in table.values() if entry.get("AppName") == "Super Mario Bros")
        assert str(managed_entry.get("appid", "")).lstrip("-").isdigit()


def test_upsert_shortcuts_migrates_legacy_matching_entry(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-steam-") as temp_root:
        config_dir = temp_root / "userdata" / "76561198000000001" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        context = SteamContext(
            userdata_dir=temp_root / "userdata",
            steam_id="76561198000000001",
            shortcuts_path=config_dir / "shortcuts.vdf",
            localconfig_path=config_dir / "localconfig.vdf",
            steam_exe=None,
        )
        legacy = {
            "AppName": "Super Mario Bros",
            "Exe": '"retroarch"',
            "LaunchOptions": '-L cores/fceumm_libretro.dll "D:\\GamehubOutput\\roms\\NES\\Super Mario Bros.nes"',
            "tags": {},
        }
        context.shortcuts_path.write_bytes(vdf.binary_dumps({"shortcuts": {"0": legacy}}))
        desired = [
            SteamShortcutSpec(
                title_id="title_nes_mario",
                system="NES",
                title_name="Super Mario Bros",
                exe='"C:\\RetroArch\\retroarch.exe"',
                launch_options='-L cores/fceumm_libretro.dll "D:\\GamehubOutput\\roms\\NES\\Super Mario Bros.nes"',
                start_dir="C:\\RetroArch",
                icon_path="",
            )
        ]

        result = upsert_shortcuts(context, desired)

        assert result.total_shortcuts == 1
        payload = vdf.binary_loads(context.shortcuts_path.read_bytes())
        entry = next(iter(payload["shortcuts"].values()))
        assert entry.get("Exe") == '"C:\\RetroArch\\retroarch.exe"'
        tags = entry.get("tags", {})
        tag_values = [tags[key] for key in sorted(tags, key=lambda k: int(str(k)) if str(k).isdigit() else str(k))]
        assert "GAMEHUB" in tag_values
        assert "GAMEHUB_TITLE:title_nes_mario" in tag_values
        assert "NES" in tag_values


def test_upsert_shortcuts_migrates_legacy_entry_when_launch_options_changed(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-steam-") as temp_root:
        config_dir = temp_root / "userdata" / "76561198000000001" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        context = SteamContext(
            userdata_dir=temp_root / "userdata",
            steam_id="76561198000000001",
            shortcuts_path=config_dir / "shortcuts.vdf",
            localconfig_path=config_dir / "localconfig.vdf",
            steam_exe=None,
        )
        legacy = {
            "AppName": "Crash Team Racing",
            "Exe": '"retroarch"',
            "LaunchOptions": '-L cores/swanstation_libretro.dll "D:\\Old\\Crash Team Racing.bin"',
            "tags": {},
        }
        context.shortcuts_path.write_bytes(vdf.binary_dumps({"shortcuts": {"0": legacy}}))
        desired = [
            SteamShortcutSpec(
                title_id="title_psx_ctr",
                system="PSX",
                title_name="Crash Team Racing",
                exe='"C:\\RetroArch\\retroarch.exe"',
                launch_options='-L cores/swanstation_libretro.dll "D:\\GamehubOutput\\roms\\PSX\\Crash Team Racing.cue"',
                start_dir="C:\\RetroArch",
                icon_path="",
            )
        ]

        result = upsert_shortcuts(context, desired)

        assert result.total_shortcuts == 1
        payload = vdf.binary_loads(context.shortcuts_path.read_bytes())
        entry = next(iter(payload["shortcuts"].values()))
        assert entry.get("Exe") == '"C:\\RetroArch\\retroarch.exe"'
        assert entry.get("LaunchOptions") == desired[0].launch_options
        tags = entry.get("tags", {})
        tag_values = [tags[key] for key in sorted(tags, key=lambda k: int(str(k)) if str(k).isdigit() else str(k))]
        assert "GAMEHUB_TITLE:title_psx_ctr" in tag_values


def test_upsert_shortcuts_migrates_legacy_entry_when_emulator_family_changes(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-steam-") as temp_root:
        config_dir = temp_root / "userdata" / "76561198000000001" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        context = SteamContext(
            userdata_dir=temp_root / "userdata",
            steam_id="76561198000000001",
            shortcuts_path=config_dir / "shortcuts.vdf",
            localconfig_path=config_dir / "localconfig.vdf",
            steam_exe=None,
        )
        legacy = {
            "AppName": "Torino 2006",
            "Exe": '"retroarch"',
            "LaunchOptions": '-L cores/swanstation_libretro.dll "D:\\GameHub\\roms\\PS2\\Torino 2006.chd"',
            "tags": {},
        }
        context.shortcuts_path.write_bytes(vdf.binary_dumps({"shortcuts": {"0": legacy}}))
        desired = [
            SteamShortcutSpec(
                title_id="title_ps2_torino_2006",
                system="PS2",
                title_name="Torino 2006",
                exe="flatpak",
                launch_options='run --file-forwarding net.pcsx2.PCSX2 -fullscreen -- @@ "/var/home/epurn/GameHub/roms/PS2/Torino 2006.chd" @@',
                start_dir="",
                icon_path="",
            )
        ]

        result = upsert_shortcuts(context, desired)

        assert result.total_shortcuts == 1
        payload = vdf.binary_loads(context.shortcuts_path.read_bytes())
        entry = next(iter(payload["shortcuts"].values()))
        assert entry.get("Exe") == "flatpak"
        assert entry.get("LaunchOptions") == desired[0].launch_options
        tags = entry.get("tags", {})
        tag_values = [tags[key] for key in sorted(tags, key=lambda k: int(str(k)) if str(k).isdigit() else str(k))]
        assert "GAMEHUB_TITLE:title_ps2_torino_2006" in tag_values


def test_update_collections_preserves_unmanaged_and_is_idempotent(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-steam-") as temp_root:
        config_dir = temp_root / "userdata" / "76561198000000001" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        context = SteamContext(
            userdata_dir=temp_root / "userdata",
            steam_id="76561198000000001",
            shortcuts_path=config_dir / "shortcuts.vdf",
            localconfig_path=config_dir / "localconfig.vdf",
            steam_exe=None,
        )
        initial_collections = {"collections": [{"name": "Manual", "added": ["123"], "removed": []}]}
        context.localconfig_path.write_text(
            vdf.dumps({"UserLocalConfigStore": {"user-collections": json.dumps(initial_collections)}}),
            encoding="utf-8",
        )

        changed_first = update_collections(context, {"NES": ["100", "200"], "PSX": ["300"]})
        changed_second = update_collections(context, {"NES": ["100", "200"], "PSX": ["300"]})

        assert changed_first > 0
        assert changed_second == 0
        payload = vdf.loads(context.localconfig_path.read_text(encoding="utf-8"))
        encoded = payload["UserLocalConfigStore"]["WebStorage"]["user-collections"]
        collections = json.loads(encoded)["collections"]
        names = sorted(item["name"] for item in collections if isinstance(item, dict))
        assert names == ["Manual", "NES", "PSX"]
        managed = [item for item in collections if isinstance(item, dict) and item.get("gamehub_managed")]
        assert sorted(item["name"] for item in managed) == ["NES", "PSX"]


def test_update_collections_skips_noop_write(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-steam-") as temp_root:
        config_dir = temp_root / "userdata" / "76561198000000001" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        context = SteamContext(
            userdata_dir=temp_root / "userdata",
            steam_id="76561198000000001",
            shortcuts_path=config_dir / "shortcuts.vdf",
            localconfig_path=config_dir / "localconfig.vdf",
            steam_exe=None,
        )
        initial_collections = {"collections": [{"name": "NES", "added": [100], "removed": [], "gamehub_managed": True}]}
        context.localconfig_path.write_text(
            vdf.dumps({"UserLocalConfigStore": {"WebStorage": {"user-collections": json.dumps(initial_collections)}}}),
            encoding="utf-8",
        )

        writes: list[str] = []
        monkeypatch.setattr(
            "gamehub_cli.steam.collections._atomic_write_text", lambda path, payload: writes.append(payload)
        )

        changed = update_collections(context, {"NES": ["100"]})

        assert changed == 0
        assert writes == []


def test_upsert_shortcuts_uses_persisted_appid_for_mapping(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-steam-") as temp_root:
        config_dir = temp_root / "userdata" / "76561198000000001" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        context = SteamContext(
            userdata_dir=temp_root / "userdata",
            steam_id="76561198000000001",
            shortcuts_path=config_dir / "shortcuts.vdf",
            localconfig_path=config_dir / "localconfig.vdf",
            steam_exe=None,
        )
        existing = {
            "AppName": "Ape Escape",
            "Exe": '"C:\\RetroArch\\retroarch.exe"',
            "LaunchOptions": '-f -L cores/swanstation_libretro.dll "D:\\GamehubOutput\\roms\\PSX\\Ape Escape.chd"',
            "appid": "-602952253",
            "tags": {
                "0": "GAMEHUB",
                "1": "GAMEHUB_TITLE:title_psx_ape_escape",
                "2": "GAMEHUB_SYSTEM:PSX",
                "3": "PSX",
            },
        }
        context.shortcuts_path.write_bytes(vdf.binary_dumps({"shortcuts": {"0": existing}}))

        desired = [
            SteamShortcutSpec(
                title_id="title_psx_ape_escape",
                system="PSX",
                title_name="Ape Escape",
                exe='"C:\\RetroArch\\retroarch.exe"',
                launch_options='-f -L cores/swanstation_libretro.dll "D:\\GamehubOutput\\roms\\PSX\\Ape Escape.chd"',
                start_dir="C:\\RetroArch",
                icon_path="",
            )
        ]

        result = upsert_shortcuts(context, desired)

        assert result.app_ids_by_title["title_psx_ape_escape"] == "-602952253"
        assert result.app_ids_by_system["PSX"] == ["-602952253"]


def test_update_collections_creates_canonical_webstorage_path_when_missing(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-steam-") as temp_root:
        config_dir = temp_root / "userdata" / "76561198000000001" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        context = SteamContext(
            userdata_dir=temp_root / "userdata",
            steam_id="76561198000000001",
            shortcuts_path=config_dir / "shortcuts.vdf",
            localconfig_path=config_dir / "localconfig.vdf",
            steam_exe=None,
        )
        context.localconfig_path.write_text(vdf.dumps({"UserLocalConfigStore": {}}), encoding="utf-8")

        changed = update_collections(context, {"PSX": ["100"]})

        assert changed > 0
        payload = vdf.loads(context.localconfig_path.read_text(encoding="utf-8"))
        encoded = payload["UserLocalConfigStore"]["WebStorage"]["user-collections"]
        parsed = json.loads(encoded)
        names = sorted(item["name"] for item in parsed["collections"] if isinstance(item, dict))
        assert names == ["PSX"]


def test_update_collections_normalizes_added_appids_to_unsigned(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-steam-") as temp_root:
        config_dir = temp_root / "userdata" / "76561198000000001" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        context = SteamContext(
            userdata_dir=temp_root / "userdata",
            steam_id="76561198000000001",
            shortcuts_path=config_dir / "shortcuts.vdf",
            localconfig_path=config_dir / "localconfig.vdf",
            steam_exe=None,
        )
        context.localconfig_path.write_text(vdf.dumps({"UserLocalConfigStore": {}}), encoding="utf-8")

        update_collections(context, {"PSX": ["-602952253"]})

        payload = vdf.loads(context.localconfig_path.read_text(encoding="utf-8"))
        encoded = payload["UserLocalConfigStore"]["WebStorage"]["user-collections"]
        parsed = json.loads(encoded)
        collections = parsed["collections"]
        psx = next(item for item in collections if isinstance(item, dict) and item.get("name") == "PSX")
        assert psx["added"] == [3692015043]


def test_update_collections_preserves_list_json_shape(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-steam-") as temp_root:
        config_dir = temp_root / "userdata" / "76561198000000001" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        context = SteamContext(
            userdata_dir=temp_root / "userdata",
            steam_id="76561198000000001",
            shortcuts_path=config_dir / "shortcuts.vdf",
            localconfig_path=config_dir / "localconfig.vdf",
            steam_exe=None,
        )
        initial_collections = [{"name": "Manual", "added": ["123"], "removed": []}]
        context.localconfig_path.write_text(
            vdf.dumps({"UserLocalConfigStore": {"user-collections": json.dumps(initial_collections)}}),
            encoding="utf-8",
        )

        changed = update_collections(context, {"NES": ["100"]})

        assert changed > 0
        payload = vdf.loads(context.localconfig_path.read_text(encoding="utf-8"))
        encoded = payload["UserLocalConfigStore"]["WebStorage"]["user-collections"]
        parsed = json.loads(encoded)
        assert isinstance(parsed, list)
        names = sorted(item["name"] for item in parsed if isinstance(item, dict))
        assert names == ["Manual", "NES"]


def test_update_cloud_collections_preserves_unmanaged_and_is_idempotent(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-steam-") as temp_root:
        config_dir = temp_root / "userdata" / "76561198000000001" / "config"
        cloud_path = config_dir / "cloudstorage" / "cloud-storage-namespace-1.json"
        cloud_path.parent.mkdir(parents=True, exist_ok=True)
        context = SteamContext(
            userdata_dir=temp_root / "userdata",
            steam_id="76561198000000001",
            shortcuts_path=config_dir / "shortcuts.vdf",
            localconfig_path=config_dir / "localconfig.vdf",
            steam_exe=None,
            cloudstorage_path=cloud_path,
        )
        cloud_path.write_text(
            json.dumps(
                [
                    [
                        "user-collections.favorite",
                        {"key": "user-collections.favorite", "timestamp": 10, "value": "{}", "version": "10"},
                    ],
                    [
                        "user-collections.gamehub-old",
                        {"key": "user-collections.gamehub-old", "timestamp": 11, "value": "{}", "version": "11"},
                    ],
                ]
            ),
            encoding="utf-8",
        )

        changed_first = update_cloud_collections(context, {"NES": ["-602952253"], "PSX": ["300"]})
        changed_second = update_cloud_collections(context, {"NES": ["-602952253"], "PSX": ["300"]})

        assert changed_first >= 3
        assert changed_second == 0
        entries = json.loads(cloud_path.read_text(encoding="utf-8"))
        payload_by_key = {entry[0]: entry[1] for entry in entries if isinstance(entry, list) and len(entry) == 2}
        assert "user-collections.favorite" in payload_by_key
        assert payload_by_key["user-collections.favorite"]["version"] == "10"

        nes_key = "user-collections.gamehub-nes"
        psx_key = "user-collections.gamehub-psx"
        stale_key = "user-collections.gamehub-old"
        assert nes_key in payload_by_key
        assert psx_key in payload_by_key
        assert payload_by_key[stale_key].get("is_deleted") is True

        nes_value = json.loads(payload_by_key[nes_key]["value"])
        psx_value = json.loads(payload_by_key[psx_key]["value"])
        assert nes_value["name"] == "NES"
        assert psx_value["name"] == "PSX"
        assert nes_value["added"] == [3692015043]
        assert psx_value["added"] == [300]


def test_update_cloud_collections_returns_zero_without_path(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-steam-") as temp_root:
        config_dir = temp_root / "userdata" / "76561198000000001" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        context = SteamContext(
            userdata_dir=temp_root / "userdata",
            steam_id="76561198000000001",
            shortcuts_path=config_dir / "shortcuts.vdf",
            localconfig_path=config_dir / "localconfig.vdf",
            steam_exe=None,
            cloudstorage_path=None,
        )

        changed = update_cloud_collections(context, {"NES": ["100"]})

        assert changed == 0


def test_prune_grid_noncanonical_variants_removes_signed_when_unsigned_exists(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-steam-") as temp_root:
        config_dir = temp_root / "userdata" / "76561198000000001" / "config"
        grid_dir = config_dir / "grid"
        grid_dir.mkdir(parents=True, exist_ok=True)
        context = SteamContext(
            userdata_dir=temp_root / "userdata",
            steam_id="76561198000000001",
            shortcuts_path=config_dir / "shortcuts.vdf",
            localconfig_path=config_dir / "localconfig.vdf",
            steam_exe=None,
        )
        (grid_dir / "-602952253p.png").write_bytes(b"grid")
        (grid_dir / "3692015043p.png").write_bytes(b"grid")

        removed = prune_grid_noncanonical_variants(context, ["-602952253"])

        assert removed in {0, 1}
        assert (grid_dir / "3692015043p.png").exists()


def test_reopen_steam_linux_uses_steam_command(monkeypatch) -> None:
    launched: list[tuple[list[str], dict]] = []
    monkeypatch.setattr("gamehub_cli.steam.lifecycle.os.name", "posix")
    monkeypatch.setattr("gamehub_cli.steam.lifecycle._wait_for_steam_start", lambda timeout_seconds=12.0: True)
    monkeypatch.setattr(
        "gamehub_cli.steam.lifecycle.shutil.which",
        lambda command: "/usr/bin/steam" if command == "steam" else None,
    )
    monkeypatch.setattr(
        "gamehub_cli.steam.lifecycle.subprocess.Popen",
        lambda command, **kwargs: launched.append((command, kwargs)),
    )
    context = SteamContext(
        userdata_dir=Path("userdata"),
        steam_id="76561198000000001",
        shortcuts_path=Path("shortcuts.vdf"),
        localconfig_path=Path("localconfig.vdf"),
        steam_exe=None,
    )

    reopened = reopen_steam(context)

    assert launched[0][0] == ["steam", "steam://open/main"]
    assert launched[0][1]["stdout"] is not None
    assert launched[0][1]["stderr"] is not None
    assert reopened is True


def test_reopen_steam_linux_returns_false_when_no_launcher_available(monkeypatch) -> None:
    monkeypatch.setattr("gamehub_cli.steam.lifecycle.os.name", "posix")
    monkeypatch.setattr("gamehub_cli.steam.lifecycle._wait_for_steam_start", lambda timeout_seconds=12.0: False)
    monkeypatch.setattr("gamehub_cli.steam.lifecycle.shutil.which", lambda command: None)
    context = SteamContext(
        userdata_dir=Path("userdata"),
        steam_id="76561198000000001",
        shortcuts_path=Path("shortcuts.vdf"),
        localconfig_path=Path("localconfig.vdf"),
        steam_exe=None,
    )

    reopened = reopen_steam(context)

    assert reopened is False
