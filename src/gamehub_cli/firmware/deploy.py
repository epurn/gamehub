from __future__ import annotations

from pathlib import Path
from typing import Callable

from gamehub_common.models import LibraryIndex

from ..common.config import GamehubConfig
from .deploy_copy import copy_or_link
from .runtime_azahar import configure_azahar_runtime
from .runtime_dolphin import configure_dolphin_runtime
from .runtime_pcsx2 import configure_pcsx2_runtime
from .runtime_retroarch import configure_retroarch_runtime
from .targets import target_dirs_for_system

_RETROARCH_SYSTEM_NAMES = {"GB", "GBA", "GBC", "GEN_MD", "N64", "NDS", "NES", "PSX", "SNES"}


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
    has_retroarch = any(system.name in _RETROARCH_SYSTEM_NAMES for system in index.systems)
    if has_retroarch:
        configure_retroarch_runtime(
            config=config,
            dry_run=dry_run,
            verbose=verbose,
            writer=writer,
        )
    has_ps2 = any(system.name == "PS2" for system in index.systems)
    ps2_bios_target: Path | None = None
    if has_ps2:
        ps2_bios_target = configure_pcsx2_runtime(config=config, dry_run=dry_run, verbose=verbose, writer=writer)
    has_dolphin = any(system.name in {"GC", "Wii"} for system in index.systems)
    if has_dolphin:
        configure_dolphin_runtime(config=config, dry_run=dry_run, verbose=verbose, writer=writer)
    has_n3ds = any(system.name == "N3DS" for system in index.systems)
    if has_n3ds:
        configure_azahar_runtime(config=config, dry_run=dry_run, verbose=verbose, writer=writer)

    for system in index.systems:
        if system.name == "PS2":
            target_dirs = [ps2_bios_target] if ps2_bios_target is not None else []
        else:
            target_dirs = target_dirs_for_system(system.name, config=config)
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
                result = copy_or_link(source, destination)
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
