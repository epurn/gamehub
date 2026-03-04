from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from gamehub_cli.common.config import GamehubConfig, SaveSyncConfig
from gamehub_cli.sync.planner import create_sync_plan
from gamehub_cli.sync.state import SyncState
from gamehub_common.models import (
    FirmwareSpec,
    LibraryIndex,
    RomSpec,
    SaveBindingCatalog,
    SaveBindingSpec,
    SaveSpec,
    SystemSpec,
    TitleEntry,
)


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
        steam_id=None,
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


def test_planner_n3ds_without_firmware_metadata_does_not_block_titles(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-plan-") as temp_root:
        system = SystemSpec(
            name="N3DS",
            rom_extensions=(".3ds", ".cci", ".cxi"),
            default_emulator="azahar",
            launch_template='"{emulator}" "{rom}"',
            firmware=(),
        )
        title = TitleEntry(
            title_id="title_n3ds_pilotwings",
            system="N3DS",
            title_name="Pilotwings Resort",
            title_rel_dir="N3DS/Pilotwings Resort.3ds",
            emulator="azahar",
            launch_template='"{emulator}" "{rom}"',
            rom=RomSpec(
                file_id="file_pilotwings",
                rel_path="roms/N3DS/Pilotwings Resort.3ds",
                sha256="b" * 64,
                size_bytes=4096,
                extension=".3ds",
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
            steam_id=None,
            steam_exe=None,
            sgdb_api_key=None,
            sgdb_cache_dir=temp_root / "artwork_cache",
            sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        )

        plan = create_sync_plan(index=index, config=config, state=SyncState(), verify=False)

        assert len(plan.firmware_actions) == 0
        assert len(plan.content_actions) == 1
        assert plan.content_actions[0].content_id == "file_pilotwings"
        assert plan.skipped_titles == 0
        assert not plan.blocked_systems


def test_planner_includes_rom_when_required_firmware_present(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-plan-") as temp_root:
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
            steam_id=None,
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


def test_planner_verify_hash_detects_local_rom_drift(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-plan-") as temp_root:
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
            steam_id=None,
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


def test_planner_without_verify_still_redownloads_on_size_mismatch(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-plan-") as temp_root:
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
            steam_id=None,
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


def test_planner_missing_optional_firmware_does_not_block_titles(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-plan-") as temp_root:
        system = SystemSpec(
            name="Wii",
            rom_extensions=(".iso",),
            default_emulator="dolphin",
            launch_template='"{emulator}" -b -e "{rom}"',
            firmware=(FirmwareSpec(filename="keys.md", sha256="a" * 64, required=False),),
        )
        title = TitleEntry(
            title_id="title_wii_mg",
            system="Wii",
            title_name="Mario Galaxy",
            title_rel_dir="Wii/Mario Galaxy",
            emulator="dolphin",
            launch_template='"{emulator}" -b -e "{rom}"',
            rom=RomSpec(
                file_id="file_mg",
                rel_path="roms/Wii/MarioGalaxy.iso",
                sha256="b" * 64,
                size_bytes=3,
                extension=".iso",
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
            steam_id=None,
            steam_exe=None,
            sgdb_api_key=None,
            sgdb_cache_dir=temp_root / "artwork_cache",
            sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        )
        rom_path = config.library_dir / "roms" / "Wii" / "MarioGalaxy.iso"
        rom_path.parent.mkdir(parents=True, exist_ok=True)
        rom_path.write_bytes(b"rom")

        plan = create_sync_plan(index=index, config=config, state=SyncState(), verify=False)

        assert not plan.blocked_systems
        assert plan.skipped_titles == 0
        assert len(plan.firmware_actions) == 1
        assert plan.firmware_actions[0].content_id == "Wii/keys.md"
        assert len(plan.content_actions) == 0


def test_planner_uses_configurable_roms_output_dir(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-plan-") as temp_root:
        system = SystemSpec(
            name="NES",
            rom_extensions=(".nes",),
            default_emulator="retroarch",
            launch_template='"{emulator}" "{rom}"',
            firmware=(),
        )
        title = TitleEntry(
            title_id="title_nes_smb",
            system="NES",
            title_name="Super Mario Bros",
            title_rel_dir="NES/Super Mario Bros",
            emulator="retroarch",
            launch_template='"{emulator}" "{rom}"',
            rom=RomSpec(
                file_id="file_smb",
                rel_path="roms/NES/SuperMarioBros.nes",
                sha256="a" * 64,
                size_bytes=40,
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
            roms_dir=temp_root / "sdcard" / "roms",
            steam_userdata_dir=None,
            steam_id=None,
            steam_exe=None,
            sgdb_api_key=None,
            sgdb_cache_dir=temp_root / "artwork_cache",
            sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        )

        plan = create_sync_plan(index=index, config=config, state=SyncState(), verify=False)

        assert len(plan.content_actions) == 1
        assert plan.content_actions[0].destination == temp_root / "sdcard" / "roms" / "NES" / "SuperMarioBros.nes"


def test_save_planner_classifies_download_upload_conflict_and_skip(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-save-plan-") as temp_root:
        save_root = temp_root / "memcards"
        save_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr("gamehub_cli.emulators.save_resolution.resolve_system_save_root", lambda _system: save_root)
        remote_bytes = [b"remote-0", b"remote-1", b"remote-2", b"remote-3"]
        saves = tuple(
            SaveSpec(
                save_id=f"save_{index}",
                title_id="title_ps2_ffx",
                system="PS2",
                kind="memory_card",
                rel_path=f"saves/PS2/Final Fantasy X/memory_card/ffx_{index}.ps2",
                sha256=_sha256_bytes(payload),
                size_bytes=len(payload),
                updated_at=datetime(2026, 1, 1, 12, index, tzinfo=timezone.utc),
                portable=True,
            )
            for index, payload in enumerate(remote_bytes)
        )
        index = LibraryIndex(index_version=1, systems=(), titles=(), saves=saves)
        config = GamehubConfig(
            server_url="http://localhost:8000",
            library_dir=temp_root / "library",
            firmware_dir=temp_root / "firmware",
            state_path=temp_root / "state.json",
            steam_userdata_dir=None,
            steam_id=None,
            steam_exe=None,
            sgdb_api_key=None,
            sgdb_cache_dir=temp_root / "artwork_cache",
            sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
            save_sync=SaveSyncConfig(enabled=True, mode="bidirectional", conflict_policy="manual"),
        )

        save_one_path = save_root / "ffx_1.ps2"
        save_one_path.parent.mkdir(parents=True, exist_ok=True)
        save_one_path.write_bytes(remote_bytes[1])

        save_two_path = save_root / "ffx_2.ps2"
        save_two_path.write_bytes(b"local-edited")

        save_three_path = save_root / "ffx_3.ps2"
        save_three_path.write_bytes(b"both-edited")

        state = SyncState(
            save_lineage={
                "save_2": {
                    "local_sha256": _sha256_bytes(remote_bytes[2]),
                    "remote_sha256": _sha256_bytes(remote_bytes[2]),
                },
                "save_3": {
                    "local_sha256": _sha256_bytes(b"lineage-local"),
                    "remote_sha256": _sha256_bytes(b"lineage-remote"),
                },
            }
        )

        plan = create_sync_plan(index=index, config=config, state=state, verify=False)
        by_id = {action.save_id: action for action in plan.save_actions}

        assert by_id["save_0"].decision == "download"
        assert by_id["save_0"].reason == "local-missing"
        assert by_id["save_1"].decision == "skip"
        assert by_id["save_1"].reason == "already-synced"
        assert by_id["save_2"].decision == "upload_existing"
        assert by_id["save_2"].reason == "local-changed-remote-unchanged"
        assert by_id["save_3"].decision == "conflict"
        assert by_id["save_3"].reason == "both-changed-manual"


def test_save_planner_respects_disabled_and_system_filters(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-save-plan-") as temp_root:
        save = SaveSpec(
            save_id="save_wii_1",
            title_id="title_wii_mg",
            system="Wii",
            kind="per_game",
            rel_path="saves/Wii/MarioGalaxy.sav",
            sha256=_sha256_bytes(b"remote"),
            size_bytes=6,
            updated_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            portable=True,
        )
        index = LibraryIndex(index_version=1, systems=(), titles=(), saves=(save,))
        config_disabled = GamehubConfig(
            server_url="http://localhost:8000",
            library_dir=temp_root / "library-disabled",
            firmware_dir=temp_root / "firmware",
            state_path=temp_root / "state.json",
            steam_userdata_dir=None,
            steam_id=None,
            steam_exe=None,
            sgdb_api_key=None,
            sgdb_cache_dir=temp_root / "artwork_cache",
            sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
            save_sync=SaveSyncConfig(enabled=False),
        )
        config_filtered = GamehubConfig(
            server_url="http://localhost:8000",
            library_dir=temp_root / "library-filtered",
            firmware_dir=temp_root / "firmware",
            state_path=temp_root / "state.json",
            steam_userdata_dir=None,
            steam_id=None,
            steam_exe=None,
            sgdb_api_key=None,
            sgdb_cache_dir=temp_root / "artwork_cache",
            sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
            save_sync=SaveSyncConfig(enabled=True, systems=("PS2",)),
        )

        plan_disabled = create_sync_plan(index=index, config=config_disabled, state=SyncState(), verify=False)
        plan_filtered = create_sync_plan(index=index, config=config_filtered, state=SyncState(), verify=False)

        assert plan_disabled.save_actions[0].decision == "skip"
        assert plan_disabled.save_actions[0].reason == "save-sync-disabled"
        assert plan_filtered.save_actions[0].decision == "skip"
        assert plan_filtered.save_actions[0].reason == "system-filtered"


def test_save_planner_emits_upload_new_for_local_only_exact_file(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-save-plan-") as temp_root:
        save_root = temp_root / "retroarch-saves"
        save_root.mkdir(parents=True, exist_ok=True)
        (save_root / "SuperMarioBros.srm").write_bytes(b"local-new")
        monkeypatch.setattr(
            "gamehub_cli.emulators.save_resolution.resolve_emulator_save_root", lambda *args, **kwargs: save_root
        )

        index = LibraryIndex(index_version=1, systems=(), titles=(), saves=())
        bindings = SaveBindingCatalog(
            bindings=(
                SaveBindingSpec(
                    binding_id="savebind_nes",
                    title_id="title_nes",
                    system="NES",
                    kind="battery",
                    server_rel_dir="saves/NES/SuperMarioBros/battery",
                    local_root="retroarch_saves",
                    strategy="exact_files",
                    candidate_filenames=("SuperMarioBros.srm",),
                    learn_rule=None,
                    portable=True,
                ),
            )
        )
        config = GamehubConfig(
            server_url="http://localhost:8000",
            library_dir=temp_root / "library",
            firmware_dir=temp_root / "firmware",
            state_path=temp_root / "state.json",
            steam_userdata_dir=None,
            steam_id=None,
            steam_exe=None,
            sgdb_api_key=None,
            sgdb_cache_dir=temp_root / "artwork_cache",
            sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
            save_sync=SaveSyncConfig(enabled=True, mode="bidirectional"),
        )

        plan = create_sync_plan(index=index, config=config, state=SyncState(), save_bindings=bindings)

        assert len(plan.save_actions) == 1
        assert plan.save_actions[0].decision == "upload_new"
        assert plan.save_actions[0].canonical_suffix == "SuperMarioBros.srm"


def test_save_planner_emits_upload_new_for_nested_retroarch_exact_file(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-save-plan-") as temp_root:
        save_root = temp_root / "retroarch-saves"
        nested = save_root / "Gambatte" / "Pokemon.srm"
        nested.parent.mkdir(parents=True, exist_ok=True)
        nested.write_bytes(b"local-new")
        monkeypatch.setattr(
            "gamehub_cli.emulators.save_resolution.resolve_emulator_save_root", lambda *args, **kwargs: save_root
        )
        monkeypatch.setattr(
            "gamehub_cli.emulators.save_resolution._retroarch_prefers_core_subdirs", lambda **kwargs: False
        )

        index = LibraryIndex(index_version=1, systems=(), titles=(), saves=())
        bindings = SaveBindingCatalog(
            bindings=(
                SaveBindingSpec(
                    binding_id="savebind_gb",
                    title_id="title_gb",
                    system="GB",
                    kind="battery",
                    server_rel_dir="saves/GB/Pokemon/battery",
                    local_root="retroarch_saves",
                    strategy="exact_files",
                    candidate_filenames=("Pokemon.srm",),
                    learn_rule=None,
                    portable=True,
                ),
            )
        )
        config = GamehubConfig(
            server_url="http://localhost:8000",
            library_dir=temp_root / "library",
            firmware_dir=temp_root / "firmware",
            state_path=temp_root / "state.json",
            steam_userdata_dir=None,
            steam_id=None,
            steam_exe=None,
            sgdb_api_key=None,
            sgdb_cache_dir=temp_root / "artwork_cache",
            sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
            save_sync=SaveSyncConfig(enabled=True, mode="bidirectional"),
        )

        plan = create_sync_plan(index=index, config=config, state=SyncState(), save_bindings=bindings)

        assert len(plan.save_actions) == 1
        assert plan.save_actions[0].decision == "upload_new"
        assert plan.save_actions[0].destination == nested


def test_save_planner_keeps_download_mode_strict_for_local_only_exact_file(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-save-plan-") as temp_root:
        save_root = temp_root / "retroarch-saves"
        save_root.mkdir(parents=True, exist_ok=True)
        (save_root / "SuperMarioBros.srm").write_bytes(b"local-new")
        monkeypatch.setattr(
            "gamehub_cli.emulators.save_resolution.resolve_emulator_save_root", lambda *args, **kwargs: save_root
        )

        index = LibraryIndex(index_version=1, systems=(), titles=(), saves=())
        bindings = SaveBindingCatalog(
            bindings=(
                SaveBindingSpec(
                    binding_id="savebind_nes",
                    title_id="title_nes",
                    system="NES",
                    kind="battery",
                    server_rel_dir="saves/NES/SuperMarioBros/battery",
                    local_root="retroarch_saves",
                    strategy="exact_files",
                    candidate_filenames=("SuperMarioBros.srm",),
                    learn_rule=None,
                    portable=True,
                ),
            )
        )
        config = GamehubConfig(
            server_url="http://localhost:8000",
            library_dir=temp_root / "library",
            firmware_dir=temp_root / "firmware",
            state_path=temp_root / "state.json",
            steam_userdata_dir=None,
            steam_id=None,
            steam_exe=None,
            sgdb_api_key=None,
            sgdb_cache_dir=temp_root / "artwork_cache",
            sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
            save_sync=SaveSyncConfig(enabled=True, mode="download"),
        )

        plan = create_sync_plan(index=index, config=config, state=SyncState(), save_bindings=bindings)

        assert len(plan.save_actions) == 1
        assert plan.save_actions[0].decision == "skip"
        assert plan.save_actions[0].reason == "download-mode-local-new"
