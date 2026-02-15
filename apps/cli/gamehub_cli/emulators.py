from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

from gamehub_common.models import LibraryIndex

import gamehub_cli.emulator_install as emulator_install
import gamehub_cli.emulator_resolution as emulator_resolution

try:
    import winreg  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    winreg = None


_known_install_candidates = emulator_resolution._known_install_candidates
_linux_dist_id = emulator_resolution._linux_dist_id


def _sync_resolution_module() -> None:
    emulator_resolution.os = os
    emulator_resolution.sys = sys
    emulator_resolution.shutil = shutil
    emulator_resolution.Path = Path
    emulator_resolution.winreg = winreg
    emulator_resolution._known_install_candidates = _known_install_candidates


def _required_emulators(index: LibraryIndex) -> set[str]:
    _sync_resolution_module()
    return emulator_resolution._required_emulators(index)


def _resolve_winget_command() -> str | None:
    _sync_resolution_module()
    return emulator_resolution._resolve_winget_command()


def _is_emulator_available(emulator_value: str) -> bool:
    _sync_resolution_module()
    return emulator_resolution._is_emulator_available(emulator_value)


def resolve_emulator_executable(emulator_value: str) -> str:
    _sync_resolution_module()
    return emulator_resolution.resolve_emulator_executable(emulator_value)


def _sync_install_module() -> None:
    emulator_install.os = os
    emulator_install.sys = sys
    emulator_install.Path = Path
    emulator_install.shlex = shlex
    emulator_install.shutil = shutil
    emulator_install.subprocess = subprocess
    emulator_install._required_emulators = _required_emulators
    emulator_install._is_emulator_available = _is_emulator_available
    emulator_install._resolve_winget_command = _resolve_winget_command
    emulator_install._linux_dist_id = _linux_dist_id


def ensure_emulators(
    index: LibraryIndex,
    dry_run: bool,
    verbose: bool,
    linux_install_backend: str | None = None,
    linux_install_command: str | None = None,
    linux_flatpak_remote: str | None = None,
) -> None:
    _sync_resolution_module()
    _sync_install_module()
    emulator_install.ensure_emulators(
        index=index,
        dry_run=dry_run,
        verbose=verbose,
        linux_install_backend=linux_install_backend,
        linux_install_command=linux_install_command,
        linux_flatpak_remote=linux_flatpak_remote,
    )
