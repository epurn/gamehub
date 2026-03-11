from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Callable

from ..common.config import GamehubConfig
from ..common.config_edit import read_simple_cfg_key, upsert_simple_cfg_key
from ..common.fsops import backup_existing_file
from .pcsx2_ini import read_ini_lines, write_ini_atomic
from .targets import retroarch_cfg_candidates_for_config

_RETROARCH_MENU_COMBO_KEY = "input_menu_toggle_gamepad_combo"
_RETROARCH_MENU_COMBO_VALUE = "4"
_RETROARCH_MENU_COMBO_LABEL = "Start+Select"
_RETROARCH_ALL_USERS_MENU_KEY = "all_users_control_menu"
_RETROARCH_ALL_USERS_MENU_VALUE = "true"
_RETROARCH_JOYPAD_DRIVER_KEY = "input_joypad_driver"
_RETROARCH_JOYPAD_DRIVER_SDL2 = "sdl2"
_RETROARCH_ANALOG_DPAD_KEYS = tuple(f"input_player{index}_analog_dpad_mode" for index in range(1, 9))
_RETROARCH_ANALOG_DPAD_VALUE = "0"
_RETROARCH_LIBRETRO_DEVICE_KEYS = tuple(f"input_libretro_device_p{index}" for index in range(1, 9))
_RETROARCH_LIBRETRO_DEVICE_VALUES = {"input_libretro_device_p1": "261"}
_RETROARCH_LIBRETRO_DEVICE_DEFAULT = "1"
_RETROARCH_REMAP_PORT_KEYS = tuple(f"input_remap_port_p{index}" for index in range(1, 9))
_RETROARCH_REMAP_PORT_VALUES = {f"input_remap_port_p{index}": str(index - 1) for index in range(1, 9)}
_RETROARCH_TURBO_KEYS = {
    "input_turbo_allow_dpad": "false",
    "input_turbo_bind": "-1",
    "input_turbo_button": "0",
    "input_turbo_duty_cycle": "0",
    "input_turbo_enable": "true",
    "input_turbo_mode": "0",
    "input_turbo_period": "6",
}
_RETROARCH_REMAP_DIRECTORY_KEY = "input_remapping_directory"
_RETROARCH_CONFIG_DIRECTORY_KEY = "config_directory"
_RETROARCH_SWANSTATION_CORE_NAME = "SwanStation"
_RETROARCH_PSX_CORE_OPTIONS = {
    "swanstation_Controller1.Type": "AnalogController",
    "swanstation_Controller2.Type": "AnalogController",
}
_STEAMOS_RELEASE_PATH = Path("/etc/os-release")
_DMI_BOARD_VENDOR_PATH = Path("/sys/devices/virtual/dmi/id/board_vendor")
logger = logging.getLogger(__name__)


def _is_steam_deck_linux() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        os_release = _STEAMOS_RELEASE_PATH.read_text(encoding="utf-8", errors="ignore").casefold()
    except OSError:
        os_release = ""
    if "id=steamos" in os_release or "steamdeck" in os_release or "holo" in os_release:
        return True
    try:
        vendor = _DMI_BOARD_VENDOR_PATH.read_text(encoding="utf-8", errors="ignore").strip().casefold()
    except OSError:
        vendor = ""
    return "valve" in vendor


def is_steam_deck_linux() -> bool:
    return _is_steam_deck_linux()


def _path_with_tilde_expanded(raw: str) -> Path:
    value = raw.strip()
    if value == "~":
        return Path.home()
    if value.startswith("~/") or value.startswith("~\\"):
        return Path.home() / value[2:]
    return Path(value)


def _resolve_retroarch_cfg_path(raw: str, *, cfg_path: Path) -> Path:
    value = raw.strip()
    if os.name == "nt" and value.startswith((":\\", ":/")):
        return cfg_path.parent / value[2:]
    candidate = _path_with_tilde_expanded(value)
    if not candidate.is_absolute():
        candidate = cfg_path.parent / candidate
    return candidate


def _resolve_retroarch_remap_dir(cfg_path: Path, lines: list[str]) -> Path:
    raw_remap = read_simple_cfg_key(lines, _RETROARCH_REMAP_DIRECTORY_KEY)
    if raw_remap:
        return _resolve_retroarch_cfg_path(raw_remap, cfg_path=cfg_path)
    raw_config_dir = read_simple_cfg_key(lines, _RETROARCH_CONFIG_DIRECTORY_KEY)
    if raw_config_dir:
        return _resolve_retroarch_cfg_path(raw_config_dir, cfg_path=cfg_path) / "remaps"
    return cfg_path.parent / "config" / "remaps"


def _write_retroarch_remap_file(remap_dir: Path, *, core_name: str) -> tuple[Path, bool]:
    remap_path = remap_dir / core_name / f"{core_name}.rmp"
    remap_lines = read_ini_lines(remap_path)
    changed = False
    for key in _RETROARCH_LIBRETRO_DEVICE_KEYS:
        desired = _RETROARCH_LIBRETRO_DEVICE_VALUES.get(key, _RETROARCH_LIBRETRO_DEVICE_DEFAULT)
        remap_lines, updated = upsert_simple_cfg_key(remap_lines, key, desired)
        changed |= updated
    for key in _RETROARCH_ANALOG_DPAD_KEYS:
        remap_lines, updated = upsert_simple_cfg_key(remap_lines, key, _RETROARCH_ANALOG_DPAD_VALUE)
        changed |= updated
    for key, desired in _RETROARCH_REMAP_PORT_VALUES.items():
        remap_lines, updated = upsert_simple_cfg_key(remap_lines, key, desired)
        changed |= updated
    for key, desired in _RETROARCH_TURBO_KEYS.items():
        remap_lines, updated = upsert_simple_cfg_key(remap_lines, key, desired)
        changed |= updated
    if changed or not remap_path.exists():
        if remap_path.exists():
            backup = backup_existing_file(remap_path)
            if backup is not None:
                logger.info("retroarch runtime backup created path=%s backup=%s kind=remap", remap_path, backup)
        write_ini_atomic(remap_path, remap_lines)
        logger.info("retroarch runtime config updated path=%s kind=remap", remap_path)
    return remap_path, changed


def _retroarch_menu_combo_requires_migration(binding: str | None) -> bool:
    if not binding:
        return True
    return binding.strip().strip('"').strip("'") != _RETROARCH_MENU_COMBO_VALUE


def _retroarch_all_users_menu_requires_migration(binding: str | None) -> bool:
    if not binding:
        return True
    return binding.strip().strip('"').strip("'").casefold() != _RETROARCH_ALL_USERS_MENU_VALUE


def _resolve_retroarch_cfg_target(config: GamehubConfig) -> Path | None:
    candidates = list(retroarch_cfg_candidates_for_config(config=config))
    if sys.platform == "darwin" and config.macos.retroarch_cfg_path is not None:
        return config.macos.retroarch_cfg_path.expanduser()
    for candidate in candidates:
        if candidate.exists():
            return candidate
    if sys.platform == "darwin":
        if candidates:
            return candidates[0]
        return None
    if config.linux.retroarch_cfg_path is not None:
        return config.linux.retroarch_cfg_path.expanduser()
    return None


def configure_retroarch_runtime(
    config: GamehubConfig,
    dry_run: bool,
    verbose: bool,
    writer: Callable[[str], None],
) -> Path | None:
    cfg_path = _resolve_retroarch_cfg_target(config=config)
    if cfg_path is None:
        if verbose:
            writer("retroarch\tskipped\thotkeys\treason=config_missing")
        return None
    core_options_path = cfg_path.with_name("retroarch-core-options.cfg")

    if dry_run:
        if verbose:
            if os.name == "nt":
                details = f"menu_combo={_RETROARCH_MENU_COMBO_LABEL}\tall_users_menu=true"
            else:
                details = (
                    f"menu_combo={_RETROARCH_MENU_COMBO_LABEL}\tall_users_menu=true\t"
                    f"analog_dpad_mode={_RETROARCH_ANALOG_DPAD_VALUE}\tlibretro_device_p1=261"
                )
            writer(f"retroarch\tdry-run\tconfigure\t{cfg_path}\t{details}")
            writer(f"retroarch\tdry-run\tcore-options\t{core_options_path}\tpsx_controller=AnalogController")
            remap_dir = _resolve_retroarch_remap_dir(cfg_path, read_ini_lines(cfg_path))
            writer(
                "retroarch\tdry-run\tremap\t"
                f"{remap_dir / _RETROARCH_SWANSTATION_CORE_NAME / (_RETROARCH_SWANSTATION_CORE_NAME + '.rmp')}"
            )
        return cfg_path

    lines = read_ini_lines(cfg_path)
    existing_combo = read_simple_cfg_key(lines, _RETROARCH_MENU_COMBO_KEY)
    existing_all_users = read_simple_cfg_key(lines, _RETROARCH_ALL_USERS_MENU_KEY)
    is_windows = os.name == "nt"
    is_deck_linux = (not is_windows) and is_steam_deck_linux()
    existing_joypad_driver = read_simple_cfg_key(lines, _RETROARCH_JOYPAD_DRIVER_KEY) if is_deck_linux else None
    existing_analog = (
        {key: read_simple_cfg_key(lines, key) for key in _RETROARCH_ANALOG_DPAD_KEYS} if not is_windows else {}
    )
    existing_libretro = (
        {key: read_simple_cfg_key(lines, key) for key in _RETROARCH_LIBRETRO_DEVICE_KEYS} if not is_windows else {}
    )
    existing_remap = (
        {key: read_simple_cfg_key(lines, key) for key in _RETROARCH_REMAP_PORT_KEYS} if not is_windows else {}
    )
    existing_turbo = {key: read_simple_cfg_key(lines, key) for key in _RETROARCH_TURBO_KEYS} if not is_windows else {}
    changed_combo = False
    changed_all_users = False
    changed_joypad_driver = False
    changed_analog = False
    changed_libretro = False
    changed_remap = False
    changed_turbo = False
    if _retroarch_menu_combo_requires_migration(existing_combo) or not cfg_path.exists():
        lines, changed_combo = upsert_simple_cfg_key(lines, _RETROARCH_MENU_COMBO_KEY, _RETROARCH_MENU_COMBO_VALUE)
    if _retroarch_all_users_menu_requires_migration(existing_all_users) or not cfg_path.exists():
        lines, changed_all_users = upsert_simple_cfg_key(
            lines,
            _RETROARCH_ALL_USERS_MENU_KEY,
            _RETROARCH_ALL_USERS_MENU_VALUE,
        )
    if is_deck_linux:
        normalized_driver = (
            existing_joypad_driver.strip().strip('"').strip("'").casefold() if existing_joypad_driver else ""
        )
        if normalized_driver != _RETROARCH_JOYPAD_DRIVER_SDL2 or not cfg_path.exists():
            lines, changed_joypad_driver = upsert_simple_cfg_key(
                lines, _RETROARCH_JOYPAD_DRIVER_KEY, _RETROARCH_JOYPAD_DRIVER_SDL2
            )
    if not is_windows:
        for key in _RETROARCH_ANALOG_DPAD_KEYS:
            existing_value = existing_analog.get(key)
            if not existing_value or existing_value != _RETROARCH_ANALOG_DPAD_VALUE or not cfg_path.exists():
                lines, changed = upsert_simple_cfg_key(lines, key, _RETROARCH_ANALOG_DPAD_VALUE)
                changed_analog |= changed
        for key in _RETROARCH_LIBRETRO_DEVICE_KEYS:
            desired = _RETROARCH_LIBRETRO_DEVICE_VALUES.get(key, _RETROARCH_LIBRETRO_DEVICE_DEFAULT)
            existing_value = existing_libretro.get(key)
            if not existing_value or existing_value != desired or not cfg_path.exists():
                lines, changed = upsert_simple_cfg_key(lines, key, desired)
                changed_libretro |= changed
        for key in _RETROARCH_REMAP_PORT_KEYS:
            desired_port = _RETROARCH_REMAP_PORT_VALUES.get(key)
            existing_value = existing_remap.get(key)
            if desired_port is not None and (
                not existing_value or existing_value != desired_port or not cfg_path.exists()
            ):
                lines, changed = upsert_simple_cfg_key(lines, key, desired_port)
                changed_remap |= changed
        for key, desired in _RETROARCH_TURBO_KEYS.items():
            existing_value = existing_turbo.get(key)
            if not existing_value or existing_value != desired or not cfg_path.exists():
                lines, changed = upsert_simple_cfg_key(lines, key, desired)
                changed_turbo |= changed
    if (
        changed_combo
        or changed_all_users
        or changed_joypad_driver
        or (not is_windows and (changed_analog or changed_libretro or changed_remap or changed_turbo))
        or not cfg_path.exists()
    ):
        if cfg_path.exists():
            backup = backup_existing_file(cfg_path)
            if backup is not None:
                logger.info("retroarch runtime backup created path=%s backup=%s kind=config", cfg_path, backup)
        write_ini_atomic(cfg_path, lines)
        logger.info("retroarch runtime config updated path=%s kind=config", cfg_path)
    core_lines = read_ini_lines(core_options_path)
    core_changed = False
    for key, value in _RETROARCH_PSX_CORE_OPTIONS.items():
        existing_value = read_simple_cfg_key(core_lines, key)
        if existing_value != value or not core_options_path.exists():
            core_lines, changed = upsert_simple_cfg_key(core_lines, key, value)
            core_changed |= changed
    if core_changed or not core_options_path.exists():
        if core_options_path.exists():
            backup = backup_existing_file(core_options_path)
            if backup is not None:
                logger.info(
                    "retroarch runtime backup created path=%s backup=%s kind=core-options",
                    core_options_path,
                    backup,
                )
        write_ini_atomic(core_options_path, core_lines)
        logger.info("retroarch runtime config updated path=%s kind=core-options", core_options_path)
    remap_dir = _resolve_retroarch_remap_dir(cfg_path, lines)
    remap_path, _ = _write_retroarch_remap_file(remap_dir, core_name=_RETROARCH_SWANSTATION_CORE_NAME)
    if verbose:
        if is_windows:
            details = f"menu_combo={_RETROARCH_MENU_COMBO_LABEL}\tall_users_menu=true"
        else:
            details = (
                f"menu_combo={_RETROARCH_MENU_COMBO_LABEL}\tall_users_menu=true\t"
                f"analog_dpad_mode={_RETROARCH_ANALOG_DPAD_VALUE}\tlibretro_device_p1=261"
            )
        writer(f"retroarch\tconfigured\t{cfg_path}\t{details}")
        writer(f"retroarch\tconfigured\tcore-options\t{core_options_path}\tpsx_controller=AnalogController")
        writer(f"retroarch\tconfigured\tremap\t{remap_path}")
    return cfg_path
