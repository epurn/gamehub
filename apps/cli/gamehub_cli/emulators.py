from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from typing import Iterable

from gamehub_common.models import LibraryIndex

try:
    import winreg  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    winreg = None

_WINGET_IDS = {
    "retroarch": "Libretro.RetroArch",
    "pcsx2": "PCSX2Team.PCSX2",
    "dolphin": "DolphinEmu.Dolphin",
}

_DNF_PACKAGES = {
    "retroarch": "retroarch",
    "pcsx2": "pcsx2",
    "dolphin": "dolphin-emu",
}

_FLATPAK_APP_IDS = {
    "retroarch": "org.libretro.RetroArch",
    "pcsx2": "net.pcsx2.PCSX2",
    "dolphin": "org.DolphinEmu.dolphin-emu",
}

_EMULATOR_COMMAND_ALIASES = {
    "retroarch": ("retroarch",),
    "pcsx2": ("pcsx2", "pcsx2-qt"),
    "dolphin": ("dolphin", "dolphin-emu"),
}


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
    return raw


def _known_install_candidates(emulator_value: str) -> tuple[Path, ...]:
    canonical = _canonical_emulator_name(emulator_value)
    home = Path.home()
    values: list[Path] = []
    if os.name == "nt":
        program_files = os.environ.get("ProgramFiles")
        program_files_x86 = os.environ.get("ProgramFiles(x86)")
        local_app_data = os.environ.get("LOCALAPPDATA")
        winget_packages = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages" if local_app_data else None
        if canonical == "retroarch":
            if local_app_data:
                values.append(Path(local_app_data) / "Programs" / "RetroArch" / "retroarch.exe")
                values.append(Path(local_app_data) / "Programs" / "RetroArch-Win64" / "retroarch.exe")
            if program_files:
                values.append(Path(program_files) / "RetroArch" / "retroarch.exe")
                values.append(Path(program_files) / "RetroArch-Win64" / "retroarch.exe")
            if program_files_x86:
                values.append(Path(program_files_x86) / "RetroArch" / "retroarch.exe")
                values.append(Path(program_files_x86) / "RetroArch-Win64" / "retroarch.exe")
            if winget_packages and winget_packages.exists():
                values.extend(sorted(winget_packages.glob("Libretro.RetroArch_*\\retroarch.exe")))
        elif canonical == "pcsx2":
            if local_app_data:
                values.append(Path(local_app_data) / "Programs" / "PCSX2" / "pcsx2-qt.exe")
                values.append(Path(local_app_data) / "Programs" / "PCSX2" / "pcsx2.exe")
            if program_files:
                values.append(Path(program_files) / "PCSX2" / "pcsx2-qt.exe")
                values.append(Path(program_files) / "PCSX2" / "pcsx2.exe")
            if program_files_x86:
                values.append(Path(program_files_x86) / "PCSX2" / "pcsx2-qt.exe")
                values.append(Path(program_files_x86) / "PCSX2" / "pcsx2.exe")
            if winget_packages and winget_packages.exists():
                values.extend(sorted(winget_packages.glob("PCSX2Team.PCSX2_*\\pcsx2-qt.exe")))
                values.extend(sorted(winget_packages.glob("PCSX2Team.PCSX2_*\\pcsx2.exe")))
        elif canonical == "dolphin":
            if local_app_data:
                values.append(Path(local_app_data) / "Programs" / "Dolphin" / "Dolphin.exe")
                values.append(Path(local_app_data) / "Programs" / "Dolphin Emulator" / "Dolphin.exe")
            if program_files:
                values.append(Path(program_files) / "Dolphin Emulator" / "Dolphin.exe")
                values.append(Path(program_files) / "Dolphin" / "Dolphin.exe")
            if program_files_x86:
                values.append(Path(program_files_x86) / "Dolphin Emulator" / "Dolphin.exe")
                values.append(Path(program_files_x86) / "Dolphin" / "Dolphin.exe")
            if winget_packages and winget_packages.exists():
                values.extend(sorted(winget_packages.glob("DolphinEmu.Dolphin_*\\Dolphin.exe")))
        values.extend(_windows_registry_install_candidates(canonical))
        return tuple(values)

    if sys.platform.startswith("linux"):
        if canonical == "retroarch":
            values.extend((Path("/usr/bin/retroarch"), Path("/usr/local/bin/retroarch")))
        elif canonical == "pcsx2":
            values.extend((Path("/usr/bin/pcsx2-qt"), Path("/usr/bin/pcsx2"), Path("/usr/local/bin/pcsx2-qt")))
        elif canonical == "dolphin":
            values.extend((Path("/usr/bin/dolphin-emu"), Path("/usr/bin/dolphin"), Path("/usr/local/bin/dolphin-emu")))
        # Flatpak exports, if present.
        values.extend(
            (
                home / ".local" / "share" / "flatpak" / "exports" / "bin" / "org.libretro.RetroArch",
                home / ".local" / "share" / "flatpak" / "exports" / "bin" / "net.pcsx2.PCSX2",
                home / ".local" / "share" / "flatpak" / "exports" / "bin" / "org.DolphinEmu.dolphin-emu",
            )
        )
    return tuple(values)


def _registry_display_names(canonical: str) -> tuple[str, ...]:
    if canonical == "retroarch":
        return ("retroarch",)
    if canonical == "pcsx2":
        return ("pcsx2",)
    if canonical == "dolphin":
        return ("dolphin",)
    return (canonical,)


def _windows_registry_install_candidates(canonical: str) -> tuple[Path, ...]:
    if os.name != "nt" or winreg is None:
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
                        values.extend(_paths_from_install_dir(canonical, Path(install_location)))
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


def _registry_value(key: object, name: str) -> str:
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
    # DisplayIcon can be "path,0"
    if "," in raw:
        raw = raw.split(",", 1)[0]
    path = Path(raw)
    return path


def _paths_from_install_dir(canonical: str, install_dir: Path) -> list[Path]:
    values: list[Path] = []
    if canonical == "retroarch":
        values.append(install_dir / "retroarch.exe")
    elif canonical == "pcsx2":
        values.append(install_dir / "pcsx2-qt.exe")
        values.append(install_dir / "pcsx2.exe")
    elif canonical == "dolphin":
        values.append(install_dir / "Dolphin.exe")
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
        if candidate.exists():
            return True
    return False


def _is_emulator_available(emulator_value: str) -> bool:
    raw = emulator_value.strip().strip('"')
    if not raw:
        return False
    path = Path(raw)
    if path.is_absolute() or path.suffix:
        return path.exists()
    if any(shutil.which(command) is not None for command in _command_candidates(raw)):
        return True
    if _known_install_exists(raw):
        return True
    resolved = resolve_emulator_executable(raw)
    if resolved == raw:
        return False
    resolved_path = Path(resolved.strip('"'))
    if resolved_path.is_absolute() or resolved_path.suffix:
        return resolved_path.exists()
    return any(shutil.which(command) is not None for command in _command_candidates(resolved))


def _resolve_winget_command() -> str | None:
    resolved = shutil.which("winget")
    if resolved:
        return resolved
    if os.name != "nt":
        return None
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    candidate = Path(local_app_data) / "Microsoft" / "WindowsApps" / "winget.exe"
    if candidate.exists():
        return str(candidate)
    return None


def resolve_emulator_executable(emulator_value: str) -> str:
    raw = emulator_value.strip().strip('"')
    if not raw:
        return emulator_value
    path = Path(raw)
    if path.exists():
        return str(path.resolve())
    if path.is_absolute() and path.exists():
        return str(path)
    # Prefer concrete known install locations before PATH aliases.
    for candidate in _dedupe_paths(_known_install_candidates(raw)):
        if candidate.exists():
            return str(candidate)
    alias_candidate: str | None = None
    for command in _command_candidates(raw):
        resolved = shutil.which(command)
        if not resolved:
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
    os_release = Path("/etc/os-release")
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


def _run_install_command(command: list[str], *, verbose: bool) -> int:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=not verbose,
        text=True,
    )
    return int(completed.returncode)


def _install_windows(missing: list[str], *, verbose: bool) -> None:
    winget_cmd = _resolve_winget_command()
    if winget_cmd is None:
        print("winget not found; cannot auto-install missing emulators")
        return

    for emulator in missing:
        winget_id = _WINGET_IDS.get(emulator.lower())
        if not winget_id:
            print(f"No installer mapping for emulator '{emulator}'; install it manually")
            continue
        print(f"Installing emulator '{emulator}' via winget ({winget_id})...")
        result = _run_install_command(
            [
                winget_cmd,
                "install",
                "--id",
                winget_id,
                "-e",
                "--accept-source-agreements",
                "--accept-package-agreements",
                "--silent",
            ],
            verbose=verbose,
        )
        if result != 0:
            if _is_emulator_available(emulator):
                print(f"Detected installed emulator despite winget non-zero exit: {emulator}")
                continue
            print(f"Warning: winget install failed for {emulator} (exit {result}). Install manually and re-run sync.")
            continue
        if _is_emulator_available(emulator):
            print(f"Installed emulator: {emulator}")
        else:
            print(f"Warning: {emulator} install command completed but executable not found yet")


def _install_fedora(missing: list[str], *, verbose: bool) -> None:
    if shutil.which("dnf") is None:
        print("dnf not found; cannot auto-install missing emulators on Fedora")
        return
    prefix: list[str] = []
    geteuid = getattr(os, "geteuid", None)
    if callable(geteuid) and geteuid() != 0:
        if shutil.which("sudo") is None:
            print("sudo not found and not running as root; cannot auto-install emulators")
            return
        prefix = ["sudo"]

    for emulator in missing:
        package_name = _DNF_PACKAGES.get(emulator.lower())
        if not package_name:
            print(f"No Fedora package mapping for emulator '{emulator}'; install it manually")
            continue
        print(f"Installing emulator '{emulator}' via dnf ({package_name})...")
        result = _run_install_command([*prefix, "dnf", "install", "-y", package_name], verbose=verbose)
        if result != 0:
            print(f"Warning: dnf install failed for {emulator} (exit {result}). Install manually and re-run sync.")
            continue
        if _is_emulator_available(emulator):
            print(f"Installed emulator: {emulator}")
        else:
            print(f"Warning: {emulator} install command completed but executable not found yet")


def _install_flatpak(missing: list[str], *, verbose: bool) -> None:
    if shutil.which("flatpak") is None:
        print("flatpak not found; cannot auto-install missing emulators via flatpak")
        return

    for emulator in missing:
        app_id = _FLATPAK_APP_IDS.get(emulator.lower())
        if not app_id:
            print(f"No flatpak mapping for emulator '{emulator}'; install it manually")
            continue
        print(f"Installing emulator '{emulator}' via flatpak ({app_id})...")
        result = _run_install_command(["flatpak", "install", "--user", "-y", "flathub", app_id], verbose=verbose)
        if result != 0:
            print(f"Warning: flatpak install failed for {emulator} (exit {result}). Install manually and re-run sync.")
            continue
        if _is_emulator_available(emulator):
            print(f"Installed emulator: {emulator}")
        else:
            print(f"Warning: {emulator} install command completed but executable not found yet")


def _linux_package_name(emulator: str) -> str:
    return _DNF_PACKAGES.get(emulator.lower(), emulator)


def _install_linux_command(missing: list[str], command_template: str, *, verbose: bool) -> None:
    template = command_template.strip()
    if not template:
        print("Linux emulator auto-install command is empty; install missing emulators manually and re-run sync.")
        return
    for emulator in missing:
        package = _linux_package_name(emulator)
        command = [token.format(package=package, emulator=emulator) for token in shlex.split(template)]
        if not command:
            print("Linux emulator auto-install command resolved to empty command; skipping")
            return
        print(f"Installing emulator '{emulator}' via configured Linux install command...")
        result = _run_install_command(command, verbose=verbose)
        if result != 0:
            print(
                "Warning: configured Linux install command failed for "
                f"{emulator} (exit {result}). Install manually and re-run sync."
            )
            continue
        if _is_emulator_available(emulator):
            print(f"Installed emulator: {emulator}")
        else:
            print(f"Warning: {emulator} install command completed but executable not found yet")


def ensure_emulators(
    index: LibraryIndex,
    dry_run: bool,
    verbose: bool,
    linux_install_backend: str | None = None,
    linux_install_command: str | None = None,
) -> None:
    required = sorted(_required_emulators(index))
    if not required:
        return

    missing = [name for name in required if not _is_emulator_available(name)]
    if not missing:
        if verbose:
            print(f"Emulators ready: {', '.join(required)}")
        return

    print(f"Missing emulators: {', '.join(missing)}")
    if dry_run:
        print("Dry-run: emulator auto-install skipped")
        return
    if os.name == "nt":
        _install_windows(missing, verbose=verbose)
        return

    if sys.platform.startswith("linux"):
        backend = (os.environ.get("GAMEHUB_LINUX_EMULATOR_INSTALL_BACKEND") or linux_install_backend or "auto").strip()
        backend = backend.casefold()
        custom_command = os.environ.get("GAMEHUB_LINUX_EMULATOR_INSTALL_COMMAND") or linux_install_command
        dist_id = _linux_dist_id()

        if backend in {"auto", ""}:
            if "fedora" in dist_id and shutil.which("dnf") is not None:
                _install_fedora(missing, verbose=verbose)
                return
            if shutil.which("flatpak") is not None:
                _install_flatpak(missing, verbose=verbose)
                return
            if custom_command:
                _install_linux_command(missing, custom_command, verbose=verbose)
                return
            print(
                "Linux emulator auto-install is unavailable for this host. "
                "Set [linux].emulator_install_backend to 'flatpak', 'dnf', or 'command', "
                "or install manually and re-run sync."
            )
            return

        if backend == "dnf":
            _install_fedora(missing, verbose=verbose)
            return
        if backend == "flatpak":
            _install_flatpak(missing, verbose=verbose)
            return
        if backend == "none":
            print("Linux emulator auto-install disabled by configuration")
            return
        if backend == "command":
            if not custom_command:
                print(
                    "Linux emulator install backend is 'command' but no command template is configured. "
                    "Set [linux].emulator_install_command and re-run sync."
                )
                return
            _install_linux_command(missing, custom_command, verbose=verbose)
            return

        print(
            "Unsupported Linux emulator install backend: "
            f"{backend}. Valid values: auto, dnf, flatpak, none, command."
        )
        return

    print("Emulator auto-install is currently supported on Windows and Linux only")
