from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Callable

from ..common.config import GamehubConfig
from ..common.fsops import backup_existing_file
from ..common.platform_paths import PCSX2_FLATPAK_APP_ID, is_flatpak_command, linux_flatpak_pcsx2_root
from ..emulators import resolve_emulator_executable
from .pcsx2_ini import read_ini_lines, upsert_ini_key, write_ini_atomic
from .targets import default_pcsx2_ini_path, resolve_pcsx2_bios_dirs

_SYS_PLATFORM = sys.platform
logger = logging.getLogger(__name__)


def configure_pcsx2_runtime(
    config: GamehubConfig,
    dry_run: bool,
    verbose: bool,
    writer: Callable[[str], None],
) -> Path:
    if _SYS_PLATFORM == "darwin":
        bios_candidates = resolve_pcsx2_bios_dirs(config=config)
        bios_dir = bios_candidates[0] if bios_candidates else config.firmware_dir / "PS2"
    else:
        override_bios_dir = (
            config.linux.pcsx2_bios_dir.expanduser() if config.linux.pcsx2_bios_dir is not None else None
        )
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
    ini_path = default_pcsx2_ini_path(config=config)
    if dry_run:
        if verbose:
            writer(f"pcsx2\tdry-run\tconfigure\t{ini_path}\tbios={bios_dir_for_config}")
        return bios_dir_for_config

    lines = read_ini_lines(ini_path)
    lines, changed_ui = upsert_ini_key(lines, "UI", "SetupWizardIncomplete", "false")
    lines, changed_bios = upsert_ini_key(lines, "Folders", "Bios", str(bios_dir_for_config))
    if changed_ui or changed_bios or not ini_path.exists():
        if ini_path.exists():
            backup_result = backup_existing_file(ini_path, keep_limit=config.backups.keep_limit)
            if backup_result.created_path is not None:
                logger.info("pcsx2 runtime backup created path=%s backup=%s", ini_path, backup_result.created_path)
            for pruned_path in backup_result.pruned_paths:
                logger.info("pcsx2 runtime backup pruned path=%s pruned_backup=%s", ini_path, pruned_path)
        write_ini_atomic(ini_path, lines)
        logger.info("pcsx2 runtime config updated path=%s bios=%s", ini_path, bios_dir_for_config)
    bios_dir_for_config.mkdir(parents=True, exist_ok=True)
    if verbose:
        writer(f"pcsx2\tconfigured\t{ini_path}\tbios={bios_dir_for_config}")
    return bios_dir_for_config
