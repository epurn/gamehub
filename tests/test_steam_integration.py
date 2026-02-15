from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import shutil
from uuid import uuid4

import vdf

from gamehub_cli.steam import (
    SteamArtworkAssignment,
    SteamContext,
    SteamShortcutSpec,
    copy_grid_art,
    update_collections,
    upsert_shortcuts,
)




def _context(temp_root: Path) -> SteamContext:
    config_dir = temp_root / "userdata" / "76561198000000001" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    return SteamContext(
        userdata_dir=temp_root / "userdata",
        steam_id="76561198000000001",
        shortcuts_path=config_dir / "shortcuts.vdf",
        localconfig_path=config_dir / "localconfig.vdf",
        steam_exe=None,
    )


def test_fake_userdata_round_trip_shortcuts_collections_and_art() -> None:
    with _workspace_tempdir("gamehub-steam-integration-") as temp_root:
        context = _context(temp_root)
        initial = {"collections": [{"name": "Manual", "added": ["123"], "removed": []}]}
        context.localconfig_path.write_text(
            vdf.dumps({"UserLocalConfigStore": {"user-collections": json.dumps(initial)}}),
            encoding="utf-8",
        )
        specs = [
            SteamShortcutSpec(
                title_id="title_nes_mario",
                system="NES",
                title_name="Super Mario Bros",
                exe="retroarch.exe",
                launch_options='"roms\\NES\\SuperMarioBros.nes"',
                start_dir="C:\\Emulators",
                icon_path="",
            ),
            SteamShortcutSpec(
                title_id="title_psx_mgs",
                system="PSX",
                title_name="Metal Gear Solid",
                exe="retroarch.exe",
                launch_options='"roms\\PSX\\MetalGearSolid.chd"',
                start_dir="C:\\Emulators",
                icon_path="",
            ),
        ]

        first = upsert_shortcuts(context, specs)
        second = upsert_shortcuts(context, specs)
        changed_collections = update_collections(context, first.app_ids_by_system)
        unchanged_collections = update_collections(context, first.app_ids_by_system)

        grid = temp_root / "art-cache" / "mario-grid.png"
        hero = temp_root / "art-cache" / "mario-hero.png"
        grid.parent.mkdir(parents=True, exist_ok=True)
        grid.write_bytes(b"grid")
        hero.write_bytes(b"hero")
        copied = copy_grid_art(
            context,
            [
                SteamArtworkAssignment(
                    steam_app_id=first.app_ids_by_title["title_nes_mario"],
                    assets_by_kind={"grid": grid, "hero": hero},
                )
            ],
        )

        assert first.total_shortcuts == 2
        assert second.total_shortcuts == 2
        assert first.app_ids_by_title == second.app_ids_by_title
        assert changed_collections > 0
        assert unchanged_collections == 0
        assert len(copied) == 3
        assert all(path.exists() for path in copied)


def test_fake_userdata_handles_corrupt_localconfig() -> None:
    with _workspace_tempdir("gamehub-steam-integration-") as temp_root:
        context = _context(temp_root)
        context.localconfig_path.write_text("not-vdf", encoding="utf-8")

        updates = update_collections(context, {"NES": ["123456"]})

        assert updates > 0
        payload = vdf.loads(context.localconfig_path.read_text(encoding="utf-8"))
        encoded = payload["UserLocalConfigStore"]["WebStorage"]["user-collections"]
        collections = json.loads(encoded)["collections"]
        assert any(item.get("name") == "NES" for item in collections if isinstance(item, dict))
