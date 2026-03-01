from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable

from gamehub_cli.common.paths import normalized_local_path
from gamehub_cli.common.platform_paths import (
    AZAHAR_FLATPAK_APP_ID,
    DOLPHIN_FLATPAK_APP_ID,
    PCSX2_FLATPAK_APP_ID,
    RETROARCH_FLATPAK_APP_ID,
    is_flatpak_command,
    linux_flatpak_azahar_root,
    linux_flatpak_dolphin_root,
    linux_flatpak_pcsx2_root,
    linux_flatpak_retroarch_root,
    parse_simple_kv_config,
    retroarch_cfg_candidates,
)

from .resolution import resolve_emulator_executable

_OS_NAME = os.name
_SYS_PLATFORM = sys.platform

_SYSTEM_DEFAULT_EMULATOR = {
    "GB": "retroarch",
    "GBA": "retroarch",
    "GBC": "retroarch",
    "GEN_MD": "retroarch",
    "N64": "retroarch",
    "NDS": "retroarch",
    "NES": "retroarch",
    "PSX": "retroarch",
    "SNES": "retroarch",
    "GC": "dolphin",
    "WII": "dolphin",
    "PS2": "pcsx2",
}


def default_emulator_for_system(system: str) -> str | None:
    return _SYSTEM_DEFAULT_EMULATOR.get(system.strip().upper())


def _existing_dir(path: Path) -> Path | None:
    normalized = normalized_local_path(path)
    return normalized if normalized.exists() else None


def _retroarch_save_root(resolve_executable: Callable[[str], str]) -> Path | None:
    resolved = resolve_executable("retroarch").strip().strip('"')
    if resolved and is_flatpak_command(resolved, RETROARCH_FLATPAK_APP_ID):
        return _existing_dir(linux_flatpak_retroarch_root() / "saves")

    cfg_candidates = retroarch_cfg_candidates(resolve_emulator_executable=resolve_executable)
    for cfg_path in cfg_candidates:
        cfg = parse_simple_kv_config(cfg_path)
        save_dir = cfg.get("savefile_directory", "").strip()
        if save_dir and save_dir.casefold() != "default":
            return _existing_dir(normalized_local_path(save_dir))
        portable = cfg_path.parent / "saves"
        existing = _existing_dir(portable)
        if existing is not None:
            return existing

    if _OS_NAME == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return _existing_dir(normalized_local_path(appdata) / "RetroArch" / "saves")
        return None

    home = normalized_local_path(Path.home())
    return _existing_dir(home / ".config" / "retroarch" / "saves")


def _pcsx2_save_root(resolve_executable: Callable[[str], str]) -> Path | None:
    resolved = resolve_executable("pcsx2").strip().strip('"')
    if resolved and is_flatpak_command(resolved, PCSX2_FLATPAK_APP_ID):
        return _existing_dir(linux_flatpak_pcsx2_root() / "memcards")

    if _OS_NAME == "nt":
        documents = os.environ.get("USERPROFILE")
        if not documents:
            return None
        return _existing_dir(normalized_local_path(documents) / "Documents" / "PCSX2" / "memcards")

    home = normalized_local_path(Path.home())
    return _existing_dir(home / ".config" / "PCSX2" / "memcards")


def _dolphin_save_root(resolve_executable: Callable[[str], str]) -> Path | None:
    resolved = resolve_executable("dolphin").strip().strip('"')
    if resolved and is_flatpak_command(resolved, DOLPHIN_FLATPAK_APP_ID):
        return _existing_dir(linux_flatpak_dolphin_root() / "GC")

    if _OS_NAME == "nt":
        documents = os.environ.get("USERPROFILE")
        if not documents:
            return None
        return _existing_dir(normalized_local_path(documents) / "Documents" / "Dolphin Emulator" / "GC")

    home = normalized_local_path(Path.home())
    return _existing_dir(home / ".local" / "share" / "dolphin-emu" / "GC")


def _azahar_save_root(resolve_executable: Callable[[str], str]) -> Path | None:
    resolved = resolve_executable("azahar").strip().strip('"')
    if resolved and is_flatpak_command(resolved, AZAHAR_FLATPAK_APP_ID):
        return _existing_dir(linux_flatpak_azahar_root() / "sdmc")

    if _OS_NAME == "nt":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None
        return _existing_dir(normalized_local_path(appdata) / "Azahar" / "sdmc")

    home = normalized_local_path(Path.home())
    return _existing_dir(home / ".local" / "share" / "azahar-emu" / "sdmc")


def resolve_emulator_save_root(
    emulator: str,
    *,
    resolve_executable: Callable[[str], str] = resolve_emulator_executable,
) -> Path | None:
    name = emulator.strip().strip('"').lower()
    if not name:
        return None
    if name in {"retroarch"}:
        return _retroarch_save_root(resolve_executable)
    if name in {"pcsx2", "pcsx2-qt"}:
        return _pcsx2_save_root(resolve_executable)
    if name in {"dolphin", "dolphin-emu"}:
        return _dolphin_save_root(resolve_executable)
    if name in {"azahar", "azahar-qt"}:
        return _azahar_save_root(resolve_executable)
    return None


def resolve_system_save_root(
    system: str,
    *,
    resolve_executable: Callable[[str], str] = resolve_emulator_executable,
) -> Path | None:
    default = default_emulator_for_system(system)
    if default is None:
        return None
    return resolve_emulator_save_root(default, resolve_executable=resolve_executable)
