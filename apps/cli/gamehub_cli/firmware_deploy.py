from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
from typing import Callable
from uuid import uuid4

from gamehub_common.ids import sha256_file
from gamehub_common.models import LibraryIndex

from .config import GamehubConfig
from .emulators import resolve_emulator_executable
import gamehub_cli.firmware_targets as firmware_targets
import gamehub_cli.pcsx2_ini as pcsx2_ini
from .fsops import replace_file
from .platform_paths import PCSX2_FLATPAK_APP_ID, is_flatpak_command, linux_flatpak_pcsx2_root


def _sync_targets_module() -> None:
    firmware_targets.resolve_emulator_executable = resolve_emulator_executable
    firmware_targets.os = os
    firmware_targets.sys = sys
    firmware_targets.Path = Path


def _retroarch_cfg_candidates(config: GamehubConfig | None = None) -> list[Path]:
    _sync_targets_module()
    return firmware_targets.retroarch_cfg_candidates_for_config(config)


def _resolve_retroarch_system_dirs(config: GamehubConfig | None = None) -> list[Path]:
    _sync_targets_module()
    return firmware_targets.resolve_retroarch_system_dirs(config)


def _pcsx2_ini_candidates(config: GamehubConfig | None = None) -> list[Path]:
    _sync_targets_module()
    return firmware_targets.pcsx2_ini_candidates(config)


def _resolve_pcsx2_bios_dirs(config: GamehubConfig | None = None) -> list[Path]:
    _sync_targets_module()
    return firmware_targets.resolve_pcsx2_bios_dirs(config)


def _resolve_dolphin_user_dirs(config: GamehubConfig | None = None) -> list[Path]:
    _sync_targets_module()
    return firmware_targets.resolve_dolphin_user_dirs(config)


def _target_dirs_for_system(system_name: str, config: GamehubConfig | None = None) -> list[Path]:
    _sync_targets_module()
    return firmware_targets.target_dirs_for_system(system_name, config)


def _default_pcsx2_ini_path(config: GamehubConfig | None = None) -> Path:
    override = None
    if config is not None:
        override = config.linux.pcsx2_ini_path
    if override is not None:
        return override.expanduser()

    prefer_flatpak = False
    if sys.platform.startswith("linux"):
        pcsx2_raw = resolve_emulator_executable("pcsx2").strip('"')
        pcsx2_exe = Path(pcsx2_raw)
        prefer_flatpak = is_flatpak_command(pcsx2_exe, PCSX2_FLATPAK_APP_ID) or (
            PCSX2_FLATPAK_APP_ID.casefold() in pcsx2_raw.casefold()
        )
        if prefer_flatpak:
            return linux_flatpak_pcsx2_root() / "inis" / "PCSX2.ini"

    for candidate in _pcsx2_ini_candidates(config=config):
        if candidate.exists():
            return candidate

    if sys.platform.startswith("linux"):
        if prefer_flatpak:
            return linux_flatpak_pcsx2_root() / "inis" / "PCSX2.ini"
        return Path.home() / ".config" / "PCSX2" / "inis" / "PCSX2.ini"

    candidates = _pcsx2_ini_candidates(config=config)
    if candidates:
        return candidates[0]
    return Path.home() / "Documents" / "PCSX2" / "inis" / "PCSX2.ini"


def _sha256(path: Path) -> str:
    return sha256_file(path)


def _copy_or_link(source: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and _sha256(destination) == _sha256(source):
        return "up_to_date"

    tmp = destination.with_name(f"{destination.name}.{uuid4().hex}.tmp")
    shutil.copy2(source, tmp)
    mode = "copied"
    replace_file(tmp, destination)
    return mode


def _sync_pcsx2_ini_module() -> None:
    pcsx2_ini.os = os
    pcsx2_ini.Path = Path
    pcsx2_ini.replace_file = replace_file


def _read_ini_lines(path: Path) -> list[str]:
    _sync_pcsx2_ini_module()
    return pcsx2_ini.read_ini_lines(path)


def _upsert_ini_key(lines: list[str], section: str, key: str, value: str) -> tuple[list[str], bool]:
    _sync_pcsx2_ini_module()
    return pcsx2_ini.upsert_ini_key(lines, section, key, value)


def _bootstrap_pcsx2_controllers(lines: list[str]) -> tuple[list[str], bool]:
    _sync_pcsx2_ini_module()
    return pcsx2_ini.bootstrap_pcsx2_controllers(lines)


def _write_ini_atomic(path: Path, lines: list[str]) -> None:
    _sync_pcsx2_ini_module()
    pcsx2_ini.write_ini_atomic(path, lines)


def _configure_pcsx2_runtime(
    config: GamehubConfig,
    dry_run: bool,
    verbose: bool,
    writer: Callable[[str], None],
) -> Path:
    override_bios_dir = config.linux.pcsx2_bios_dir.expanduser() if config.linux.pcsx2_bios_dir is not None else None
    pcsx2_raw = resolve_emulator_executable("pcsx2").strip('"')
    pcsx2_exe = Path(pcsx2_raw)
    prefer_flatpak = is_flatpak_command(pcsx2_exe, PCSX2_FLATPAK_APP_ID) or (
        PCSX2_FLATPAK_APP_ID.casefold() in pcsx2_raw.casefold()
    )
    if override_bios_dir is not None:
        bios_dir = override_bios_dir
    elif prefer_flatpak:
        bios_dir = linux_flatpak_pcsx2_root() / "bios"
    else:
        bios_dir = config.firmware_dir / "PS2"

    bios_dir_for_config = bios_dir.resolve(strict=False)
    ini_path = _default_pcsx2_ini_path(config=config)
    if dry_run:
        if verbose:
            writer(
                f"pcsx2\tdry-run\tconfigure\t{ini_path}\tbios={bios_dir_for_config}\tcontrollers={config.linux.pcsx2_controller_autoconfig}"
            )
        return bios_dir_for_config

    lines = _read_ini_lines(ini_path)
    lines, changed_ui = _upsert_ini_key(lines, "UI", "SetupWizardIncomplete", "false")
    lines, changed_bios = _upsert_ini_key(lines, "Folders", "Bios", str(bios_dir_for_config))
    changed_controllers = False
    if sys.platform.startswith("linux") and config.linux.pcsx2_controller_autoconfig:
        lines, changed_controllers = _bootstrap_pcsx2_controllers(lines)
    if changed_ui or changed_bios or changed_controllers or not ini_path.exists():
        _write_ini_atomic(ini_path, lines)
    bios_dir_for_config.mkdir(parents=True, exist_ok=True)
    if verbose:
        writer(
            f"pcsx2\tconfigured\t{ini_path}\tbios={bios_dir_for_config}\tcontrollers={config.linux.pcsx2_controller_autoconfig}"
        )
    return bios_dir_for_config


def deploy_firmware_to_emulators(
    config: GamehubConfig,
    index: LibraryIndex,
    dry_run: bool,
    verbose: bool,
    writer: Callable[[str], None] = print,
) -> None:
    requested = 0
    applied = 0
    skipped = 0
    has_ps2 = any(system.name == "PS2" for system in index.systems)
    ps2_bios_target: Path | None = None
    if has_ps2:
        ps2_bios_target = _configure_pcsx2_runtime(config=config, dry_run=dry_run, verbose=verbose, writer=writer)

    for system in index.systems:
        if system.name == "PS2":
            target_dirs = [ps2_bios_target] if ps2_bios_target is not None else []
        else:
            target_dirs = _target_dirs_for_system(system.name, config=config)
        if not target_dirs:
            continue
        for firmware in system.firmware:
            source = config.firmware_dir / system.name / firmware.filename
            for target_dir in target_dirs:
                destination = target_dir / firmware.filename
                requested += 1
                if not source.exists():
                    if verbose:
                        writer(f"firmware\tmissing-source\t{source}\t->\t{destination}")
                    skipped += 1
                    continue
                if dry_run:
                    if verbose:
                        writer(f"firmware\tdry-run\t{source}\t->\t{destination}")
                    continue
                result = _copy_or_link(source, destination)
                if verbose:
                    writer(f"firmware\t{result}\t{source}\t->\t{destination}")
                if result == "up_to_date":
                    skipped += 1
                else:
                    applied += 1

    if dry_run:
        if verbose and requested > 0:
            writer(f"Firmware deployment dry-run targets: {requested}")
        return
    if requested == 0:
        return
    writer(f"Firmware deployment: targets={requested} applied={applied} skipped={skipped}")
