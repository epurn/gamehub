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
from .retroarch_cores import resolve_retroarch_paths
from .targets import retroarch_cfg_candidates_for_config

_OS_NAME = os.name
_SYS_PLATFORM = sys.platform
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
_RETROARCH_GAME_SPECIFIC_OPTIONS_KEY = "game_specific_options"
_RETROARCH_VIDEO_DRIVER_KEY = "video_driver"
_RETROARCH_VIDEO_DRIVER_GLCORE = "glcore"
_RETROARCH_SWANSTATION_CORE_NAME = "SwanStation"
_RETROARCH_PSX_CORE_OPTIONS = {
    "swanstation_Controller1.Type": "AnalogController",
    "swanstation_Controller2.Type": "AnalogController",
}
_RETROARCH_MUPEN64PLUS_NEXT_CORE_NAME = "mupen64plus_next_libretro"
_RETROARCH_MUPEN64PLUS_NEXT_CORE_FILENAME = f"{_RETROARCH_MUPEN64PLUS_NEXT_CORE_NAME}.dylib"
_RETROARCH_MUPEN64PLUS_NEXT_CONFIG_DIRNAME = "Mupen64Plus-Next"
_RETROARCH_MACOS_N64_LEGACY_CORE_OPTION_KEYS = ("mupen64plus-gfxplugin", "mupen64plus-rspmode")
_RETROARCH_MACOS_N64_CORE_OPTIONS = {
    "mupen64plus-rdp-plugin": "angrylion",
    "mupen64plus-rsp-plugin": "hle",
}
_STEAMOS_RELEASE_PATH = Path("/etc/os-release")
_DMI_BOARD_VENDOR_PATH = Path("/sys/devices/virtual/dmi/id/board_vendor")
logger = logging.getLogger(__name__)


class RetroArchMacOSN64RemediationError(RuntimeError):
    """Raised when the managed macOS N64 RetroArch baseline cannot be converged safely."""


def _is_steam_deck_linux() -> bool:
    if not _SYS_PLATFORM.startswith("linux"):
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
    if _OS_NAME == "nt" and value.startswith((":\\", ":/")):
        return cfg_path.parent / value[2:]
    candidate = _path_with_tilde_expanded(value)
    if not candidate.is_absolute():
        candidate = cfg_path.parent / candidate
    return candidate


def _resolve_retroarch_remap_dir(cfg_path: Path, lines: list[str]) -> Path:
    raw_remap = read_simple_cfg_key(lines, _RETROARCH_REMAP_DIRECTORY_KEY)
    if raw_remap:
        return _resolve_retroarch_cfg_path(raw_remap, cfg_path=cfg_path)
    return _resolve_retroarch_config_dir(cfg_path, lines) / "remaps"


def _resolve_retroarch_config_dir(cfg_path: Path, lines: list[str]) -> Path:
    raw_config_dir = read_simple_cfg_key(lines, _RETROARCH_CONFIG_DIRECTORY_KEY)
    if raw_config_dir:
        return _resolve_retroarch_cfg_path(raw_config_dir, cfg_path=cfg_path)
    return cfg_path.parent / "config"


def _retroarch_game_specific_options_enabled(lines: list[str]) -> bool:
    return _normalized_cfg_value(read_simple_cfg_key(lines, _RETROARCH_GAME_SPECIFIC_OPTIONS_KEY)) == "true"


def _write_retroarch_simple_cfg_updates(
    path: Path,
    *,
    updates: dict[str, str],
    kind: str,
    create_if_missing: bool,
    keep_limit: int,
    remove_keys: tuple[str, ...] = (),
) -> bool:
    if not path.exists() and not create_if_missing:
        return False
    lines = read_ini_lines(path)
    if remove_keys:
        lines, removed = _remove_simple_cfg_keys(lines, remove_keys)
    else:
        removed = False
    changed = False
    for key, value in updates.items():
        existing_value = read_simple_cfg_key(lines, key)
        if _normalized_cfg_value(existing_value) != value.casefold() or not path.exists():
            lines, updated = upsert_simple_cfg_key(lines, key, value)
            changed |= updated
    changed = changed or removed
    if changed or (create_if_missing and not path.exists()):
        if path.exists():
            backup_result = backup_existing_file(path, keep_limit=keep_limit)
            if backup_result.created_path is not None:
                logger.info(
                    "retroarch runtime backup created path=%s backup=%s kind=%s",
                    path,
                    backup_result.created_path,
                    kind,
                )
            for pruned_path in backup_result.pruned_paths:
                logger.info(
                    "retroarch runtime backup pruned path=%s pruned_backup=%s kind=%s",
                    path,
                    pruned_path,
                    kind,
                )
        write_ini_atomic(path, lines)
        logger.info("retroarch runtime config updated path=%s kind=%s", path, kind)
    return changed


def _remove_simple_cfg_keys(lines: list[str], keys: tuple[str, ...]) -> tuple[list[str], bool]:
    key_names = {key.casefold() for key in keys}
    if not key_names:
        return lines, False
    changed = False
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";") or "=" not in stripped:
            output.append(line)
            continue
        current_key = stripped.split("=", 1)[0].strip().casefold()
        if current_key in key_names:
            changed = True
            continue
        output.append(line)
    return output, changed


def _write_retroarch_remap_file(
    remap_dir: Path,
    *,
    core_name: str,
    keep_limit: int,
) -> tuple[Path, bool]:
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
            backup_result = backup_existing_file(remap_path, keep_limit=keep_limit)
            if backup_result.created_path is not None:
                logger.info(
                    "retroarch runtime backup created path=%s backup=%s kind=remap",
                    remap_path,
                    backup_result.created_path,
                )
            for pruned_path in backup_result.pruned_paths:
                logger.info(
                    "retroarch runtime backup pruned path=%s pruned_backup=%s kind=remap",
                    remap_path,
                    pruned_path,
                )
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
    if _SYS_PLATFORM == "darwin" and config.macos.retroarch_cfg_path is not None:
        return config.macos.retroarch_cfg_path.expanduser()
    for candidate in candidates:
        if candidate.exists():
            return candidate
    if _SYS_PLATFORM == "darwin":
        if candidates:
            return candidates[0]
        return None
    if config.linux.retroarch_cfg_path is not None:
        return config.linux.retroarch_cfg_path.expanduser()
    return None


def _normalized_cfg_value(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip().strip('"').strip("'").casefold()


def _resolve_macos_n64_core_path(config: GamehubConfig, *, cfg_path: Path) -> Path | None:
    if _SYS_PLATFORM != "darwin":
        return None
    resolved_paths = resolve_retroarch_paths(
        explicit_cores_dir=config.macos.retroarch_cores_dir,
        explicit_info_dir=config.macos.retroarch_info_dir,
        explicit_cfg_path=config.macos.retroarch_cfg_path or cfg_path,
    )
    if resolved_paths is None:
        return None
    return resolved_paths.cores_dir / _RETROARCH_MUPEN64PLUS_NEXT_CORE_FILENAME


def _macos_n64_remediation_error(*, message: str) -> RetroArchMacOSN64RemediationError:
    return RetroArchMacOSN64RemediationError(f"managed macOS N64 launch blocked: {message}")


def _apply_macos_n64_remediation(
    *,
    config: GamehubConfig,
    cfg_path: Path,
    lines: list[str],
    core_options_path: Path,
    core_lines: list[str],
    strict: bool,
    verbose: bool,
    writer: Callable[[str], None],
) -> tuple[list[str], list[str], bool, bool, Path | None]:
    if _SYS_PLATFORM != "darwin":
        return lines, core_lines, False, False, None

    core_path = _resolve_macos_n64_core_path(config, cfg_path=cfg_path)
    if core_path is None:
        if strict:
            raise _macos_n64_remediation_error(
                message=(
                    "RetroArch cores directory could not be resolved; set [macos].retroarch_cores_dir "
                    "or run gamehub init first"
                )
            )
        if verbose:
            writer("retroarch\tskipped\tn64_macos_remediation\treason=cores_dir_unresolved")
        return lines, core_lines, False, False, None
    if not core_path.exists():
        if strict:
            raise _macos_n64_remediation_error(
                message=(
                    f"required core {_RETROARCH_MUPEN64PLUS_NEXT_CORE_FILENAME} was not found at {core_path}; "
                    "run gamehub init or set [macos].retroarch_cores_dir explicitly"
                )
            )
        if verbose:
            writer(f"retroarch\tskipped\tn64_macos_remediation\treason=core_missing\tcore={core_path}")
        return lines, core_lines, False, False, core_path

    changed_config = False
    existing_video_driver = read_simple_cfg_key(lines, _RETROARCH_VIDEO_DRIVER_KEY)
    if _normalized_cfg_value(existing_video_driver) != _RETROARCH_VIDEO_DRIVER_GLCORE or not cfg_path.exists():
        lines, updated = upsert_simple_cfg_key(lines, _RETROARCH_VIDEO_DRIVER_KEY, _RETROARCH_VIDEO_DRIVER_GLCORE)
        changed_config |= updated

    changed_core_options = False
    core_lines, removed_legacy_core_options = _remove_simple_cfg_keys(
        core_lines, _RETROARCH_MACOS_N64_LEGACY_CORE_OPTION_KEYS
    )
    changed_core_options |= removed_legacy_core_options
    for key, value in _RETROARCH_MACOS_N64_CORE_OPTIONS.items():
        existing_value = read_simple_cfg_key(core_lines, key)
        if _normalized_cfg_value(existing_value) != value.casefold() or not core_options_path.exists():
            core_lines, updated = upsert_simple_cfg_key(core_lines, key, value)
            changed_core_options |= updated

    return lines, core_lines, changed_config, changed_core_options, core_path


def configure_managed_macos_n64_content_runtime(
    *,
    config: GamehubConfig,
    rom_rel_path: str,
) -> bool:
    if _SYS_PLATFORM != "darwin":
        return False

    cfg_path = _resolve_retroarch_cfg_target(config=config)
    if cfg_path is None:
        raise _macos_n64_remediation_error(
            message=(
                "RetroArch config path could not be resolved; set [macos].retroarch_cfg_path "
                "or create the managed RetroArch config first"
            )
        )

    rom_path = Path(rom_rel_path.replace("\\", "/"))
    rom_stem = rom_path.stem.strip()
    if not rom_stem:
        raise _macos_n64_remediation_error(message="managed macOS N64 launch is missing a ROM name")

    cfg_lines = read_ini_lines(cfg_path)
    override_dir = _resolve_retroarch_config_dir(cfg_path, cfg_lines) / _RETROARCH_MUPEN64PLUS_NEXT_CONFIG_DIRNAME
    changed = False

    override_cfg_paths = [
        override_dir / f"{_RETROARCH_MUPEN64PLUS_NEXT_CONFIG_DIRNAME}.cfg",
    ]
    content_dir_name = rom_path.parent.name.strip()
    if content_dir_name:
        override_cfg_paths.append(override_dir / f"{content_dir_name}.cfg")
    override_cfg_paths.append(override_dir / f"{rom_stem}.cfg")

    for override_path in override_cfg_paths:
        changed |= _write_retroarch_simple_cfg_updates(
            override_path,
            updates={_RETROARCH_VIDEO_DRIVER_KEY: _RETROARCH_VIDEO_DRIVER_GLCORE},
            kind="n64-macos-override",
            create_if_missing=False,
            keep_limit=config.backups.keep_limit,
        )

    override_opt_paths = [
        override_dir / f"{_RETROARCH_MUPEN64PLUS_NEXT_CONFIG_DIRNAME}.opt",
    ]
    if content_dir_name:
        override_opt_paths.append(override_dir / f"{content_dir_name}.opt")
    override_opt_paths.append(override_dir / f"{rom_stem}.opt")

    if any(path.exists() for path in override_opt_paths) or _retroarch_game_specific_options_enabled(cfg_lines):
        for override_path in override_opt_paths:
            changed |= _write_retroarch_simple_cfg_updates(
                override_path,
                updates=_RETROARCH_MACOS_N64_CORE_OPTIONS,
                kind="n64-macos-core-options-override",
                create_if_missing=False,
                keep_limit=config.backups.keep_limit,
                remove_keys=_RETROARCH_MACOS_N64_LEGACY_CORE_OPTION_KEYS,
            )

    return changed


def configure_retroarch_runtime(
    config: GamehubConfig,
    dry_run: bool,
    verbose: bool,
    writer: Callable[[str], None],
    *,
    strict_macos_n64: bool = False,
) -> Path | None:
    cfg_path = _resolve_retroarch_cfg_target(config=config)
    if cfg_path is None:
        if strict_macos_n64 and _SYS_PLATFORM == "darwin":
            raise _macos_n64_remediation_error(
                message=(
                    "RetroArch config path could not be resolved; set [macos].retroarch_cfg_path "
                    "or create the managed RetroArch config first"
                )
            )
        if verbose:
            writer("retroarch\tskipped\thotkeys\treason=config_missing")
        return None
    core_options_path = cfg_path.with_name("retroarch-core-options.cfg")

    if dry_run:
        if verbose:
            if _OS_NAME == "nt":
                details = f"menu_combo={_RETROARCH_MENU_COMBO_LABEL}\tall_users_menu=true"
            else:
                details = (
                    f"menu_combo={_RETROARCH_MENU_COMBO_LABEL}\tall_users_menu=true\t"
                    f"analog_dpad_mode={_RETROARCH_ANALOG_DPAD_VALUE}\tlibretro_device_p1=261"
                )
            writer(f"retroarch\tdry-run\tconfigure\t{cfg_path}\t{details}")
            writer(f"retroarch\tdry-run\tcore-options\t{core_options_path}\tpsx_controller=AnalogController")
            dry_run_n64_core_path = _resolve_macos_n64_core_path(config, cfg_path=cfg_path)
            if dry_run_n64_core_path is not None and dry_run_n64_core_path.exists():
                writer(
                    "retroarch\tdry-run\tn64_macos_remediation\t"
                    f"{cfg_path}\tvideo_driver={_RETROARCH_VIDEO_DRIVER_GLCORE}\t"
                    "mupen64plus-rdp-plugin=angrylion\tmupen64plus-rsp-plugin=hle"
                )
            elif _SYS_PLATFORM == "darwin":
                writer(f"retroarch\tdry-run\tn64_macos_remediation\t{cfg_path}\treason=core_missing_or_unresolved")
            remap_dir = _resolve_retroarch_remap_dir(cfg_path, read_ini_lines(cfg_path))
            writer(
                "retroarch\tdry-run\tremap\t"
                f"{remap_dir / _RETROARCH_SWANSTATION_CORE_NAME / (_RETROARCH_SWANSTATION_CORE_NAME + '.rmp')}"
            )
        return cfg_path

    lines = read_ini_lines(cfg_path)
    existing_combo = read_simple_cfg_key(lines, _RETROARCH_MENU_COMBO_KEY)
    existing_all_users = read_simple_cfg_key(lines, _RETROARCH_ALL_USERS_MENU_KEY)
    is_windows = _OS_NAME == "nt"
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
    n64_config_changed = False
    n64_core_changed = False
    n64_core_path: Path | None = None
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
    core_lines = read_ini_lines(core_options_path)
    lines, core_lines, n64_config_changed, n64_core_changed, n64_core_path = _apply_macos_n64_remediation(
        config=config,
        cfg_path=cfg_path,
        lines=lines,
        core_options_path=core_options_path,
        core_lines=core_lines,
        strict=strict_macos_n64,
        verbose=verbose,
        writer=writer,
    )
    if (
        changed_combo
        or changed_all_users
        or changed_joypad_driver
        or n64_config_changed
        or (not is_windows and (changed_analog or changed_libretro or changed_remap or changed_turbo))
        or not cfg_path.exists()
    ):
        if cfg_path.exists():
            backup_result = backup_existing_file(cfg_path, keep_limit=config.backups.keep_limit)
            if backup_result.created_path is not None:
                logger.info(
                    "retroarch runtime backup created path=%s backup=%s kind=config",
                    cfg_path,
                    backup_result.created_path,
                )
            for pruned_path in backup_result.pruned_paths:
                logger.info(
                    "retroarch runtime backup pruned path=%s pruned_backup=%s kind=config",
                    cfg_path,
                    pruned_path,
                )
        write_ini_atomic(cfg_path, lines)
        logger.info("retroarch runtime config updated path=%s kind=config", cfg_path)
    core_changed = False
    for key, value in _RETROARCH_PSX_CORE_OPTIONS.items():
        existing_value = read_simple_cfg_key(core_lines, key)
        if existing_value != value or not core_options_path.exists():
            core_lines, changed = upsert_simple_cfg_key(core_lines, key, value)
            core_changed |= changed
    core_changed = core_changed or n64_core_changed
    if core_changed or not core_options_path.exists():
        if core_options_path.exists():
            backup_result = backup_existing_file(core_options_path, keep_limit=config.backups.keep_limit)
            if backup_result.created_path is not None:
                logger.info(
                    "retroarch runtime backup created path=%s backup=%s kind=core-options",
                    core_options_path,
                    backup_result.created_path,
                )
            for pruned_path in backup_result.pruned_paths:
                logger.info(
                    "retroarch runtime backup pruned path=%s pruned_backup=%s kind=core-options",
                    core_options_path,
                    pruned_path,
                )
        write_ini_atomic(core_options_path, core_lines)
        logger.info("retroarch runtime config updated path=%s kind=core-options", core_options_path)
    if n64_config_changed or n64_core_changed:
        logger.info(
            "retroarch runtime config updated path=%s kind=n64-macos-remediation core=%s",
            cfg_path,
            n64_core_path,
        )
    remap_dir = _resolve_retroarch_remap_dir(cfg_path, lines)
    remap_path, _ = _write_retroarch_remap_file(
        remap_dir,
        core_name=_RETROARCH_SWANSTATION_CORE_NAME,
        keep_limit=config.backups.keep_limit,
    )
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
        if n64_core_path is not None and n64_core_path.exists():
            writer(
                "retroarch\tconfigured\tn64_macos_remediation\t"
                f"{cfg_path}\tvideo_driver={_RETROARCH_VIDEO_DRIVER_GLCORE}\t"
                "mupen64plus-rdp-plugin=angrylion\tmupen64plus-rsp-plugin=hle"
            )
        writer(f"retroarch\tconfigured\tremap\t{remap_path}")
    return cfg_path
