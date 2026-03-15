from __future__ import annotations

import logging
import os
import sys
from pathlib import Path, PosixPath
from typing import Callable

from ..common.config import GamehubConfig
from ..common.config_edit import upsert_qsettings_key
from ..common.fsops import backup_existing_file
from ..common.platform_paths import (
    AZAHAR_FLATPAK_APP_ID,
    is_flatpak_command,
    linux_flatpak_azahar_config_root,
    linux_flatpak_azahar_root,
    macos_azahar_qt_config_candidates,
)
from ..emulators import resolve_emulator_executable
from .pcsx2_ini import read_ini_lines, write_ini_atomic

_OS_NAME = os.name
_SYS_PLATFORM = sys.platform
_AZAHAR_FULLSCREEN_KEY = "fullscreen"
_AZAHAR_FULLSCREEN_DEFAULT_KEY = r"fullscreen\default"
_AZAHAR_FULLSCREEN_VALUE = "true"
_AZAHAR_FULLSCREEN_DEFAULT_VALUE = "false"
_AZAHAR_CONFIRM_CLOSE_KEY = "confirmClose"
_AZAHAR_CONFIRM_CLOSE_DEFAULT_KEY = r"confirmClose\default"
_AZAHAR_CONFIRM_CLOSE_VALUE = "false"
_AZAHAR_CONFIRM_CLOSE_DEFAULT_VALUE = "false"
logger = logging.getLogger(__name__)


def default_azahar_qt_config_path(config: GamehubConfig | None = None) -> Path:
    appdata = os.environ.get("APPDATA")
    if _OS_NAME == "nt" and appdata:
        # Keep mocked Windows branches host-safe when tests run on non-Windows hosts.
        if _SYS_PLATFORM.startswith("win"):
            return Path(appdata) / "Azahar" / "config" / "qt-config.ini"
        return PosixPath(appdata) / "Azahar" / "config" / "qt-config.ini"
    if _SYS_PLATFORM == "darwin":
        candidates = macos_azahar_qt_config_candidates()
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]

    home = Path.home()
    flatpak_qt_config = linux_flatpak_azahar_config_root() / "qt-config.ini"
    flatpak_data_root = linux_flatpak_azahar_root()
    flatpak_export_user = home / ".local" / "share" / "flatpak" / "exports" / "bin" / AZAHAR_FLATPAK_APP_ID
    azahar_raw = resolve_emulator_executable("azahar").strip('"')
    azahar_exe = Path(azahar_raw)
    if _SYS_PLATFORM.startswith("linux") and (
        is_flatpak_command(azahar_exe, AZAHAR_FLATPAK_APP_ID)
        or AZAHAR_FLATPAK_APP_ID.casefold() in azahar_raw.casefold()
        or flatpak_qt_config.parent.exists()
        or flatpak_data_root.exists()
        or flatpak_export_user.exists()
    ):
        return flatpak_qt_config
    return home / ".config" / "azahar-emu" / "qt-config.ini"


def configure_azahar_runtime(
    config: GamehubConfig,
    dry_run: bool,
    verbose: bool,
    writer: Callable[[str], None] = print,
) -> Path:
    ini_path = default_azahar_qt_config_path(config=config)
    details_parts = ["fullscreen=true", "confirm_exit_dialog=false"]
    details = "\t".join(details_parts)
    if dry_run:
        if verbose:
            writer(f"azahar\tdry-run\tconfigure\t{ini_path}\t{details}")
        return ini_path

    lines = read_ini_lines(ini_path)
    lines, changed_fullscreen = upsert_qsettings_key(lines, _AZAHAR_FULLSCREEN_KEY, _AZAHAR_FULLSCREEN_VALUE)
    lines, changed_fullscreen_default = upsert_qsettings_key(
        lines, _AZAHAR_FULLSCREEN_DEFAULT_KEY, _AZAHAR_FULLSCREEN_DEFAULT_VALUE
    )
    lines, changed_confirm_close = upsert_qsettings_key(lines, _AZAHAR_CONFIRM_CLOSE_KEY, _AZAHAR_CONFIRM_CLOSE_VALUE)
    lines, changed_confirm_close_default = upsert_qsettings_key(
        lines, _AZAHAR_CONFIRM_CLOSE_DEFAULT_KEY, _AZAHAR_CONFIRM_CLOSE_DEFAULT_VALUE
    )
    if (
        changed_fullscreen
        or changed_fullscreen_default
        or changed_confirm_close
        or changed_confirm_close_default
        or not ini_path.exists()
    ):
        if ini_path.exists():
            backup = backup_existing_file(ini_path)
            if backup is not None:
                logger.info("azahar runtime backup created path=%s backup=%s", ini_path, backup)
        write_ini_atomic(ini_path, lines)
        logger.info("azahar runtime config updated path=%s", ini_path)

    if verbose:
        writer(f"azahar\tconfigured\t{ini_path}\t{details}")
    return ini_path
