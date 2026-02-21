from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import shutil
import subprocess
import sys
from typing import Callable

from gamehub_common.models import LibraryIndex

from . import installer, resolution


@dataclass(frozen=True)
class EmulatorServices:
    """Concrete emulator service hooks used by the CLI runtime."""

    ensure: Callable[[LibraryIndex, bool, bool, str | None, str | None, str | None], None]
    resolve_executable: Callable[[str], str]


def _default_services() -> EmulatorServices:
    return EmulatorServices(
        ensure=installer.ensure_emulators,
        resolve_executable=resolution.resolve_emulator_executable,
    )


_SERVICES = _default_services()


def configure_services(*, ensure: Callable | None = None, resolve_executable: Callable | None = None) -> None:
    """Allow tests and alternate runtimes to inject explicit emulator services."""

    global _SERVICES
    _SERVICES = EmulatorServices(
        ensure=ensure or _SERVICES.ensure,
        resolve_executable=resolve_executable or _SERVICES.resolve_executable,
    )


# Compatibility exports for existing tests and modules that import internals.
emulator_install = installer
emulator_resolution = resolution

_known_install_candidates = resolution._known_install_candidates
_linux_dist_id = resolution._linux_dist_id
_required_emulators = resolution._required_emulators
_resolve_winget_command = resolution._resolve_winget_command
_is_emulator_available = resolution._is_emulator_available


def _sync_runtime_overrides() -> None:
    resolution._known_install_candidates = _known_install_candidates
    resolution._linux_dist_id = _linux_dist_id
    resolution._required_emulators = _required_emulators
    resolution._resolve_winget_command = _resolve_winget_command
    resolution._is_emulator_available = _is_emulator_available

    installer._linux_dist_id = _linux_dist_id
    installer._required_emulators = _required_emulators
    installer._is_emulator_available = _is_emulator_available
    installer._resolve_winget_command = _resolve_winget_command


def ensure_emulators(
    index: LibraryIndex,
    dry_run: bool,
    verbose: bool,
    linux_install_backend: str | None = None,
    linux_install_command: str | None = None,
    linux_flatpak_remote: str | None = None,
) -> None:
    _sync_runtime_overrides()
    _SERVICES.ensure(
        index,
        dry_run,
        verbose,
        linux_install_backend,
        linux_install_command,
        linux_flatpak_remote,
    )


def resolve_emulator_executable(emulator_value: str) -> str:
    _sync_runtime_overrides()
    return _SERVICES.resolve_executable(emulator_value)


__all__ = [
    "Path",
    "configure_services",
    "emulator_install",
    "emulator_resolution",
    "ensure_emulators",
    "os",
    "resolve_emulator_executable",
    "shutil",
    "subprocess",
    "sys",
    "_is_emulator_available",
    "_known_install_candidates",
    "_linux_dist_id",
    "_required_emulators",
    "_resolve_winget_command",
]
