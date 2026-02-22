from __future__ import annotations

import os
import shutil
import subprocess

from gamehub_common.models import LibraryIndex

from . import install_common, install_flatpak, install_linux, install_windows
from . import resolution as emulator_resolution
from .resolution import _is_emulator_available, _linux_dist_id, _required_emulators

_OS_NAME = install_common._OS_NAME
_SYS_PLATFORM = install_common._SYS_PLATFORM

# Compatibility patch points used by tests/extensions.
_install_dolphin_from_official_release_archive = install_windows._install_dolphin_from_official_release_archive
_install_azahar_from_windows_installer = install_windows._install_azahar_from_windows_installer
_download_azahar_windows_installer = install_windows._download_azahar_windows_installer
_flatpak_app_export_candidates = install_flatpak._flatpak_app_export_candidates


def _sync_resolution_runtime_overrides() -> None:
    install_common._OS_NAME = _OS_NAME
    install_common._SYS_PLATFORM = _SYS_PLATFORM
    emulator_resolution._OS_NAME = _OS_NAME
    emulator_resolution._SYS_PLATFORM = _SYS_PLATFORM

    # Keep injected runtime modules aligned for monkeypatch-heavy tests.
    install_common.os = os
    install_common.shutil = shutil
    install_common.subprocess = subprocess
    install_windows.os = os
    install_windows.shutil = shutil
    install_windows.subprocess = subprocess
    install_linux.os = os
    install_linux.shutil = shutil
    install_flatpak.shutil = shutil
    install_flatpak.subprocess = subprocess
    emulator_resolution.shutil = shutil

    install_windows._install_dolphin_from_official_release_archive = _install_dolphin_from_official_release_archive
    install_windows._install_azahar_from_windows_installer = _install_azahar_from_windows_installer
    install_windows._download_azahar_windows_installer = _download_azahar_windows_installer
    install_flatpak._flatpak_app_export_candidates = _flatpak_app_export_candidates


def ensure_emulators(
    index: LibraryIndex,
    dry_run: bool,
    verbose: bool,
    linux_install_backend: str | None = None,
    linux_install_command: str | None = None,
    linux_flatpak_remote: str | None = None,
) -> None:
    _sync_resolution_runtime_overrides()

    required = sorted(_required_emulators(index))
    if not required:
        return

    linux_dist_id = ""
    linux_backend = ""
    if _OS_NAME == "nt":
        missing = [name for name in required if not _is_emulator_available(name)]
    elif _SYS_PLATFORM.startswith("linux"):
        linux_backend = (linux_install_backend or "auto").strip().casefold()
        linux_dist_id = _linux_dist_id()
        missing = install_linux._linux_missing_emulators(required, backend=linux_backend, dist_id=linux_dist_id)
    else:
        missing = [name for name in required if not _is_emulator_available(name)]

    if not missing:
        if verbose:
            print(f"Emulators ready: {', '.join(required)}")
        if _SYS_PLATFORM.startswith("linux"):
            install_linux._validate_forced_linux_flatpak_emulators(
                required,
                backend=linux_backend,
                dist_id=linux_dist_id,
            )
        install_windows._validate_windows_dolphin_runtime(required)
        return

    print(f"Missing emulators: {', '.join(missing)}")
    if dry_run:
        print("Dry-run: emulator auto-install skipped")
        install_windows._validate_windows_dolphin_runtime(required)
        return
    if _OS_NAME == "nt":
        install_windows._install_windows(missing, verbose=verbose)
        install_windows._validate_windows_dolphin_runtime(required)
        return

    if _SYS_PLATFORM.startswith("linux"):
        backend = linux_backend
        custom_command = linux_install_command
        dist_id = linux_dist_id

        if backend in {"auto", ""}:
            if (
                install_flatpak._prefer_flatpak_for_auto_backend(dist_id)
                and install_flatpak.shutil.which("flatpak") is not None
            ):
                install_flatpak._install_flatpak(missing, verbose=verbose, remote=linux_flatpak_remote)
                install_linux._validate_forced_linux_flatpak_emulators(required, backend=backend, dist_id=dist_id)
                return
            if "fedora" in dist_id and install_linux.shutil.which("dnf") is not None:
                install_linux._install_fedora(missing, verbose=verbose)
                return
            if ("ubuntu" in dist_id or "debian" in dist_id) and (
                install_linux.shutil.which("apt-get") is not None or install_linux.shutil.which("apt") is not None
            ):
                install_linux._install_apt(missing, verbose=verbose)
                return
            if install_flatpak.shutil.which("flatpak") is not None:
                install_flatpak._install_flatpak(missing, verbose=verbose, remote=linux_flatpak_remote)
                return
            if custom_command:
                install_linux._install_linux_command(missing, custom_command, verbose=verbose)
                return
            print(
                "Linux emulator auto-install is unavailable for this host. "
                "Set [linux].emulator_install_backend to 'flatpak', 'dnf', or 'command', "
                "or install manually and re-run sync."
            )
            return

        if backend == "dnf":
            install_linux._install_fedora(missing, verbose=verbose)
            return
        if backend == "apt":
            install_linux._install_apt(missing, verbose=verbose)
            return
        if backend == "flatpak":
            install_flatpak._install_flatpak(missing, verbose=verbose, remote=linux_flatpak_remote)
            install_linux._validate_forced_linux_flatpak_emulators(required, backend=backend, dist_id=dist_id)
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
            install_linux._install_linux_command(missing, custom_command, verbose=verbose)
            return

        print(
            "Unsupported Linux emulator install backend: "
            f"{backend}. Valid values: auto, dnf, apt, flatpak, none, command."
        )
        return

    print("Emulator auto-install is currently supported on Windows and Linux only")
