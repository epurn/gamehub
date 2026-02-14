from __future__ import annotations

from pathlib import Path

from gamehub_cli.config import GamehubConfig
from gamehub_cli.planner import create_sync_plan
from gamehub_cli.state import SyncState
from gamehub_common.models import FirmwareSpec, LibraryIndex, RomSpec, SystemSpec, TitleEntry


def test_planner_blocks_titles_when_firmware_missing() -> None:
    system = SystemSpec(
        name="PS2",
        rom_extensions=(".iso",),
        default_emulator="pcsx2",
        launch_template='"{emulator}" "{rom}"',
        firmware=(FirmwareSpec(filename="scph10000.bin", sha256="a" * 64, required=True),),
    )
    title = TitleEntry(
        title_id="title_ps2_ffx",
        system="PS2",
        title_name="Final Fantasy X",
        title_rel_dir="PS2/Final Fantasy X",
        emulator="pcsx2",
        launch_template='"{emulator}" "{rom}"',
        rom=RomSpec(
            file_id="file_ffx",
            rel_path="roms/PS2/Final Fantasy X/ffx.iso",
            sha256="b" * 64,
            size_bytes=1024,
            extension=".iso",
        ),
        assets=(),
    )
    index = LibraryIndex(index_version=1, systems=(system,), titles=(title,))
    fixture_root = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
    config = GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=fixture_root / "library_out",
        firmware_dir=fixture_root / "firmware_out",
        state_path=fixture_root / "state.json",
        steam_userdata_dir=None,
        steam_exe=None,
    )
    plan = create_sync_plan(index=index, config=config, state=SyncState(), verify=False)
    assert len(plan.firmware_actions) == 1
    assert len(plan.content_actions) == 0
    assert plan.skipped_titles == 1
    assert plan.blocked_systems["PS2"] == "Missing required firmware"
