from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
from uuid import uuid4

import vdf

from gamehub_cli.steam import (
    SteamContext,
    SteamArtworkAssignment,
    SteamShortcutSpec,
    steam_id64_from_userdata_id,
    backup_steam_configs,
    copy_grid_art,
    discover_steam_id,
    prune_grid_noncanonical_variants,
    update_cloud_collections,
    update_collections,
    upsert_shortcuts,
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


def test_discover_steam_id_prefers_most_recent_profile() -> None:
    with _workspace_tempdir("gamehub-steam-") as temp_root:
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


def test_discover_steam_id_uses_preferred_when_present() -> None:
    with _workspace_tempdir("gamehub-steam-") as temp_root:
        (temp_root / "76561198000000010").mkdir()
        (temp_root / "76561198000000002").mkdir()

        steam_id = discover_steam_id(temp_root, preferred_steam_id="76561198000000010")

        assert steam_id == "76561198000000010"


def test_discover_steam_id_accepts_preferred_steamid64() -> None:
    with _workspace_tempdir("gamehub-steam-") as temp_root:
        account_id = "37747392"
        (temp_root / account_id).mkdir()

        steam_id = discover_steam_id(temp_root, preferred_steam_id="76561197998013120")

        assert steam_id == account_id


def test_discover_steam_id_raises_for_missing_preferred() -> None:
    with _workspace_tempdir("gamehub-steam-") as temp_root:
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


def test_copy_grid_art_copies_existing_and_skips_missing() -> None:
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

        copied = copy_grid_art(context, assignments)

        copied_names = sorted(path.name for path in copied)
        assert copied_names == ["123456.png", "123456_icon.png", "123456p.png"]


def test_upsert_shortcuts_round_trip_and_idempotent() -> None:
    with _workspace_tempdir("gamehub-steam-") as temp_root:
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


def test_upsert_shortcuts_migrates_legacy_matching_entry() -> None:
    with _workspace_tempdir("gamehub-steam-") as temp_root:
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


def test_upsert_shortcuts_migrates_legacy_entry_when_launch_options_changed() -> None:
    with _workspace_tempdir("gamehub-steam-") as temp_root:
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


def test_update_collections_preserves_unmanaged_and_is_idempotent() -> None:
    with _workspace_tempdir("gamehub-steam-") as temp_root:
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


def test_upsert_shortcuts_uses_persisted_appid_for_mapping() -> None:
    with _workspace_tempdir("gamehub-steam-") as temp_root:
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


def test_update_collections_creates_canonical_webstorage_path_when_missing() -> None:
    with _workspace_tempdir("gamehub-steam-") as temp_root:
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


def test_update_collections_normalizes_added_appids_to_unsigned() -> None:
    with _workspace_tempdir("gamehub-steam-") as temp_root:
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
        assert psx["added"] == ["3692015043"]


def test_update_collections_preserves_list_json_shape() -> None:
    with _workspace_tempdir("gamehub-steam-") as temp_root:
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


def test_update_cloud_collections_preserves_unmanaged_and_is_idempotent() -> None:
    with _workspace_tempdir("gamehub-steam-") as temp_root:
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


def test_update_cloud_collections_returns_zero_without_path() -> None:
    with _workspace_tempdir("gamehub-steam-") as temp_root:
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


def test_prune_grid_noncanonical_variants_removes_signed_when_unsigned_exists() -> None:
    with _workspace_tempdir("gamehub-steam-") as temp_root:
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
