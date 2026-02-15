from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

from gamehub_common.models import LibraryIndex

from .emulator_resolution import (
    _is_emulator_available,
    _linux_dist_id,
    _required_emulators,
    _resolve_winget_command,
)

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

_APT_PACKAGES = {
    "retroarch": "retroarch",
    "pcsx2": "pcsx2",
    "dolphin": "dolphin-emu",
}

_FLATPAK_APP_IDS = {
    "retroarch": "org.libretro.RetroArch",
    "pcsx2": "net.pcsx2.PCSX2",
    "dolphin": "org.DolphinEmu.dolphin-emu",
}


def _run_install_command(command: list[str], *, verbose: bool) -> int:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=not verbose,
        text=True,
    )
    return int(completed.returncode)


def _flatpak_remotes() -> list[str]:
    completed = subprocess.run(
        ["flatpak", "remotes", "--columns=name"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return []
    values: list[str] = []
    for line in completed.stdout.splitlines():
        item = line.strip()
        if not item:
            continue
        if item.casefold() in {"name", "names"}:
            continue
        values.append(item)
    return values


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


def _install_apt(missing: list[str], *, verbose: bool) -> None:
    apt_cmd = shutil.which("apt-get") or shutil.which("apt")
    if apt_cmd is None:
        print("apt-get not found; cannot auto-install missing emulators on Debian/Ubuntu hosts")
        return
    prefix: list[str] = []
    geteuid = getattr(os, "geteuid", None)
    if callable(geteuid) and geteuid() != 0:
        if shutil.which("sudo") is None:
            print("sudo not found and not running as root; cannot auto-install emulators")
            return
        prefix = ["sudo"]

    apt_binary = Path(apt_cmd).name
    for emulator in missing:
        package_name = _APT_PACKAGES.get(emulator.lower())
        if not package_name:
            print(f"No Debian/Ubuntu package mapping for emulator '{emulator}'; install it manually")
            continue
        print(f"Installing emulator '{emulator}' via {apt_binary} ({package_name})...")
        result = _run_install_command([*prefix, apt_binary, "install", "-y", package_name], verbose=verbose)
        if result != 0:
            print(
                f"Warning: {apt_binary} install failed for {emulator} (exit {result}). "
                "Install manually and re-run sync."
            )
            continue
        if _is_emulator_available(emulator):
            print(f"Installed emulator: {emulator}")
        else:
            print(f"Warning: {emulator} install command completed but executable not found yet")


def _install_flatpak(missing: list[str], *, verbose: bool, remote: str | None = None) -> None:
    if shutil.which("flatpak") is None:
        print("flatpak not found; cannot auto-install missing emulators via flatpak")
        return

    configured_remote = (remote or "").strip() or None
    remotes = _flatpak_remotes()
    if configured_remote and configured_remote not in remotes:
        print(
            f"Configured flatpak remote '{configured_remote}' is not available. "
            f"Known remotes: {', '.join(remotes) if remotes else '<none>'}"
        )
        return

    for emulator in missing:
        app_id = _FLATPAK_APP_IDS.get(emulator.lower())
        if not app_id:
            print(f"No flatpak mapping for emulator '{emulator}'; install it manually")
            continue
        print(f"Installing emulator '{emulator}' via flatpak ({app_id})...")
        command_candidates: list[list[str]] = []
        if configured_remote:
            command_candidates.append(["flatpak", "install", "--user", "-y", configured_remote, app_id])
        command_candidates.append(["flatpak", "install", "--user", "-y", app_id])
        deduped_commands: list[list[str]] = []
        seen: set[tuple[str, ...]] = set()
        for command in command_candidates:
            key = tuple(command)
            if key in seen:
                continue
            seen.add(key)
            deduped_commands.append(command)

        success = False
        for position, command in enumerate(deduped_commands):
            result = _run_install_command(command, verbose=verbose)
            if result == 0:
                success = True
                break
            if configured_remote and position == 0 and len(deduped_commands) > 1:
                print(
                    "Warning: flatpak install via configured remote failed; retrying with automatic remote resolution."
                )

        if not success:
            if not remotes:
                print(
                    "Warning: flatpak install failed and no remotes are configured. "
                    "Add one (for example: flatpak remote-add --if-not-exists flathub "
                    "https://flathub.org/repo/flathub.flatpakrepo)."
                )
            elif configured_remote:
                print(
                    "Warning: flatpak install failed for configured remote "
                    f"'{configured_remote}'. This remote may be filtered on your distro."
                )
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
    linux_flatpak_remote: str | None = None,
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
        backend = (linux_install_backend or "auto").strip()
        backend = backend.casefold()
        custom_command = linux_install_command
        dist_id = _linux_dist_id()

        if backend in {"auto", ""}:
            if "fedora" in dist_id and shutil.which("dnf") is not None:
                _install_fedora(missing, verbose=verbose)
                return
            if ("ubuntu" in dist_id or "debian" in dist_id) and (shutil.which("apt-get") is not None or shutil.which("apt") is not None):
                _install_apt(missing, verbose=verbose)
                return
            if shutil.which("flatpak") is not None:
                _install_flatpak(missing, verbose=verbose, remote=linux_flatpak_remote)
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
        if backend == "apt":
            _install_apt(missing, verbose=verbose)
            return
        if backend == "flatpak":
            _install_flatpak(missing, verbose=verbose, remote=linux_flatpak_remote)
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
            f"{backend}. Valid values: auto, dnf, apt, flatpak, none, command."
        )
        return

    print("Emulator auto-install is currently supported on Windows and Linux only")
