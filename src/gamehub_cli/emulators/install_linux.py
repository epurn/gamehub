from __future__ import annotations

import os
import shlex
import shutil

from . import install_common, install_flatpak
from .resolution import _is_emulator_available

_DNF_PACKAGES = {
    "retroarch": "retroarch",
    "pcsx2": "pcsx2",
    "dolphin": "dolphin-emu",
    "azahar": "azahar",
}

_APT_PACKAGES = {
    "retroarch": "retroarch",
    "pcsx2": "pcsx2",
    "dolphin": "dolphin-emu",
    "azahar": "azahar",
}


def _linux_missing_emulators(required: list[str], *, backend: str, dist_id: str) -> list[str]:
    force_flatpak = install_flatpak._flatpak_preferred_linux_backend(backend, dist_id)
    missing: list[str] = []
    for name in required:
        normalized = install_flatpak._canonical_emulator_key(name)
        if force_flatpak and normalized in install_flatpak._FLATPAK_FORCED_EMULATORS:
            app_id = install_flatpak._FLATPAK_APP_IDS.get(normalized)
            if app_id and not install_flatpak._is_flatpak_app_available(app_id):
                missing.append(name)
            continue
        if not _is_emulator_available(name):
            missing.append(name)
    return missing


def _validate_forced_linux_flatpak_emulators(required: list[str], *, backend: str, dist_id: str) -> None:
    if not install_flatpak._flatpak_preferred_linux_backend(backend, dist_id):
        return
    missing_apps: list[str] = []
    for name in required:
        normalized = install_flatpak._canonical_emulator_key(name)
        if normalized not in install_flatpak._FLATPAK_FORCED_EMULATORS:
            continue
        app_id = install_flatpak._FLATPAK_APP_IDS.get(normalized)
        if app_id and not install_flatpak._is_flatpak_app_available(app_id):
            missing_apps.append(app_id)
    if missing_apps:
        joined = ", ".join(sorted(set(missing_apps)))
        raise RuntimeError(
            "Required Flatpak emulator(s) are unavailable for this Linux backend: "
            f"{joined}. Install them via flatpak and re-run sync."
        )


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
        result = install_common._run_install_command([*prefix, "dnf", "install", "-y", package_name], verbose=verbose)
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

    apt_binary = install_common._safe_path(apt_cmd).name
    for emulator in missing:
        package_name = _APT_PACKAGES.get(emulator.lower())
        if not package_name:
            print(f"No Debian/Ubuntu package mapping for emulator '{emulator}'; install it manually")
            continue
        print(f"Installing emulator '{emulator}' via {apt_binary} ({package_name})...")
        result = install_common._run_install_command(
            [*prefix, apt_binary, "install", "-y", package_name], verbose=verbose
        )
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


def _linux_package_name(emulator: str) -> str:
    return _DNF_PACKAGES.get(install_flatpak._canonical_emulator_key(emulator), emulator)


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
        result = install_common._run_install_command(command, verbose=verbose)
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
