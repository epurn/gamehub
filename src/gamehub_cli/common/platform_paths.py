from __future__ import annotations

import os
import plistlib
from pathlib import Path, PosixPath, WindowsPath
from typing import Callable, Iterable

RETROARCH_FLATPAK_APP_ID = "org.libretro.RetroArch"
PCSX2_FLATPAK_APP_ID = "net.pcsx2.PCSX2"
DOLPHIN_FLATPAK_APP_ID = "org.DolphinEmu.dolphin-emu"
AZAHAR_FLATPAK_APP_ID = "org.azahar_emu.Azahar"
_OS_NAME = os.name

try:
    _HOST_PATH_CLS = type(Path.cwd())
except Exception:
    _HOST_PATH_CLS = WindowsPath if _OS_NAME == "nt" else PosixPath


def _safe_home_path() -> Path:
    try:
        return _host_path(str(Path.home()))
    except Exception:
        pass
    for raw in (os.path.expanduser("~"), os.environ.get("USERPROFILE", ""), os.environ.get("HOME", "")):
        value = str(raw).strip()
        if not value or value == "~":
            continue
        return _host_path(value)
    return _host_path(os.getcwd())


def _host_path(raw: str) -> Path:
    return _HOST_PATH_CLS(raw)


def linux_flatpak_retroarch_root() -> Path:
    return _safe_home_path() / ".var" / "app" / RETROARCH_FLATPAK_APP_ID / "config" / "retroarch"


def linux_flatpak_pcsx2_root() -> Path:
    return _safe_home_path() / ".var" / "app" / PCSX2_FLATPAK_APP_ID / "config" / "PCSX2"


def linux_flatpak_dolphin_root() -> Path:
    return _safe_home_path() / ".var" / "app" / DOLPHIN_FLATPAK_APP_ID / "data" / "dolphin-emu"


def linux_flatpak_dolphin_config_root() -> Path:
    return _safe_home_path() / ".var" / "app" / DOLPHIN_FLATPAK_APP_ID / "config" / "dolphin-emu"


def linux_flatpak_azahar_root() -> Path:
    return _safe_home_path() / ".var" / "app" / AZAHAR_FLATPAK_APP_ID / "data" / "azahar-emu"


def linux_flatpak_azahar_config_root() -> Path:
    return _safe_home_path() / ".var" / "app" / AZAHAR_FLATPAK_APP_ID / "config" / "azahar-emu"


def macos_application_support_root() -> Path:
    return _safe_home_path() / "Library" / "Application Support"


def macos_user_applications_dir() -> Path:
    return _safe_home_path() / "Applications"


def macos_system_applications_dir() -> Path:
    return _host_path("/Applications")


def macos_retroarch_root() -> Path:
    return macos_application_support_root() / "RetroArch"


def macos_pcsx2_root() -> Path:
    return macos_application_support_root() / "PCSX2"


def macos_dolphin_root() -> Path:
    return macos_application_support_root() / "Dolphin"


def macos_azahar_root() -> Path:
    return macos_application_support_root() / "Azahar"


def macos_application_bundle_candidates(bundle_names: Iterable[str]) -> list[Path]:
    normalized_names: list[str] = []
    for bundle_name in bundle_names:
        value = str(bundle_name).strip()
        if not value:
            continue
        if not value.lower().endswith(".app"):
            value = f"{value}.app"
        normalized_names.append(value)

    values: list[Path] = []
    for applications_dir in (macos_user_applications_dir(), macos_system_applications_dir()):
        for bundle_name in normalized_names:
            values.append(applications_dir / bundle_name)
    return unique_paths(values)


def resolve_macos_app_bundle_executable(bundle_path: Path) -> Path | None:
    candidate = bundle_path.expanduser()
    if candidate.suffix.casefold() != ".app" or not candidate.is_dir():
        return None

    info_plist = candidate / "Contents" / "Info.plist"
    if not info_plist.is_file():
        return None

    try:
        with info_plist.open("rb") as handle:
            plist = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None

    executable_name = plist.get("CFBundleExecutable")
    if not isinstance(executable_name, str):
        return None
    executable_name = executable_name.strip().replace("\\", "/")
    if not executable_name or "/" in executable_name:
        return None

    executable_path = candidate / "Contents" / "MacOS" / executable_name
    if executable_path.is_file():
        return executable_path
    return None


def is_flatpak_command(path_value: str | Path, app_id: str) -> bool:
    if isinstance(path_value, Path):
        raw = path_value.as_posix()
    else:
        raw = str(path_value)
    normalized = raw.strip().strip('"').replace("\\", "/").casefold()
    app = app_id.casefold()
    return normalized.endswith(f"/{app}") or f"flatpak/exports/bin/{app}" in normalized


def unique_paths(values: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[Path] = set()
    for value in values:
        candidate = value.expanduser()
        if candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)
    return result


def parse_simple_kv_config(path: Path) -> dict[str, str]:
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


def retroarch_cfg_candidates(
    explicit_cfg_path: Path | None = None,
    resolve_emulator_executable: Callable[[str], str] | None = None,
    os_name: str | None = None,
    sys_platform: str | None = None,
) -> list[Path]:
    values: list[Path] = []
    current_os_name = _OS_NAME if os_name is None else os_name
    current_sys_platform = sys_platform if sys_platform is not None else ""
    if explicit_cfg_path is not None:
        values.append(explicit_cfg_path.expanduser())

    if current_os_name == "nt":
        if resolve_emulator_executable is not None:
            exe_raw = resolve_emulator_executable("retroarch").strip('"')
            if exe_raw:
                exe_path = _host_path(exe_raw)
                if exe_path.exists():
                    values.append(exe_path.parent / "retroarch.cfg")

    appdata = os.environ.get("APPDATA")
    if current_os_name == "nt" and appdata:
        values.append(_host_path(appdata) / "RetroArch" / "retroarch.cfg")

    if current_os_name != "nt":
        if current_sys_platform == "darwin":
            values.append(macos_retroarch_root() / "retroarch.cfg")
            return unique_paths(values)

        home = _safe_home_path()
        native_cfg = home / ".config" / "retroarch" / "retroarch.cfg"
        flatpak_cfg = linux_flatpak_retroarch_root() / "retroarch.cfg"
        prefer_flatpak = False
        if resolve_emulator_executable is not None:
            try:
                retroarch_raw = resolve_emulator_executable("retroarch").strip().strip('"')
            except Exception:
                retroarch_raw = ""
            if retroarch_raw and is_flatpak_command(retroarch_raw, RETROARCH_FLATPAK_APP_ID):
                prefer_flatpak = True
        if prefer_flatpak:
            values.append(flatpak_cfg)
            values.append(native_cfg)
        else:
            values.append(native_cfg)
            values.append(flatpak_cfg)
    return unique_paths(values)
