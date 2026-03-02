from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from gamehub_cli.common.config import ControllersConfig, GamehubConfig
from gamehub_cli.controllers.convergence import (
    ControllerTargetStatus,
    apply_controller_convergence_plan,
    build_controller_convergence_plan,
    converge_controller_state,
    format_runtime_selection_rules,
)
from gamehub_cli.controllers.profiles import (
    PROFILE_KBM,
    PROFILE_XBOX_1P,
    PROFILE_XBOX_2P,
    profile_name_for_controller_count,
)
from gamehub_common.models import LibraryIndex, RomSpec, TitleEntry


def _config(root: Path) -> GamehubConfig:
    return GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=root / "library",
        firmware_dir=root / "firmware",
        state_path=root / "state.json",
        steam_userdata_dir=None,
        steam_id=None,
        steam_exe=None,
        sgdb_api_key=None,
        sgdb_cache_dir=root / "cache",
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        controllers=ControllersConfig(launch_autoconfig=True),
    )


def _pcsx2_index() -> LibraryIndex:
    return LibraryIndex(
        index_version=1,
        systems=(),
        titles=(
            TitleEntry(
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
            ),
        ),
    )


def test_controller_convergence_first_apply_writes_expected_state(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-convergence-") as temp_root:
        base = _config(temp_root)
        pcsx2_ini = temp_root / "pcsx2" / "inis" / "PCSX2.ini"
        config = replace(base, linux=replace(base.linux, pcsx2_ini_path=pcsx2_ini))

        result = converge_controller_state(
            config,
            index=_pcsx2_index(),
            dry_run=False,
            verbose=False,
            force_managed=False,
        )

        profile_file = config.library_dir / "controller_profiles" / "pcsx2" / "kbm" / "PCSX2.ini"
        metadata_file = profile_file.parent / ".gamehub-managed.json"
        assert profile_file.exists()
        assert metadata_file.exists()
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        entry = metadata["entries"]["PCSX2.ini"]
        assert entry["ownership"] == "managed"
        assert entry["source_profile"] == "kbm"
        assert entry["source_template"] == "profile://pcsx2/kbm/PCSX2.ini"
        assert len(entry["fingerprint_sha256"]) == 64
        assert entry["timestamp_utc"]

        pcsx2_text = pcsx2_ini.read_text(encoding="utf-8")
        assert "SDL = true" in pcsx2_text
        assert "ConfirmShutdown = false" in pcsx2_text
        assert result.repaired_count > 0


def test_controller_convergence_second_apply_is_no_op(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-convergence-") as temp_root:
        base = _config(temp_root)
        pcsx2_ini = temp_root / "pcsx2" / "inis" / "PCSX2.ini"
        config = replace(base, linux=replace(base.linux, pcsx2_ini_path=pcsx2_ini))
        index = _pcsx2_index()

        converge_controller_state(
            config,
            index=index,
            dry_run=False,
            verbose=False,
            force_managed=False,
        )
        second = converge_controller_state(
            config,
            index=index,
            dry_run=False,
            verbose=False,
            force_managed=False,
        )

        assert second.repaired_count == 0
        assert second.drift_count == 0
        assert second.unmanaged_count == 0
        assert second.error_count == 0
        assert second.unchanged_count > 0


def test_controller_convergence_detects_managed_profile_drift(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-convergence-") as temp_root:
        base = _config(temp_root)
        pcsx2_ini = temp_root / "pcsx2" / "inis" / "PCSX2.ini"
        config = replace(base, linux=replace(base.linux, pcsx2_ini_path=pcsx2_ini))
        index = _pcsx2_index()

        converge_controller_state(
            config,
            index=index,
            dry_run=False,
            verbose=False,
            force_managed=False,
        )
        profile_file = config.library_dir / "controller_profiles" / "pcsx2" / "kbm" / "PCSX2.ini"
        profile_file.write_text("[Injected]\nUser = Drift\n", encoding="utf-8")

        plan = build_controller_convergence_plan(config, emulator_families={"pcsx2"})
        result = apply_controller_convergence_plan(plan, apply=False, force_managed=False)
        finding = next(item for item in result.findings if item.target_path == profile_file)
        assert finding.status == ControllerTargetStatus.DRIFT
        assert finding.repairable is True
        assert result.drift_count > 0


def test_controller_convergence_apply_repairs_managed_profile_drift(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-convergence-") as temp_root:
        base = _config(temp_root)
        pcsx2_ini = temp_root / "pcsx2" / "inis" / "PCSX2.ini"
        config = replace(base, linux=replace(base.linux, pcsx2_ini_path=pcsx2_ini))
        index = _pcsx2_index()

        converge_controller_state(
            config,
            index=index,
            dry_run=False,
            verbose=False,
            force_managed=False,
        )
        profile_file = config.library_dir / "controller_profiles" / "pcsx2" / "kbm" / "PCSX2.ini"
        profile_file.write_text("[Injected]\nUser = Drift\n", encoding="utf-8")

        plan = build_controller_convergence_plan(config, emulator_families={"pcsx2"})
        repaired = apply_controller_convergence_plan(plan, apply=True, force_managed=False)
        finding = next(item for item in repaired.findings if item.target_path == profile_file)
        assert finding.status == ControllerTargetStatus.REPAIRED
        assert finding.repaired is True
        assert "OpenPauseMenu = Keyboard/Escape" in profile_file.read_text(encoding="utf-8")


def test_controller_convergence_does_not_overwrite_unmanaged_profile_without_marker(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-convergence-") as temp_root:
        base = _config(temp_root)
        pcsx2_ini = temp_root / "pcsx2" / "inis" / "PCSX2.ini"
        config = replace(base, linux=replace(base.linux, pcsx2_ini_path=pcsx2_ini))
        profile_file = config.library_dir / "controller_profiles" / "pcsx2" / "kbm" / "PCSX2.ini"
        profile_file.parent.mkdir(parents=True, exist_ok=True)
        profile_file.write_text("[Custom]\nUser = Keep\n", encoding="utf-8")

        plan = build_controller_convergence_plan(config, emulator_families={"pcsx2"})
        result = apply_controller_convergence_plan(plan, apply=True, force_managed=False)
        finding = next(item for item in result.findings if item.target_path == profile_file)
        assert finding.status == ControllerTargetStatus.UNMANAGED
        assert finding.repaired is False
        assert "[Custom]" in profile_file.read_text(encoding="utf-8")


def test_controller_convergence_force_replaces_unmanaged_profile_with_backup(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-convergence-") as temp_root:
        base = _config(temp_root)
        pcsx2_ini = temp_root / "pcsx2" / "inis" / "PCSX2.ini"
        config = replace(base, linux=replace(base.linux, pcsx2_ini_path=pcsx2_ini))
        profile_file = config.library_dir / "controller_profiles" / "pcsx2" / "kbm" / "PCSX2.ini"
        profile_file.parent.mkdir(parents=True, exist_ok=True)
        profile_file.write_text("[Custom]\nUser = Keep\n", encoding="utf-8")

        plan = build_controller_convergence_plan(config, emulator_families={"pcsx2"})
        result = apply_controller_convergence_plan(plan, apply=True, force_unmanaged=True)
        finding = next(item for item in result.findings if item.target_path == profile_file)
        backup_root = profile_file.parent / ".gamehub-unmanaged-backups"

        assert finding.status == ControllerTargetStatus.REPAIRED
        assert finding.repaired is True
        assert "OpenPauseMenu = Keyboard/Escape" in profile_file.read_text(encoding="utf-8")
        backups = list(backup_root.glob("PCSX2.ini.*.bak"))
        assert backups
        assert "[Custom]" in backups[0].read_text(encoding="utf-8")


def test_controller_convergence_force_archives_extra_unmanaged_profile_file(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-convergence-") as temp_root:
        base = _config(temp_root)
        pcsx2_ini = temp_root / "pcsx2" / "inis" / "PCSX2.ini"
        config = replace(base, linux=replace(base.linux, pcsx2_ini_path=pcsx2_ini))
        extra_file = config.library_dir / "controller_profiles" / "pcsx2" / "kbm" / "custom.ini"
        extra_file.parent.mkdir(parents=True, exist_ok=True)
        extra_file.write_text("[Custom]\nUser = Keep\n", encoding="utf-8")

        plan = build_controller_convergence_plan(config, emulator_families={"pcsx2"})
        result = apply_controller_convergence_plan(
            plan,
            apply=True,
            force_unmanaged=True,
            include_unmanaged_scan=True,
        )
        finding = next(item for item in result.findings if item.target_path == extra_file)
        backup_root = extra_file.parent / ".gamehub-unmanaged-backups"

        assert finding.status == ControllerTargetStatus.REPAIRED
        assert finding.repaired is True
        assert not extra_file.exists()
        backups = list(backup_root.glob("custom.ini.*.bak"))
        assert backups
        assert "[Custom]" in backups[0].read_text(encoding="utf-8")


def test_controller_convergence_runtime_selection_rules_remain_autodetect() -> None:
    rules = format_runtime_selection_rules(
        build_controller_convergence_plan(_config(Path("gamehub"))).runtime_selection
    )
    assert rules == "0->kbm,1->xbox_1p,2+->xbox_2p"
    assert profile_name_for_controller_count(0) == PROFILE_KBM
    assert profile_name_for_controller_count(1) == PROFILE_XBOX_1P
    assert profile_name_for_controller_count(2) == PROFILE_XBOX_2P
