from __future__ import annotations

import os
from pathlib import Path
import sys

from .config import GamehubConfig
from .emulators import resolve_emulator_executable
from .platform_paths import (
    DOLPHIN_FLATPAK_APP_ID,
    PCSX2_FLATPAK_APP_ID,
    RETROARCH_FLATPAK_APP_ID,
    is_flatpak_command,
    linux_flatpak_dolphin_root,
    linux_flatpak_pcsx2_root,
    linux_flatpak_retroarch_root,
    parse_simple_kv_config,
    retroarch_cfg_candidates,
    unique_paths,
)


def _configured_path(config: GamehubConfig | None, setting_name: str) -> Path | None:
    if config is None:
        return None
    value = getattr(config.linux, setting_name, None)
    if value is None:
        return None
    return value.expanduser()


def retroarch_cfg_candidates_for_config(config: GamehubConfig | None = None) -> list[Path]:
    return retroarch_cfg_candidates(explicit_cfg_path=_configured_path(config, "retroarch_cfg_path"))


def resolve_retroarch_system_dirs(config: GamehubConfig | None = None) -> list[Path]:
    values: list[Path] = []
    system_override = _configured_path(config, "retroarch_system_dir")
    if system_override:
        values.append(system_override)

    for cfg_path in retroarch_cfg_candidates_for_config(config=config):
        parsed = parse_simple_kv_config(cfg_path)
        raw = parsed.get("system_directory")
        if not raw:
            continue
        if raw.lower() == "default":
            values.append(cfg_path.parent / "system")
            continue
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = cfg_path.parent / candidate
        values.append(candidate)

    retroarch_raw = resolve_emulator_executable("retroarch").strip('"')
    retroarch_exe = Path(retroarch_raw)
    prefer_flatpak = is_flatpak_command(retroarch_exe, RETROARCH_FLATPAK_APP_ID) or (
        RETROARCH_FLATPAK_APP_ID.casefold() in retroarch_raw.casefold()
    )
    if os.name == "nt" and retroarch_exe.exists():
        values.append(retroarch_exe.parent / "system")
    elif sys.platform.startswith("linux") and prefer_flatpak:
        values.append(linux_flatpak_retroarch_root() / "system")

    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        values.append(Path(appdata) / "RetroArch" / "system")
    home = Path.home()
    native = home / ".config" / "retroarch" / "system"
    flatpak = linux_flatpak_retroarch_root() / "system"
    if sys.platform.startswith("linux") and prefer_flatpak:
        values.append(flatpak)
        values.append(native)
    else:
        values.append(native)
        values.append(flatpak)
    return unique_paths(values)


def pcsx2_ini_candidates(config: GamehubConfig | None = None) -> list[Path]:
    values: list[Path] = []
    ini_override = _configured_path(config, "pcsx2_ini_path")
    if ini_override:
        values.append(ini_override)
    user_profile = os.environ.get("USERPROFILE")
    if os.name == "nt" and user_profile:
        values.append(Path(user_profile) / "Documents" / "PCSX2" / "inis" / "PCSX2.ini")
        values.append(Path(user_profile) / "Documents" / "PCSX2" / "PCSX2.ini")
    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        values.append(Path(appdata) / "PCSX2" / "inis" / "PCSX2.ini")
        values.append(Path(appdata) / "PCSX2" / "PCSX2.ini")
    home = Path.home()
    values.append(home / "Documents" / "PCSX2" / "inis" / "PCSX2.ini")
    values.append(home / "Documents" / "PCSX2" / "PCSX2.ini")
    values.append(home / ".config" / "PCSX2" / "inis" / "PCSX2.ini")
    values.append(home / ".config" / "PCSX2" / "PCSX2.ini")
    values.append(linux_flatpak_pcsx2_root() / "inis" / "PCSX2.ini")
    return unique_paths(values)


def resolve_pcsx2_bios_dirs(config: GamehubConfig | None = None) -> list[Path]:
    values: list[Path] = []
    bios_override = _configured_path(config, "pcsx2_bios_dir")
    if bios_override:
        values.append(bios_override)

    for ini_path in pcsx2_ini_candidates(config=config):
        parsed = parse_simple_kv_config(ini_path)
        bios_value = parsed.get("bios") or parsed.get("folders.bios")
        if not bios_value:
            continue
        candidate = Path(bios_value)
        if not candidate.is_absolute():
            root = ini_path.parent.parent if ini_path.parent.name.lower() == "inis" else ini_path.parent
            candidate = root / candidate
        values.append(candidate)

    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        values.append(Path(appdata) / "PCSX2" / "bios")
    user_profile = os.environ.get("USERPROFILE")
    if os.name == "nt" and user_profile:
        values.append(Path(user_profile) / "Documents" / "PCSX2" / "bios")
    home = Path.home()
    native = home / ".config" / "PCSX2" / "bios"
    flatpak = linux_flatpak_pcsx2_root() / "bios"
    docs = home / "Documents" / "PCSX2" / "bios"
    pcsx2_raw = resolve_emulator_executable("pcsx2").strip('"')
    pcsx2_exe = Path(pcsx2_raw)
    prefer_flatpak = is_flatpak_command(pcsx2_exe, PCSX2_FLATPAK_APP_ID) or (
        PCSX2_FLATPAK_APP_ID.casefold() in pcsx2_raw.casefold()
    )
    if sys.platform.startswith("linux") and prefer_flatpak:
        values.extend((flatpak, native, docs))
    else:
        values.extend((docs, native, flatpak))
    return unique_paths(values)


def resolve_dolphin_user_dirs(config: GamehubConfig | None = None) -> list[Path]:
    values: list[Path] = []
    user_override = _configured_path(config, "dolphin_user_path")
    if user_override:
        values.append(user_override)
        return unique_paths(values)

    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        values.append(Path(appdata) / "Dolphin Emulator")

    home = Path.home()
    legacy = home / ".dolphin-emu"
    if legacy.exists():
        values.append(legacy)
    native = home / ".local" / "share" / "dolphin-emu"
    flatpak = linux_flatpak_dolphin_root()
    existing_linux = [path for path in (flatpak, native, legacy) if path.exists()]
    if existing_linux:
        values.extend(existing_linux)
        return unique_paths(values)

    dolphin_raw = resolve_emulator_executable("dolphin").strip('"')
    dolphin_exe = Path(dolphin_raw)
    if is_flatpak_command(dolphin_exe, DOLPHIN_FLATPAK_APP_ID) or (
        DOLPHIN_FLATPAK_APP_ID.casefold() in dolphin_raw.casefold()
    ):
        values.append(flatpak)
    else:
        values.append(native)
    return unique_paths(values)


def target_dirs_for_system(system_name: str, config: GamehubConfig | None = None) -> list[Path]:
    if system_name == "PSX":
        return resolve_retroarch_system_dirs(config=config)
    if system_name == "PS2":
        return resolve_pcsx2_bios_dirs(config=config)
    if system_name == "Wii":
        return [path / "Wii" for path in resolve_dolphin_user_dirs(config=config)]
    if system_name == "GC":
        return [path / "GC" for path in resolve_dolphin_user_dirs(config=config)]
    return []


def default_pcsx2_ini_path(config: GamehubConfig | None = None) -> Path:
    override = _configured_path(config, "pcsx2_ini_path")
    if override is not None:
        return override

    if sys.platform.startswith("linux"):
        pcsx2_raw = resolve_emulator_executable("pcsx2").strip('"')
        pcsx2_exe = Path(pcsx2_raw)
        if is_flatpak_command(pcsx2_exe, PCSX2_FLATPAK_APP_ID) or (
            PCSX2_FLATPAK_APP_ID.casefold() in pcsx2_raw.casefold()
        ):
            return linux_flatpak_pcsx2_root() / "inis" / "PCSX2.ini"

    candidates = pcsx2_ini_candidates(config=config)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    if sys.platform.startswith("linux"):
        pcsx2_raw = resolve_emulator_executable("pcsx2").strip('"')
        pcsx2_exe = Path(pcsx2_raw)
        if is_flatpak_command(pcsx2_exe, PCSX2_FLATPAK_APP_ID) or (
            PCSX2_FLATPAK_APP_ID.casefold() in pcsx2_raw.casefold()
        ):
            return linux_flatpak_pcsx2_root() / "inis" / "PCSX2.ini"
        return Path.home() / ".config" / "PCSX2" / "inis" / "PCSX2.ini"
    if candidates:
        return candidates[0]
    return Path.home() / "Documents" / "PCSX2" / "inis" / "PCSX2.ini"
