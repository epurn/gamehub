from __future__ import annotations

import os
from importlib import import_module
from pathlib import Path, PurePosixPath
from typing import Callable, cast

from gamehub_common.models import SaveSpec

from .resolution import resolve_emulator_executable

_OS_NAME = os.name

_RETROARCH_FLATPAK_APP_ID = "org.libretro.RetroArch"
_PCSX2_FLATPAK_APP_ID = "net.pcsx2.PCSX2"
_DOLPHIN_FLATPAK_APP_ID = "org.DolphinEmu.dolphin-emu"
_AZAHAR_FLATPAK_APP_ID = "org.azahar_emu.Azahar"

_SYSTEM_DEFAULT_EMULATOR = {
    "GB": "retroarch",
    "GBA": "retroarch",
    "GBC": "retroarch",
    "GEN_MD": "retroarch",
    "N64": "retroarch",
    "NDS": "retroarch",
    "N3DS": "azahar",
    "NES": "retroarch",
    "PSX": "retroarch",
    "SNES": "retroarch",
    "GC": "dolphin",
    "WII": "dolphin",
    "PS2": "pcsx2",
}


def _normalized_local_path(value: str | Path) -> Path:
    helper = import_module("gamehub_cli.common.paths")
    normalizer = cast(Callable[[str | Path], Path], helper.normalized_local_path)
    return normalizer(value)


def default_emulator_for_system(system: str) -> str | None:
    return _SYSTEM_DEFAULT_EMULATOR.get(system.strip().upper())


def _parse_simple_kv_config(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    parsed: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or raw.startswith(";") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        parsed[key.strip().lower()] = value.strip().strip('"').strip("'")
    return parsed


def _retroarch_cfg_candidates(resolve_executable: Callable[[str], str]) -> tuple[Path, ...]:
    values: list[Path] = []

    if _OS_NAME == "nt":
        exe_raw = resolve_executable("retroarch").strip().strip('"')
        if exe_raw:
            exe_path = _normalized_local_path(exe_raw)
            if exe_path.exists():
                values.append(exe_path.parent / "retroarch.cfg")
        appdata = os.environ.get("APPDATA")
        if appdata:
            values.append(_normalized_local_path(appdata) / "RetroArch" / "retroarch.cfg")
    else:
        home = _normalized_local_path(Path.home())
        values.append(home / ".config" / "retroarch" / "retroarch.cfg")
        values.append(home / ".var" / "app" / _RETROARCH_FLATPAK_APP_ID / "config" / "retroarch" / "retroarch.cfg")

    deduped: list[Path] = []
    seen: set[Path] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return tuple(deduped)


def _is_flatpak_command(path_value: str | Path, app_id: str) -> bool:
    raw = str(path_value)
    normalized = raw.strip().strip('"').replace("\\", "/").casefold()
    app = app_id.casefold()
    return normalized.endswith(f"/{app}") or f"flatpak/exports/bin/{app}" in normalized


def _existing_dir(path: Path) -> Path | None:
    normalized = _normalized_local_path(path)
    return normalized if normalized.exists() else None


def _retroarch_save_root(resolve_executable: Callable[[str], str]) -> Path | None:
    resolved = resolve_executable("retroarch").strip().strip('"')
    if resolved and _is_flatpak_command(resolved, _RETROARCH_FLATPAK_APP_ID):
        home = _normalized_local_path(Path.home())
        return _existing_dir(home / ".var" / "app" / _RETROARCH_FLATPAK_APP_ID / "config" / "retroarch" / "saves")

    for cfg_path in _retroarch_cfg_candidates(resolve_executable=resolve_executable):
        cfg = _parse_simple_kv_config(cfg_path)
        save_dir = cfg.get("savefile_directory", "").strip()
        if save_dir and save_dir.casefold() != "default":
            return _existing_dir(_normalized_local_path(save_dir))
        portable = cfg_path.parent / "saves"
        existing = _existing_dir(portable)
        if existing is not None:
            return existing

    if _OS_NAME == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return _existing_dir(_normalized_local_path(appdata) / "RetroArch" / "saves")
        return None

    home = _normalized_local_path(Path.home())
    return _existing_dir(home / ".config" / "retroarch" / "saves")


def _pcsx2_save_root(resolve_executable: Callable[[str], str]) -> Path | None:
    resolved = resolve_executable("pcsx2").strip().strip('"')
    if resolved and _is_flatpak_command(resolved, _PCSX2_FLATPAK_APP_ID):
        home = _normalized_local_path(Path.home())
        return _existing_dir(home / ".var" / "app" / _PCSX2_FLATPAK_APP_ID / "config" / "PCSX2" / "memcards")

    if _OS_NAME == "nt":
        documents = os.environ.get("USERPROFILE")
        if not documents:
            return None
        return _existing_dir(_normalized_local_path(documents) / "Documents" / "PCSX2" / "memcards")

    home = _normalized_local_path(Path.home())
    return _existing_dir(home / ".config" / "PCSX2" / "memcards")


def _dolphin_data_root(resolve_executable: Callable[[str], str]) -> Path | None:
    resolved = resolve_executable("dolphin").strip().strip('"')
    if resolved and _is_flatpak_command(resolved, _DOLPHIN_FLATPAK_APP_ID):
        home = _normalized_local_path(Path.home())
        return _existing_dir(home / ".var" / "app" / _DOLPHIN_FLATPAK_APP_ID / "data" / "dolphin-emu")

    if _OS_NAME == "nt":
        documents = os.environ.get("USERPROFILE")
        if not documents:
            return None
        return _existing_dir(_normalized_local_path(documents) / "Documents" / "Dolphin Emulator")

    home = _normalized_local_path(Path.home())
    return _existing_dir(home / ".local" / "share" / "dolphin-emu")


def _dolphin_save_root(resolve_executable: Callable[[str], str]) -> Path | None:
    root = _dolphin_data_root(resolve_executable)
    if root is None:
        return None
    return _existing_dir(root / "GC")


def _azahar_save_root(resolve_executable: Callable[[str], str]) -> Path | None:
    resolved = resolve_executable("azahar").strip().strip('"')
    if resolved and _is_flatpak_command(resolved, _AZAHAR_FLATPAK_APP_ID):
        home = _normalized_local_path(Path.home())
        return _existing_dir(home / ".var" / "app" / _AZAHAR_FLATPAK_APP_ID / "data" / "azahar-emu" / "sdmc")

    if _OS_NAME == "nt":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None
        return _existing_dir(_normalized_local_path(appdata) / "Azahar" / "sdmc")

    home = _normalized_local_path(Path.home())
    return _existing_dir(home / ".local" / "share" / "azahar-emu" / "sdmc")


def resolve_local_save_destination(save: SaveSpec) -> Path | None:
    root = resolve_system_save_root(save.system)
    if root is None:
        return None
    parts = tuple(part for part in PurePosixPath(save.rel_path).parts if part not in {"", "."})
    if len(parts) < 5:
        return None
    suffix_parts = parts[4:]
    if save.kind in {"battery", "memory_card"}:
        return root / suffix_parts[-1]
    return root.joinpath(*suffix_parts)


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
    normalized = system.strip().upper()
    if normalized == "GC":
        root = _dolphin_data_root(resolve_executable)
        if root is None:
            return None
        return _existing_dir(root / "GC")
    if normalized == "WII":
        root = _dolphin_data_root(resolve_executable)
        if root is None:
            return None
        return _existing_dir(root / "Wii")
    default = default_emulator_for_system(normalized)
    if default is None:
        return None
    return resolve_emulator_save_root(default, resolve_executable=resolve_executable)
