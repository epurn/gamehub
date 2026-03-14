from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any, Iterable

from gamehub_common.models import LibraryIndex

from ..common.platform_paths import (
    macos_application_bundle_candidates,
    macos_user_applications_dir,
    resolve_macos_app_bundle_executable,
)

winreg: ModuleType | None
try:
    import winreg as _winreg
except ModuleNotFoundError:  # pragma: no cover
    winreg = None
else:
    winreg = _winreg

_FLATPAK_APP_IDS = {
    "retroarch": "org.libretro.RetroArch",
    "pcsx2": "net.pcsx2.PCSX2",
    "dolphin": "org.DolphinEmu.dolphin-emu",
    "azahar": "org.azahar_emu.Azahar",
}

_EMULATOR_COMMAND_ALIASES = {
    "retroarch": ("retroarch",),
    "pcsx2": ("pcsx2", "pcsx2-qt"),
    "dolphin": ("dolphin", "dolphin-emu"),
    "azahar": ("azahar", "azahar-qt"),
}

_MACOS_APP_BUNDLE_NAMES = {
    "retroarch": ("RetroArch.app",),
    "pcsx2": ("PCSX2.app",),
    "dolphin": ("Dolphin.app", "Dolphin Emulator.app"),
    "azahar": ("Azahar.app",),
}
_MACH_O_ARCH_RE = re.compile(r"\b(arm64e|arm64|x86_64|i386)\b")
_MACOS_ARCH_EXECUTABLE = "/usr/bin/arch"
_MACOS_TRUE_EXECUTABLE = "/usr/bin/true"

_HOST_PATH_TYPE = type(Path.cwd())
_OS_NAME = os.name
_SYS_PLATFORM = sys.platform
_MACOS_DISABLE_PCSX2_ROSETTA = False


@dataclass(frozen=True)
class _MacOSExecutablePolicy:
    allowed: bool
    preference: int
    reason: str | None = None
    architectures: tuple[str, ...] = ()


def _safe_path(value: str) -> Path:
    # Always construct paths using the host's concrete path class so tests that
    # monkeypatch os.name/sys.platform (for branch simulation) do not force
    # unsupported WindowsPath/PosixPath instantiation on the current runtime.
    normalized = value.replace("\\", "/")
    return _HOST_PATH_TYPE(normalized)


def _command_candidates(emulator_value: str) -> tuple[str, ...]:
    normalized = emulator_value.strip().strip('"')
    if not normalized:
        return ()
    lowered = normalized.lower()
    aliases = _EMULATOR_COMMAND_ALIASES.get(lowered)
    if aliases:
        return aliases
    return (normalized,)


def _canonical_emulator_name(emulator_value: str) -> str:
    raw = emulator_value.strip().strip('"').lower()
    if not raw:
        return ""
    if raw in _EMULATOR_COMMAND_ALIASES:
        return raw
    for canonical, aliases in _EMULATOR_COMMAND_ALIASES.items():
        if raw in aliases:
            return canonical
    normalized = raw.replace("\\", "/")
    path = PurePosixPath(normalized)
    bundle_candidates = (path, *path.parents)
    for candidate in bundle_candidates:
        bundle_name = candidate.name.casefold()
        if not bundle_name.endswith(".app"):
            continue
        for canonical, bundle_names in _MACOS_APP_BUNDLE_NAMES.items():
            if any(bundle_name == bundle.casefold() for bundle in bundle_names):
                return canonical
        break
    basename = path.name.casefold()
    stem = path.stem.casefold()
    for canonical, aliases in _EMULATOR_COMMAND_ALIASES.items():
        if basename in aliases or stem in aliases:
            return canonical
    return raw


def _set_macos_pcsx2_rosetta_disabled(disabled: bool) -> None:
    global _MACOS_DISABLE_PCSX2_ROSETTA
    _MACOS_DISABLE_PCSX2_ROSETTA = disabled


def _is_macos_host() -> bool:
    return _OS_NAME != "nt" and _SYS_PLATFORM == "darwin"


def _is_apple_silicon_macos() -> bool:
    return _is_macos_host() and platform.machine().strip().casefold() in {"arm64", "arm64e", "aarch64"}


def _should_apply_macos_policy(emulator_value: str, path_value: Path) -> bool:
    if not _is_macos_host():
        return False
    if _canonical_emulator_name(emulator_value) not in _MACOS_APP_BUNDLE_NAMES:
        return False
    candidate = path_value.expanduser()
    if candidate.suffix.casefold() == ".app":
        return True
    if any(parent.suffix.casefold() == ".app" for parent in candidate.parents):
        return True
    return not candidate.suffix


def _normalize_macos_architectures(tokens: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({"arm64" if token == "arm64e" else token for token in tokens}))


def _normalize_macos_executable_candidate(path_value: Path) -> Path | None:
    candidate = path_value.expanduser()
    if not candidate.exists():
        return None
    if candidate.suffix.casefold() == ".app":
        executable = resolve_macos_app_bundle_executable(candidate)
        if executable is None:
            return None
        candidate = executable
    if candidate.is_dir():
        return None
    try:
        return candidate.resolve()
    except OSError:
        return candidate


def _macos_binary_architectures(path_value: Path) -> tuple[str, ...]:
    executable = _normalize_macos_executable_candidate(path_value)
    if executable is None:
        return ()
    outputs: list[str] = []
    for command in (["lipo", "-archs", str(executable)], ["file", str(executable)]):
        try:
            completed = subprocess.run(  # noqa: S603
                command,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            continue
        if completed.returncode != 0:
            continue
        outputs.append(f"{completed.stdout}\n{completed.stderr}")
    tokens: list[str] = []
    for output in outputs:
        tokens.extend(_MACH_O_ARCH_RE.findall(output))
    return _normalize_macos_architectures(tokens)


def _macos_rosetta_available() -> bool:
    if not _is_apple_silicon_macos():
        return False
    try:
        completed = subprocess.run(  # noqa: S603
            [_MACOS_ARCH_EXECUTABLE, "-x86_64", _MACOS_TRUE_EXECUTABLE],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    return completed.returncode == 0


def _macos_executable_policy(emulator_value: str, path_value: Path) -> _MacOSExecutablePolicy:
    architectures = _macos_binary_architectures(path_value)
    if not _is_apple_silicon_macos():
        return _MacOSExecutablePolicy(allowed=True, preference=0, architectures=architectures)
    if not architectures:
        return _MacOSExecutablePolicy(
            allowed=False,
            preference=99,
            reason="could not verify macOS executable architecture",
        )
    if "arm64" in architectures:
        return _MacOSExecutablePolicy(allowed=True, preference=0, architectures=architectures)

    joined = ", ".join(architectures)
    canonical = _canonical_emulator_name(emulator_value)
    if canonical == "pcsx2":
        if _MACOS_DISABLE_PCSX2_ROSETTA:
            return _MacOSExecutablePolicy(
                allowed=False,
                preference=99,
                reason=(
                    "Intel-only PCSX2 is installed, but PCSX2 Rosetta fallback is disabled by "
                    "[macos].disable_pcsx2_rosetta."
                ),
                architectures=architectures,
            )
        if not _macos_rosetta_available():
            return _MacOSExecutablePolicy(
                allowed=False,
                preference=99,
                reason=(
                    "Intel-only PCSX2 requires Rosetta, but Rosetta is not available on this Mac. "
                    "Install Rosetta separately and re-run sync."
                ),
                architectures=architectures,
            )
        return _MacOSExecutablePolicy(allowed=True, preference=1, architectures=architectures)

    return _MacOSExecutablePolicy(
        allowed=False,
        preference=99,
        reason=f"macOS executable is not native Apple Silicon or universal (architectures: {joined})",
        architectures=architectures,
    )


def _select_macos_preferred_executable(emulator_value: str, candidates: Iterable[Path]) -> str | None:
    best_path: str | None = None
    best_preference: int | None = None
    for candidate in candidates:
        executable = _normalize_macos_executable_candidate(candidate)
        if executable is None:
            continue
        policy = _macos_executable_policy(emulator_value, candidate)
        if not policy.allowed:
            continue
        if best_preference is None or policy.preference < best_preference:
            best_path = str(executable)
            best_preference = policy.preference
    return best_path


def _macos_emulator_unavailable_reason(emulator_value: str) -> str | None:
    if _OS_NAME == "nt" or _SYS_PLATFORM != "darwin":
        return None
    raw = emulator_value.strip().strip('"')
    if not raw:
        return None
    candidates: list[Path] = []
    path = _safe_path(raw)
    if path.exists():
        candidates.append(path)
    bundle_names = _MACOS_APP_BUNDLE_NAMES.get(_canonical_emulator_name(raw), ())
    if bundle_names:
        candidates.extend(macos_application_bundle_candidates(bundle_names))
    for command in _command_candidates(raw):
        resolved_command = shutil.which(command)
        if resolved_command:
            candidates.append(_safe_path(resolved_command))
    for candidate in _dedupe_paths(candidates):
        executable = _normalize_macos_executable_candidate(candidate)
        if executable is None:
            continue
        policy = _macos_executable_policy(emulator_value, candidate)
        if policy.allowed:
            continue
        if policy.reason:
            return policy.reason
    return None


def resolve_macos_preferred_bundle_executable(emulator_value: str, *, user_only: bool = False) -> str | None:
    canonical = _canonical_emulator_name(emulator_value)
    if not _is_macos_host():
        return None
    bundle_names = _MACOS_APP_BUNDLE_NAMES.get(canonical, ())
    if not bundle_names:
        return None
    user_applications_dir = macos_user_applications_dir()
    candidates: list[Path] = []
    for bundle_path in macos_application_bundle_candidates(bundle_names):
        if user_only and bundle_path.parent != user_applications_dir:
            continue
        candidates.append(bundle_path)
    return _select_macos_preferred_executable(canonical, candidates)


def _known_install_candidates(emulator_value: str) -> tuple[Path, ...]:
    canonical = _canonical_emulator_name(emulator_value)
    values: list[Path] = []
    if _OS_NAME == "nt":
        program_files = os.environ.get("ProgramFiles")
        program_files_x86 = os.environ.get("ProgramFiles(x86)")
        local_app_data = os.environ.get("LOCALAPPDATA")
        winget_packages = _safe_path(local_app_data) / "Microsoft" / "WinGet" / "Packages" if local_app_data else None
        if canonical == "retroarch":
            if local_app_data:
                values.append(_safe_path(local_app_data) / "Programs" / "RetroArch" / "retroarch.exe")
                values.append(_safe_path(local_app_data) / "Programs" / "RetroArch-Win64" / "retroarch.exe")
            if program_files:
                values.append(_safe_path(program_files) / "RetroArch" / "retroarch.exe")
                values.append(_safe_path(program_files) / "RetroArch-Win64" / "retroarch.exe")
            if program_files_x86:
                values.append(_safe_path(program_files_x86) / "RetroArch" / "retroarch.exe")
                values.append(_safe_path(program_files_x86) / "RetroArch-Win64" / "retroarch.exe")
            if winget_packages and winget_packages.exists():
                values.extend(sorted(winget_packages.glob("Libretro.RetroArch_*\\retroarch.exe")))
        elif canonical == "pcsx2":
            if local_app_data:
                values.append(_safe_path(local_app_data) / "Programs" / "PCSX2" / "pcsx2-qt.exe")
                values.append(_safe_path(local_app_data) / "Programs" / "PCSX2" / "pcsx2.exe")
            if program_files:
                values.append(_safe_path(program_files) / "PCSX2" / "pcsx2-qt.exe")
                values.append(_safe_path(program_files) / "PCSX2" / "pcsx2.exe")
            if program_files_x86:
                values.append(_safe_path(program_files_x86) / "PCSX2" / "pcsx2-qt.exe")
                values.append(_safe_path(program_files_x86) / "PCSX2" / "pcsx2.exe")
            if winget_packages and winget_packages.exists():
                values.extend(sorted(winget_packages.glob("PCSX2Team.PCSX2_*\\pcsx2-qt.exe")))
                values.extend(sorted(winget_packages.glob("PCSX2Team.PCSX2_*\\pcsx2.exe")))
        elif canonical == "dolphin":
            if local_app_data:
                values.append(_safe_path(local_app_data) / "Programs" / "Dolphin" / "Dolphin.exe")
                values.append(_safe_path(local_app_data) / "Programs" / "Dolphin Emulator" / "Dolphin.exe")
            if program_files:
                values.append(_safe_path(program_files) / "Dolphin Emulator" / "Dolphin.exe")
                values.append(_safe_path(program_files) / "Dolphin" / "Dolphin.exe")
            if program_files_x86:
                values.append(_safe_path(program_files_x86) / "Dolphin Emulator" / "Dolphin.exe")
                values.append(_safe_path(program_files_x86) / "Dolphin" / "Dolphin.exe")
            if winget_packages and winget_packages.exists():
                values.extend(sorted(winget_packages.glob("DolphinEmulator.Dolphin_*\\Dolphin.exe")))
                values.extend(sorted(winget_packages.glob("DolphinEmu.Dolphin_*\\Dolphin.exe")))
        elif canonical == "azahar":
            if local_app_data:
                values.append(_safe_path(local_app_data) / "Programs" / "Azahar" / "azahar.exe")
                values.append(_safe_path(local_app_data) / "Programs" / "Azahar" / "azahar-qt.exe")
                values.append(_safe_path(local_app_data) / "Azahar" / "azahar.exe")
                values.append(_safe_path(local_app_data) / "Azahar" / "azahar-qt.exe")
                programs_dir = _safe_path(local_app_data) / "Programs"
                if programs_dir.exists():
                    values.extend(sorted(programs_dir.glob("Azahar*\\azahar*.exe")))
            if program_files:
                values.append(_safe_path(program_files) / "Azahar" / "azahar.exe")
                values.append(_safe_path(program_files) / "Azahar" / "azahar-qt.exe")
            if program_files_x86:
                values.append(_safe_path(program_files_x86) / "Azahar" / "azahar.exe")
                values.append(_safe_path(program_files_x86) / "Azahar" / "azahar-qt.exe")
        values.extend(_windows_registry_install_candidates(canonical))
        return tuple(values)

    if _SYS_PLATFORM.startswith("linux"):
        home = _HOST_PATH_TYPE.home()
        if canonical == "retroarch":
            values.extend((_safe_path("/usr/bin/retroarch"), _safe_path("/usr/local/bin/retroarch")))
        elif canonical == "pcsx2":
            values.extend(
                (
                    _safe_path("/usr/bin/pcsx2-qt"),
                    _safe_path("/usr/bin/pcsx2"),
                    _safe_path("/usr/local/bin/pcsx2-qt"),
                )
            )
        elif canonical == "dolphin":
            flatpak_app_id = _FLATPAK_APP_IDS.get(canonical)
            if flatpak_app_id:
                values.append(home / ".local" / "share" / "flatpak" / "exports" / "bin" / flatpak_app_id)
                values.append(_safe_path("/var/lib/flatpak/exports/bin") / flatpak_app_id)
            values.extend(
                (
                    _safe_path("/usr/bin/dolphin-emu"),
                    _safe_path("/usr/bin/dolphin"),
                    _safe_path("/usr/local/bin/dolphin-emu"),
                )
            )
        elif canonical == "azahar":
            flatpak_app_id = _FLATPAK_APP_IDS.get(canonical)
            if flatpak_app_id:
                values.append(home / ".local" / "share" / "flatpak" / "exports" / "bin" / flatpak_app_id)
                values.append(_safe_path("/var/lib/flatpak/exports/bin") / flatpak_app_id)
            values.extend((_safe_path("/usr/bin/azahar"), _safe_path("/usr/local/bin/azahar")))
        flatpak_app_id = _FLATPAK_APP_IDS.get(canonical)
        if flatpak_app_id and canonical != "dolphin":
            values.append(home / ".local" / "share" / "flatpak" / "exports" / "bin" / flatpak_app_id)
        return tuple(values)

    if _is_macos_host():
        preferred_executable = resolve_macos_preferred_bundle_executable(emulator_value)
        if preferred_executable is not None:
            values.append(_safe_path(preferred_executable))
    return tuple(values)


def _registry_display_names(canonical: str) -> tuple[str, ...]:
    if canonical == "retroarch":
        return ("retroarch",)
    if canonical == "pcsx2":
        return ("pcsx2",)
    if canonical == "dolphin":
        return ("dolphin",)
    if canonical == "azahar":
        return ("azahar",)
    return (canonical,)


def _windows_registry_install_candidates(canonical: str) -> tuple[Path, ...]:
    if _OS_NAME != "nt" or winreg is None:
        return ()
    names = _registry_display_names(canonical)
    subkeys = (
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    values: list[Path] = []
    for root, path in subkeys:
        try:
            key = winreg.OpenKey(root, path)
        except OSError:
            continue
        try:
            total = winreg.QueryInfoKey(key)[0]
            for index in range(total):
                try:
                    name = winreg.EnumKey(key, index)
                    item_key = winreg.OpenKey(key, name)
                except OSError:
                    continue
                try:
                    display_name = _registry_value(item_key, "DisplayName").lower()
                    if not any(token in display_name for token in names):
                        continue
                    install_location = _registry_value(item_key, "InstallLocation")
                    display_icon = _registry_value(item_key, "DisplayIcon")
                    if install_location:
                        values.extend(_paths_from_install_dir(canonical, _safe_path(install_location)))
                    if display_icon:
                        icon_path = _normalize_display_icon_path(display_icon)
                        if icon_path:
                            values.append(icon_path)
                finally:
                    try:
                        winreg.CloseKey(item_key)
                    except OSError:
                        pass
        finally:
            try:
                winreg.CloseKey(key)
            except OSError:
                pass
    return tuple(values)


def _registry_value(key: Any, name: str) -> str:
    if winreg is None:
        return ""
    try:
        value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return ""
    return str(value).strip()


def _normalize_display_icon_path(value: str) -> Path | None:
    raw = value.strip().strip('"')
    if not raw:
        return None
    if "," in raw:
        raw = raw.split(",", 1)[0]
    return _safe_path(raw)


def _paths_from_install_dir(canonical: str, install_dir: Path) -> list[Path]:
    values: list[Path] = []
    if canonical == "retroarch":
        values.append(install_dir / "retroarch.exe")
    elif canonical == "pcsx2":
        values.append(install_dir / "pcsx2-qt.exe")
        values.append(install_dir / "pcsx2.exe")
    elif canonical == "dolphin":
        values.append(install_dir / "Dolphin.exe")
    elif canonical == "azahar":
        values.append(install_dir / "azahar.exe")
        values.append(install_dir / "azahar-qt.exe")
    return values


def _dedupe_paths(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _is_windows_apps_alias(path_value: str) -> bool:
    normalized = path_value.replace("/", "\\").lower()
    return "\\windowsapps\\" in normalized


def _known_install_exists(emulator_value: str) -> bool:
    for candidate in _dedupe_paths(_known_install_candidates(emulator_value)):
        if _should_apply_macos_policy(emulator_value, candidate):
            if _select_macos_preferred_executable(emulator_value, [candidate]) is not None:
                return True
            continue
        if candidate.exists():
            return True
    return False


def _is_emulator_available(emulator_value: str) -> bool:
    raw = emulator_value.strip().strip('"')
    if not raw:
        return False
    path = _safe_path(raw)
    if path.is_absolute() or path.suffix:
        if not path.exists():
            return False
        if _should_apply_macos_policy(emulator_value, path):
            return _select_macos_preferred_executable(emulator_value, [path]) is not None
        return True
    for command in _command_candidates(raw):
        resolved_command = shutil.which(command)
        if not resolved_command:
            continue
        if _should_apply_macos_policy(emulator_value, _safe_path(resolved_command)):
            if _select_macos_preferred_executable(emulator_value, [_safe_path(resolved_command)]) is not None:
                return True
            continue
        return True
    if _known_install_exists(raw):
        return True
    resolved = resolve_emulator_executable(raw)
    if resolved == raw:
        return False
    resolved_path = _safe_path(resolved.strip('"'))
    if resolved_path.is_absolute() or resolved_path.suffix:
        return resolved_path.exists()
    return any(shutil.which(command) is not None for command in _command_candidates(resolved))


def _resolve_winget_command() -> str | None:
    resolved = shutil.which("winget")
    if resolved:
        return resolved
    if _OS_NAME != "nt":
        return None
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    candidate = _safe_path(local_app_data) / "Microsoft" / "WindowsApps" / "winget.exe"
    if candidate.exists():
        return str(candidate)
    return None


def resolve_emulator_executable(emulator_value: str) -> str:
    raw = emulator_value.strip().strip('"')
    if not raw:
        return emulator_value
    if _is_macos_host() and _canonical_emulator_name(raw) == "azahar":
        preferred_user_executable = resolve_macos_preferred_bundle_executable(raw, user_only=True)
        if preferred_user_executable is not None:
            return preferred_user_executable
    path = _safe_path(raw)
    if path.exists():
        if _should_apply_macos_policy(raw, path):
            compatible_path = _select_macos_preferred_executable(raw, [path])
            if compatible_path is not None:
                return compatible_path
        try:
            return str(path.resolve())
        except OSError:
            return str(path)
    if path.is_absolute() and path.exists():
        return str(path)
    for candidate in _dedupe_paths(_known_install_candidates(raw)):
        if _should_apply_macos_policy(raw, candidate):
            compatible_path = _select_macos_preferred_executable(raw, [candidate])
            if compatible_path is not None:
                return compatible_path
            continue
        if candidate.exists():
            return str(candidate)
    alias_candidate: str | None = None
    for command in _command_candidates(raw):
        resolved = shutil.which(command)
        if not resolved:
            continue
        if _should_apply_macos_policy(raw, _safe_path(resolved)):
            compatible_path = _select_macos_preferred_executable(raw, [_safe_path(resolved)])
            if compatible_path is not None:
                return compatible_path
            continue
        if _is_windows_apps_alias(resolved):
            alias_candidate = resolved
            continue
        return resolved
    if alias_candidate:
        return alias_candidate
    return raw


def _required_emulators(index: LibraryIndex) -> set[str]:
    values = {title.emulator.strip() for title in index.titles if title.emulator.strip()}
    values.update(system.default_emulator.strip() for system in index.systems if system.default_emulator.strip())
    return values


def _linux_dist_id() -> str:
    os_release = _safe_path("/etc/os-release")
    if not os_release.exists():
        return ""
    fields: dict[str, str] = {}
    for line in os_release.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" not in line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        fields[key.strip().lower()] = value.strip().strip('"').strip("'").lower()
    id_value = fields.get("id", "")
    id_like = fields.get("id_like", "")
    if id_value:
        return f"{id_value} {id_like}".strip()
    return id_like
