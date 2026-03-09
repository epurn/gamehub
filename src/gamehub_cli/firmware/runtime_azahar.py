from __future__ import annotations

import os
import sys
from pathlib import Path, PosixPath
from typing import Callable

from ..common.config import GamehubConfig
from ..common.config_edit import upsert_qsettings_key
from ..common.platform_paths import (
    AZAHAR_FLATPAK_APP_ID,
    is_flatpak_command,
    linux_flatpak_azahar_config_root,
    linux_flatpak_azahar_root,
)
from ..emulators import resolve_emulator_executable
from .pcsx2_ini import read_ini_lines, write_ini_atomic
from .targets import resolve_azahar_runtime_user_dir

_AZAHAR_FULLSCREEN_KEY = "fullscreen"
_AZAHAR_FULLSCREEN_DEFAULT_KEY = r"fullscreen\default"
_AZAHAR_FULLSCREEN_VALUE = "true"
_AZAHAR_FULLSCREEN_DEFAULT_VALUE = "false"
_AZAHAR_CONFIRM_CLOSE_KEY = "confirmClose"
_AZAHAR_CONFIRM_CLOSE_DEFAULT_KEY = r"confirmClose\default"
_AZAHAR_CONFIRM_CLOSE_VALUE = "false"
_AZAHAR_CONFIRM_CLOSE_DEFAULT_VALUE = "false"


def default_azahar_qt_config_path(config: GamehubConfig | None = None) -> Path:
    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        # Keep mocked Windows branches host-safe when tests run on non-Windows hosts.
        if sys.platform.startswith("win"):
            return Path(appdata) / "Azahar" / "config" / "qt-config.ini"
        return PosixPath(appdata) / "Azahar" / "config" / "qt-config.ini"
    if sys.platform == "darwin":
        return resolve_azahar_runtime_user_dir(config=config) / "config" / "qt-config.ini"

    home = Path.home()
    flatpak_qt_config = linux_flatpak_azahar_config_root() / "qt-config.ini"
    flatpak_data_root = linux_flatpak_azahar_root()
    flatpak_export_user = home / ".local" / "share" / "flatpak" / "exports" / "bin" / AZAHAR_FLATPAK_APP_ID
    azahar_raw = resolve_emulator_executable("azahar").strip('"')
    azahar_exe = Path(azahar_raw)
    if sys.platform.startswith("linux") and (
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
        write_ini_atomic(ini_path, lines)

    if verbose:
        writer(f"azahar\tconfigured\t{ini_path}\t{details}")
    return ini_path
