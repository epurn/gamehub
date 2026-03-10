from __future__ import annotations

import os
import sys
from pathlib import Path, PosixPath, WindowsPath

from ..common.config import GamehubConfig
from ..common.platform_paths import (
    AZAHAR_FLATPAK_APP_ID,
    DOLPHIN_FLATPAK_APP_ID,
    PCSX2_FLATPAK_APP_ID,
    RETROARCH_FLATPAK_APP_ID,
    is_flatpak_command,
    linux_flatpak_azahar_root,
    linux_flatpak_dolphin_config_root,
    linux_flatpak_dolphin_root,
    linux_flatpak_pcsx2_root,
    linux_flatpak_retroarch_root,
    macos_azahar_root,
    macos_dolphin_root,
    macos_pcsx2_root,
    macos_retroarch_root_candidates,
    parse_simple_kv_config,
    retroarch_cfg_candidates,
    unique_paths,
)
from ..emulators import resolve_emulator_executable

try:
    _HOST_PATH_CLS = type(Path.cwd())
except Exception:
    _HOST_PATH_CLS = WindowsPath if os.name == "nt" else PosixPath


def _safe_home_path() -> Path:
    try:
        home = _host_path(str(Path.home()))
        if os.name != "nt":
            try:
                return _host_path(str(home.resolve(strict=False)))
            except Exception:
                return home
        return home
    except Exception:
        pass
    for raw in (os.path.expanduser("~"), os.environ.get("USERPROFILE", ""), os.environ.get("HOME", "")):
        value = str(raw).strip()
        if not value or value == "~":
            continue
        home = _host_path(value)
        if os.name != "nt":
            try:
                return _host_path(str(home.resolve(strict=False)))
            except Exception:
                return home
        return home
    return _host_path(os.getcwd())


def _host_path(raw: str) -> Path:
    return _HOST_PATH_CLS(raw)


def _path_with_tilde_expanded(raw: str) -> Path:
    value = raw.strip()
    if value == "~":
        return _safe_home_path()
    if value.startswith("~/") or value.startswith("~\\"):
        return _safe_home_path() / value[2:]
    return _host_path(value)


def _configured_path(config: GamehubConfig | None, setting_name: str) -> Path | None:
    if config is None:
        return None
    if sys.platform == "darwin":
        macos_value = getattr(config.macos, setting_name, None)
        if isinstance(macos_value, Path):
            return macos_value.expanduser()
        return None
    value = getattr(config.linux, setting_name, None)
    if not isinstance(value, Path):
        return None
    return value.expanduser()


def _windows_dolphin_user_dir_candidates() -> list[Path]:
    values: list[Path] = []
    dolphin_raw = resolve_emulator_executable("dolphin").strip('"')
    dolphin_exe = _host_path(dolphin_raw) if dolphin_raw else None
    if dolphin_exe is not None and dolphin_exe.exists():
        values.append(dolphin_exe.parent / "User")
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        values.append(_host_path(user_profile) / "Documents" / "Dolphin Emulator")
    appdata = os.environ.get("APPDATA")
    if appdata:
        values.append(_host_path(appdata) / "Dolphin Emulator")
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        values.append(_host_path(local_app_data) / "Dolphin Emulator")
    return unique_paths(values)


def _windows_dolphin_install_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return _host_path(local_app_data) / "Programs" / "Dolphin"
    return _safe_home_path() / "AppData" / "Local" / "Programs" / "Dolphin"


def _windows_dolphin_preferred_user_dir_from_install() -> Path | None:
    dolphin_raw = resolve_emulator_executable("dolphin").strip('"')
    if not dolphin_raw:
        return None
    dolphin_exe = _host_path(dolphin_raw)
    if not dolphin_exe.exists():
        return None
    install_root = _windows_dolphin_install_root()
    try:
        dolphin_exe = dolphin_exe.resolve()
    except OSError:
        dolphin_exe = dolphin_exe
    try:
        install_root = install_root.resolve()
    except OSError:
        install_root = install_root
    if install_root in dolphin_exe.parents:
        return install_root / "User"
    return None


def _select_existing_dolphin_user_dir(candidates: list[Path]) -> Path | None:
    if not candidates:
        return None
    config_files = ("Dolphin.ini", "GCPadNew.ini", "WiimoteNew.ini", "Hotkeys.ini")
    for candidate in candidates:
        config_root = candidate / "Config"
        if any((config_root / filename).exists() for filename in config_files):
            return candidate
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def retroarch_cfg_candidates_for_config(config: GamehubConfig | None = None) -> list[Path]:
    return retroarch_cfg_candidates(
        explicit_cfg_path=_configured_path(config, "retroarch_cfg_path"),
        resolve_emulator_executable=resolve_emulator_executable,
        os_name=os.name,
        sys_platform=sys.platform,
    )


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
        if os.name == "nt" and raw.startswith((":\\", ":/")):
            values.append(cfg_path.parent / raw[2:])
            continue
        candidate = _path_with_tilde_expanded(raw)
        if not candidate.is_absolute():
            candidate = cfg_path.parent / candidate
        values.append(candidate)

    retroarch_raw = resolve_emulator_executable("retroarch").strip('"')
    retroarch_exe = _host_path(retroarch_raw)
    prefer_flatpak = is_flatpak_command(retroarch_exe, RETROARCH_FLATPAK_APP_ID) or (
        RETROARCH_FLATPAK_APP_ID.casefold() in retroarch_raw.casefold()
    )
    # Keep portable Windows RetroArch layouts working even when tests run on non-Windows hosts.
    if retroarch_exe.exists() and (os.name == "nt" or retroarch_exe.name.casefold() == "retroarch.exe"):
        values.append(retroarch_exe.parent / "system")
    elif sys.platform.startswith("linux") and prefer_flatpak:
        values.append(linux_flatpak_retroarch_root() / "system")

    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        values.append(_host_path(appdata) / "RetroArch" / "system")
    if sys.platform == "darwin":
        values.append(macos_retroarch_root_candidates()[0] / "system")
        return unique_paths(values)
    home = _safe_home_path()
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
        values.append(_host_path(user_profile) / "Documents" / "PCSX2" / "inis" / "PCSX2.ini")
        values.append(_host_path(user_profile) / "Documents" / "PCSX2" / "PCSX2.ini")
    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        values.append(_host_path(appdata) / "PCSX2" / "inis" / "PCSX2.ini")
        values.append(_host_path(appdata) / "PCSX2" / "PCSX2.ini")
    if sys.platform == "darwin":
        values.append(macos_pcsx2_root() / "inis" / "PCSX2.ini")
        values.append(macos_pcsx2_root() / "PCSX2.ini")
        return unique_paths(values)
    home = _safe_home_path()
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
        candidate = _path_with_tilde_expanded(bios_value)
        if not candidate.is_absolute():
            root = ini_path.parent.parent if ini_path.parent.name.lower() == "inis" else ini_path.parent
            candidate = root / candidate
        values.append(candidate)

    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        values.append(_host_path(appdata) / "PCSX2" / "bios")
    user_profile = os.environ.get("USERPROFILE")
    if os.name == "nt" and user_profile:
        values.append(_host_path(user_profile) / "Documents" / "PCSX2" / "bios")
    if sys.platform == "darwin":
        values.append(macos_pcsx2_root() / "bios")
        return unique_paths(values)
    home = _safe_home_path()
    native = home / ".config" / "PCSX2" / "bios"
    flatpak = linux_flatpak_pcsx2_root() / "bios"
    docs = home / "Documents" / "PCSX2" / "bios"
    pcsx2_raw = resolve_emulator_executable("pcsx2").strip('"')
    pcsx2_exe = _host_path(pcsx2_raw)
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

    if os.name == "nt":
        install_user_dir = _windows_dolphin_preferred_user_dir_from_install()
        if install_user_dir is not None:
            return [install_user_dir]
        candidates = _windows_dolphin_user_dir_candidates()
        selected = _select_existing_dolphin_user_dir(candidates)
        if selected is not None:
            return [selected]
        return candidates[:1]

    if sys.platform == "darwin":
        values.append(macos_dolphin_root())
        return unique_paths(values)

    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        values.append(_host_path(appdata) / "Dolphin Emulator")

    home = _safe_home_path()
    native = home / ".local" / "share" / "dolphin-emu"
    flatpak = linux_flatpak_dolphin_root()
    existing_linux = [path for path in (flatpak, native) if path.exists()]
    if existing_linux:
        values.extend(existing_linux)
        return unique_paths(values)

    dolphin_raw = resolve_emulator_executable("dolphin").strip('"')
    dolphin_exe = _host_path(dolphin_raw)
    if is_flatpak_command(dolphin_exe, DOLPHIN_FLATPAK_APP_ID) or (
        DOLPHIN_FLATPAK_APP_ID.casefold() in dolphin_raw.casefold()
    ):
        values.append(flatpak)
    else:
        values.append(native)
    return unique_paths(values)


def resolve_dolphin_runtime_user_dir(config: GamehubConfig | None = None) -> Path:
    user_override = _configured_path(config, "dolphin_user_path")
    if user_override:
        return user_override

    if os.name == "nt":
        install_user_dir = _windows_dolphin_preferred_user_dir_from_install()
        if install_user_dir is not None:
            return install_user_dir
        candidates = _windows_dolphin_user_dir_candidates()
        selected = _select_existing_dolphin_user_dir(candidates)
        if selected is not None:
            return selected
        if candidates:
            return candidates[0]
        appdata = os.environ.get("APPDATA")
        if appdata:
            return _host_path(appdata) / "Dolphin Emulator"

    if sys.platform == "darwin":
        return macos_dolphin_root()

    home = _safe_home_path()
    if sys.platform.startswith("linux"):
        flatpak_export_user = home / ".local" / "share" / "flatpak" / "exports" / "bin" / DOLPHIN_FLATPAK_APP_ID
        flatpak_export_system = _host_path("/var/lib/flatpak/exports/bin") / DOLPHIN_FLATPAK_APP_ID
        flatpak_data = linux_flatpak_dolphin_root()
        flatpak_config = linux_flatpak_dolphin_config_root()
        if (
            flatpak_data.exists()
            or flatpak_config.exists()
            or flatpak_export_user.exists()
            or flatpak_export_system.exists()
        ):
            return flatpak_data
    if sys.platform.startswith("linux"):
        return home / ".local" / "share" / "dolphin-emu"
    return home / ".local" / "share" / "dolphin-emu"


def resolve_dolphin_config_dirs(config: GamehubConfig | None = None) -> list[Path]:
    values: list[Path] = []
    user_override = _configured_path(config, "dolphin_user_path")
    if user_override:
        values.append(user_override)
        return unique_paths(values)

    runtime = resolve_dolphin_runtime_user_dir(config=config)
    values.append(runtime)
    if os.name == "nt":
        return unique_paths(values)
    if sys.platform == "darwin":
        return unique_paths(values)

    home = _safe_home_path()
    native = home / ".config" / "dolphin-emu"
    native_data = home / ".local" / "share" / "dolphin-emu"
    flatpak = linux_flatpak_dolphin_config_root()
    existing_linux = [path for path in (flatpak, native, native_data) if path.exists()]
    if existing_linux:
        values.extend(existing_linux)
        return unique_paths(values)

    dolphin_raw = resolve_emulator_executable("dolphin").strip('"')
    dolphin_exe = _host_path(dolphin_raw)
    if is_flatpak_command(dolphin_exe, DOLPHIN_FLATPAK_APP_ID) or (
        DOLPHIN_FLATPAK_APP_ID.casefold() in dolphin_raw.casefold()
    ):
        values.append(flatpak)
    else:
        values.append(native)
        values.append(native_data)
    return unique_paths(values)


def resolve_azahar_user_dirs(config: GamehubConfig | None = None) -> list[Path]:
    values: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        values.append(_host_path(appdata) / "Azahar")
        return unique_paths(values)
    if sys.platform == "darwin":
        values.append(macos_azahar_root())
        return unique_paths(values)

    home = _safe_home_path()
    native = home / ".local" / "share" / "azahar"
    flatpak = linux_flatpak_azahar_root()
    existing_linux = [path for path in (flatpak, native) if path.exists()]
    if existing_linux:
        values.extend(existing_linux)
        return unique_paths(values)

    azahar_raw = resolve_emulator_executable("azahar").strip('"')
    azahar_exe = _host_path(azahar_raw)
    if is_flatpak_command(azahar_exe, AZAHAR_FLATPAK_APP_ID) or (
        AZAHAR_FLATPAK_APP_ID.casefold() in azahar_raw.casefold()
    ):
        values.append(flatpak)
    else:
        values.append(native)
        values.append(flatpak)
    return unique_paths(values)


def resolve_azahar_runtime_user_dir(config: GamehubConfig | None = None) -> Path:
    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        return _host_path(appdata) / "Azahar"
    if sys.platform == "darwin":
        return macos_azahar_root()

    home = _safe_home_path()
    flatpak_export_user = home / ".local" / "share" / "flatpak" / "exports" / "bin" / AZAHAR_FLATPAK_APP_ID
    flatpak_export_system = _host_path("/var/lib/flatpak/exports/bin") / AZAHAR_FLATPAK_APP_ID
    flatpak_data = linux_flatpak_azahar_root()
    if flatpak_data.exists() or flatpak_export_user.exists() or flatpak_export_system.exists():
        return flatpak_data
    return home / ".local" / "share" / "azahar"


def target_dirs_for_system(system_name: str, config: GamehubConfig | None = None) -> list[Path]:
    if system_name == "PSX":
        return resolve_retroarch_system_dirs(config=config)
    if system_name == "PS2":
        return resolve_pcsx2_bios_dirs(config=config)
    if system_name == "Wii":
        return [resolve_dolphin_runtime_user_dir(config=config) / "Wii"]
    if system_name == "GC":
        return [resolve_dolphin_runtime_user_dir(config=config) / "GC"]
    return []


def default_pcsx2_ini_path(config: GamehubConfig | None = None) -> Path:
    override = _configured_path(config, "pcsx2_ini_path")
    if override is not None:
        return override

    if sys.platform == "darwin":
        candidates = pcsx2_ini_candidates(config=config)
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return macos_pcsx2_root() / "inis" / "PCSX2.ini"

    if sys.platform.startswith("linux"):
        pcsx2_raw = resolve_emulator_executable("pcsx2").strip('"')
        pcsx2_exe = _host_path(pcsx2_raw)
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
        pcsx2_exe = _host_path(pcsx2_raw)
        if is_flatpak_command(pcsx2_exe, PCSX2_FLATPAK_APP_ID) or (
            PCSX2_FLATPAK_APP_ID.casefold() in pcsx2_raw.casefold()
        ):
            return linux_flatpak_pcsx2_root() / "inis" / "PCSX2.ini"
        return _safe_home_path() / ".config" / "PCSX2" / "inis" / "PCSX2.ini"
    if candidates:
        return candidates[0]
    return _safe_home_path() / "Documents" / "PCSX2" / "inis" / "PCSX2.ini"
