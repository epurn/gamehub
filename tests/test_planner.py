from __future__ import annotations

from contextlib import contextmanager
import hashlib
from pathlib import Path
import shutil
from uuid import uuid4

from gamehub_cli.config import GamehubConfig
from gamehub_cli.planner import create_sync_plan
from gamehub_cli.state import SyncState
from gamehub_common.models import FirmwareSpec, LibraryIndex, RomSpec, SystemSpec, TitleEntry


@contextmanager
def _workspace_plan_dir(prefix: str):
    root = Path(__file__).resolve().parents[1] / ".pytest_tmp_local"
    root.mkdir(parents=True, exist_ok=True)
    temp_dir = root / f"{prefix}{uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=False)
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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
            rel_path="roms/PS2/Final Fantasy X.iso",
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
        sgdb_api_key=None,
        sgdb_cache_dir=fixture_root / "artwork_cache",
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
    )
    plan = create_sync_plan(index=index, config=config, state=SyncState(), verify=False)
    assert len(plan.firmware_actions) == 1
    assert len(plan.content_actions) == 0
    assert plan.skipped_titles == 1
    assert plan.blocked_systems["PS2"] == "Missing required firmware"


def test_planner_includes_rom_when_required_firmware_present() -> None:
    with _workspace_plan_dir("gamehub-plan-") as temp_root:
        system = SystemSpec(
            name="PSX",
            rom_extensions=(".bin",),
            default_emulator="retroarch",
            launch_template='"{emulator}" "{rom}"',
            firmware=(FirmwareSpec(filename="scph5501.bin", sha256=_sha256_bytes(b"fw"), required=True),),
        )
        title = TitleEntry(
            title_id="title_psx_mgs",
            system="PSX",
            title_name="Metal Gear Solid",
            title_rel_dir="PSX/Metal Gear Solid",
            emulator="retroarch",
            launch_template='"{emulator}" "{rom}"',
            rom=RomSpec(
                file_id="file_mgs",
                rel_path="roms/PSX/Metal Gear Solid.bin",
                sha256="c" * 64,
                size_bytes=2048,
                extension=".bin",
            ),
            assets=(),
        )
        index = LibraryIndex(index_version=1, systems=(system,), titles=(title,))
        config = GamehubConfig(
            server_url="http://localhost:8000",
            library_dir=temp_root / "library",
            firmware_dir=temp_root / "firmware",
            state_path=temp_root / "state.json",
            steam_userdata_dir=None,
            steam_exe=None,
            sgdb_api_key=None,
            sgdb_cache_dir=temp_root / "artwork_cache",
            sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        )
        firmware_path = config.firmware_dir / "PSX" / "scph5501.bin"
        firmware_path.parent.mkdir(parents=True, exist_ok=True)
        firmware_path.write_bytes(b"fw")

        plan = create_sync_plan(index=index, config=config, state=SyncState(), verify=True)

        assert len(plan.firmware_actions) == 0
        assert len(plan.content_actions) == 1
        assert plan.content_actions[0].content_id == "file_mgs"
        assert plan.skipped_titles == 0
        assert not plan.blocked_systems


def test_planner_verify_hash_detects_local_rom_drift() -> None:
    with _workspace_plan_dir("gamehub-plan-") as temp_root:
        system = SystemSpec(
            name="NES",
            rom_extensions=(".nes",),
            default_emulator="retroarch",
            launch_template='"{emulator}" "{rom}"',
            firmware=(),
        )
        expected_rom_bytes = b"expected-rom"
        title = TitleEntry(
            title_id="title_nes_mario",
            system="NES",
            title_name="Super Mario Bros",
            title_rel_dir="NES/Super Mario Bros",
            emulator="retroarch",
            launch_template='"{emulator}" "{rom}"',
            rom=RomSpec(
                file_id="file_mario",
                rel_path="roms/NES/SuperMarioBros.nes",
                sha256=_sha256_bytes(expected_rom_bytes),
                size_bytes=len(expected_rom_bytes),
                extension=".nes",
            ),
            assets=(),
        )
        index = LibraryIndex(index_version=1, systems=(system,), titles=(title,))
        config = GamehubConfig(
            server_url="http://localhost:8000",
            library_dir=temp_root / "library",
            firmware_dir=temp_root / "firmware",
            state_path=temp_root / "state.json",
            steam_userdata_dir=None,
            steam_exe=None,
            sgdb_api_key=None,
            sgdb_cache_dir=temp_root / "artwork_cache",
            sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        )
        rom_path = config.library_dir / "roms" / "NES" / "SuperMarioBros.nes"
        rom_path.parent.mkdir(parents=True, exist_ok=True)
        rom_path.write_bytes(b"drifted_data")
        state = SyncState(downloaded_checksums={"file_mario": title.rom.sha256})

        plan_no_verify = create_sync_plan(index=index, config=config, state=state, verify=False)
        plan_verify = create_sync_plan(index=index, config=config, state=state, verify=True)

        assert len(plan_no_verify.content_actions) == 0
        assert len(plan_verify.content_actions) == 1
        assert plan_verify.content_actions[0].content_id == "file_mario"


def test_planner_without_verify_still_redownloads_on_size_mismatch() -> None:
    with _workspace_plan_dir("gamehub-plan-") as temp_root:
        system = SystemSpec(
            name="NES",
            rom_extensions=(".nes",),
            default_emulator="retroarch",
            launch_template='"{emulator}" "{rom}"',
            firmware=(),
        )
        expected_rom_bytes = b"0123456789abcdef"
        title = TitleEntry(
            title_id="title_nes_mismatch",
            system="NES",
            title_name="Size Mismatch Test",
            title_rel_dir="NES/Size Mismatch Test",
            emulator="retroarch",
            launch_template='"{emulator}" "{rom}"',
            rom=RomSpec(
                file_id="file_size_mismatch",
                rel_path="roms/NES/SizeMismatchTest.nes",
                sha256=_sha256_bytes(expected_rom_bytes),
                size_bytes=len(expected_rom_bytes),
                extension=".nes",
            ),
            assets=(),
        )
        index = LibraryIndex(index_version=1, systems=(system,), titles=(title,))
        config = GamehubConfig(
            server_url="http://localhost:8000",
            library_dir=temp_root / "library",
            firmware_dir=temp_root / "firmware",
            state_path=temp_root / "state.json",
            steam_userdata_dir=None,
            steam_exe=None,
            sgdb_api_key=None,
            sgdb_cache_dir=temp_root / "artwork_cache",
            sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        )
        rom_path = config.library_dir / "roms" / "NES" / "SizeMismatchTest.nes"
        rom_path.parent.mkdir(parents=True, exist_ok=True)
        rom_path.write_bytes(b"x")  # Wrong size, but file exists.
        state = SyncState(downloaded_checksums={"file_size_mismatch": title.rom.sha256})

        plan = create_sync_plan(index=index, config=config, state=state, verify=False)

        assert len(plan.content_actions) == 1
        assert plan.content_actions[0].content_id == "file_size_mismatch"
