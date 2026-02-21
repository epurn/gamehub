from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path, PosixPath
from typing import Callable
from uuid import uuid4

from gamehub_common.ids import sha256_file
from gamehub_common.models import LibraryIndex

from ..common.config import GamehubConfig
from ..common.fsops import replace_file
from ..common.platform_paths import (
    AZAHAR_FLATPAK_APP_ID,
    PCSX2_FLATPAK_APP_ID,
    is_flatpak_command,
    linux_flatpak_azahar_config_root,
    linux_flatpak_azahar_root,
    linux_flatpak_pcsx2_root,
)
from ..emulators import resolve_emulator_executable
from . import pcsx2_ini as pcsx2_ini
from . import targets as firmware_targets

_RETROARCH_SYSTEM_NAMES = {"GB", "GBA", "GBC", "GEN_MD", "N64", "NDS", "NES", "PSX", "SNES"}
_RETROARCH_MENU_COMBO_KEY = "input_menu_toggle_gamepad_combo"
_RETROARCH_MENU_COMBO_VALUE = "4"
_RETROARCH_MENU_COMBO_LABEL = "Start+Select"
_RETROARCH_ALL_USERS_MENU_KEY = "all_users_control_menu"
_RETROARCH_ALL_USERS_MENU_VALUE = "true"
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
_AZAHAR_FULLSCREEN_KEY = "fullscreen"
_AZAHAR_FULLSCREEN_DEFAULT_KEY = r"fullscreen\default"
_AZAHAR_FULLSCREEN_VALUE = "true"
_AZAHAR_FULLSCREEN_DEFAULT_VALUE = "false"
_AZAHAR_CONFIRM_CLOSE_KEY = "confirmClose"
_AZAHAR_CONFIRM_CLOSE_DEFAULT_KEY = r"confirmClose\default"
_AZAHAR_CONFIRM_CLOSE_VALUE = "false"
_AZAHAR_CONFIRM_CLOSE_DEFAULT_VALUE = "false"


def _read_simple_cfg_key(lines: list[str], key: str) -> str | None:
    key_name = key.casefold()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";") or "=" not in stripped:
            continue
        current_key, current_value = stripped.split("=", 1)
        if current_key.strip().casefold() != key_name:
            continue
        value = current_value.split("#", 1)[0].split(";", 1)[0].strip()
        return value.strip('"').strip("'")
    return None


def _upsert_simple_cfg_key(lines: list[str], key: str, value: str) -> tuple[list[str], bool]:
    key_name = key.casefold()
    desired = f'{key} = "{value}"'
    changed = False
    found = False
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";") or "=" not in stripped:
            output.append(line)
            continue
        current_key = stripped.split("=", 1)[0].strip().casefold()
        if current_key != key_name:
            output.append(line)
            continue
        found = True
        if stripped != desired:
            output.append(desired)
            changed = True
        else:
            output.append(line)
    if not found:
        if output and output[-1].strip():
            output.append("")
        output.append(desired)
        changed = True
    return output, changed


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
    raw_remap = _read_simple_cfg_key(lines, _RETROARCH_REMAP_DIRECTORY_KEY)
    if raw_remap:
        return _resolve_retroarch_cfg_path(raw_remap, cfg_path=cfg_path)
    raw_config_dir = _read_simple_cfg_key(lines, _RETROARCH_CONFIG_DIRECTORY_KEY)
    if raw_config_dir:
        return _resolve_retroarch_cfg_path(raw_config_dir, cfg_path=cfg_path) / "remaps"
    return cfg_path.parent / "config" / "remaps"


def _write_retroarch_remap_file(remap_dir: Path, *, core_name: str) -> tuple[Path, bool]:
    remap_path = remap_dir / core_name / f"{core_name}.rmp"
    remap_lines = _read_ini_lines(remap_path)
    changed = False
    for key in _RETROARCH_LIBRETRO_DEVICE_KEYS:
        desired = _RETROARCH_LIBRETRO_DEVICE_VALUES.get(key, _RETROARCH_LIBRETRO_DEVICE_DEFAULT)
        remap_lines, updated = _upsert_simple_cfg_key(remap_lines, key, desired)
        changed |= updated
    for key in _RETROARCH_ANALOG_DPAD_KEYS:
        remap_lines, updated = _upsert_simple_cfg_key(remap_lines, key, _RETROARCH_ANALOG_DPAD_VALUE)
        changed |= updated
    for key, desired in _RETROARCH_REMAP_PORT_VALUES.items():
        remap_lines, updated = _upsert_simple_cfg_key(remap_lines, key, desired)
        changed |= updated
    for key, desired in _RETROARCH_TURBO_KEYS.items():
        remap_lines, updated = _upsert_simple_cfg_key(remap_lines, key, desired)
        changed |= updated
    if changed or not remap_path.exists():
        _write_ini_atomic(remap_path, remap_lines)
    return remap_path, changed


def _upsert_qsettings_key(lines: list[str], key: str, value: str) -> tuple[list[str], bool]:
    key_name = key.casefold()
    desired = f"{key}={value}"
    changed = False
    found = False
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";") or "=" not in stripped:
            output.append(line)
            continue
        current_key = stripped.split("=", 1)[0].strip().casefold()
        if current_key != key_name:
            output.append(line)
            continue
        found = True
        if stripped != desired:
            output.append(desired)
            changed = True
        else:
            output.append(line)
    if not found:
        if output and output[-1].strip():
            output.append("")
        output.append(desired)
        changed = True
    return output, changed


def _read_qsettings_key(lines: list[str], key: str) -> str | None:
    key_name = key.casefold()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";") or "=" not in stripped:
            continue
        current_key, current_value = stripped.split("=", 1)
        if current_key.strip().casefold() != key_name:
            continue
        return current_value.strip()
    return None


def _retroarch_menu_combo_requires_migration(binding: str | None) -> bool:
    if not binding:
        return True
    return binding.strip().strip('"').strip("'") != _RETROARCH_MENU_COMBO_VALUE


def _retroarch_all_users_menu_requires_migration(binding: str | None) -> bool:
    if not binding:
        return True
    return binding.strip().strip('"').strip("'").casefold() != _RETROARCH_ALL_USERS_MENU_VALUE


def _sync_targets_module() -> None:
    setattr(firmware_targets, "resolve_emulator_executable", resolve_emulator_executable)
    setattr(firmware_targets, "os", os)
    setattr(firmware_targets, "sys", sys)
    setattr(firmware_targets, "Path", Path)


def _retroarch_cfg_candidates(config: GamehubConfig | None = None) -> list[Path]:
    _sync_targets_module()
    return firmware_targets.retroarch_cfg_candidates_for_config(config)


def _resolve_retroarch_system_dirs(config: GamehubConfig | None = None) -> list[Path]:
    _sync_targets_module()
    return firmware_targets.resolve_retroarch_system_dirs(config)


def _pcsx2_ini_candidates(config: GamehubConfig | None = None) -> list[Path]:
    _sync_targets_module()
    return firmware_targets.pcsx2_ini_candidates(config)


def _resolve_pcsx2_bios_dirs(config: GamehubConfig | None = None) -> list[Path]:
    _sync_targets_module()
    return firmware_targets.resolve_pcsx2_bios_dirs(config)


def _resolve_dolphin_user_dirs(config: GamehubConfig | None = None) -> list[Path]:
    _sync_targets_module()
    return firmware_targets.resolve_dolphin_user_dirs(config)


def _resolve_dolphin_runtime_user_dir(config: GamehubConfig | None = None) -> Path:
    _sync_targets_module()
    return firmware_targets.resolve_dolphin_runtime_user_dir(config)


def _resolve_dolphin_config_dirs(config: GamehubConfig | None = None) -> list[Path]:
    _sync_targets_module()
    return firmware_targets.resolve_dolphin_config_dirs(config)


def _target_dirs_for_system(system_name: str, config: GamehubConfig | None = None) -> list[Path]:
    _sync_targets_module()
    return firmware_targets.target_dirs_for_system(system_name, config)


def _default_pcsx2_ini_path(config: GamehubConfig | None = None) -> Path:
    override = None
    if config is not None:
        override = config.linux.pcsx2_ini_path
    if override is not None:
        return override.expanduser()

    prefer_flatpak = False
    if sys.platform.startswith("linux"):
        pcsx2_raw = resolve_emulator_executable("pcsx2").strip('"')
        pcsx2_exe = Path(pcsx2_raw)
        prefer_flatpak = is_flatpak_command(pcsx2_exe, PCSX2_FLATPAK_APP_ID) or (
            PCSX2_FLATPAK_APP_ID.casefold() in pcsx2_raw.casefold()
        )
        if prefer_flatpak:
            return linux_flatpak_pcsx2_root() / "inis" / "PCSX2.ini"

    for candidate in _pcsx2_ini_candidates(config=config):
        if candidate.exists():
            return candidate

    if sys.platform.startswith("linux"):
        if prefer_flatpak:
            return linux_flatpak_pcsx2_root() / "inis" / "PCSX2.ini"
        return Path.home() / ".config" / "PCSX2" / "inis" / "PCSX2.ini"

    candidates = _pcsx2_ini_candidates(config=config)
    if candidates:
        return candidates[0]
    return Path.home() / "Documents" / "PCSX2" / "inis" / "PCSX2.ini"


def _default_dolphin_ini_path(config: GamehubConfig | None = None) -> Path:
    return _resolve_dolphin_runtime_user_dir(config=config) / "Config" / "Dolphin.ini"


def _default_azahar_qt_config_path(config: GamehubConfig | None = None) -> Path:
    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        # Test suites can monkeypatch os.name="nt" on non-Windows hosts.
        # Keep mocked Windows branches host-safe by selecting a native path class.
        if sys.platform.startswith("win"):
            return Path(appdata) / "Azahar" / "config" / "qt-config.ini"
        return PosixPath(appdata) / "Azahar" / "config" / "qt-config.ini"

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


def _sha256(path: Path) -> str:
    return sha256_file(path)


def _copy_or_link(source: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and _sha256(destination) == _sha256(source):
        return "up_to_date"

    tmp = destination.with_name(f"{destination.name}.{uuid4().hex}.tmp")
    shutil.copy2(source, tmp)
    mode = "copied"
    replace_file(tmp, destination)
    return mode


def _sync_pcsx2_ini_module() -> None:
    setattr(pcsx2_ini, "os", os)
    setattr(pcsx2_ini, "Path", Path)
    setattr(pcsx2_ini, "replace_file", replace_file)


def _read_ini_lines(path: Path) -> list[str]:
    _sync_pcsx2_ini_module()
    return pcsx2_ini.read_ini_lines(path)


def _upsert_ini_key(lines: list[str], section: str, key: str, value: str) -> tuple[list[str], bool]:
    _sync_pcsx2_ini_module()
    return pcsx2_ini.upsert_ini_key(lines, section, key, value)


def _write_ini_atomic(path: Path, lines: list[str]) -> None:
    _sync_pcsx2_ini_module()
    pcsx2_ini.write_ini_atomic(path, lines)


def _resolve_retroarch_cfg_target(config: GamehubConfig) -> Path | None:
    for candidate in _retroarch_cfg_candidates(config=config):
        if candidate.exists():
            return candidate
    if config.linux.retroarch_cfg_path is not None:
        return config.linux.retroarch_cfg_path.expanduser()
    return None


def _configure_retroarch_runtime(
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
            remap_dir = _resolve_retroarch_remap_dir(cfg_path, _read_ini_lines(cfg_path))
            writer(
                "retroarch\tdry-run\tremap\t"
                f"{remap_dir / _RETROARCH_SWANSTATION_CORE_NAME / (_RETROARCH_SWANSTATION_CORE_NAME + '.rmp')}"
            )
        return cfg_path

    lines = _read_ini_lines(cfg_path)
    existing_combo = _read_simple_cfg_key(lines, _RETROARCH_MENU_COMBO_KEY)
    existing_all_users = _read_simple_cfg_key(lines, _RETROARCH_ALL_USERS_MENU_KEY)
    is_windows = os.name == "nt"
    existing_analog = (
        {key: _read_simple_cfg_key(lines, key) for key in _RETROARCH_ANALOG_DPAD_KEYS} if not is_windows else {}
    )
    existing_libretro = (
        {key: _read_simple_cfg_key(lines, key) for key in _RETROARCH_LIBRETRO_DEVICE_KEYS} if not is_windows else {}
    )
    existing_remap = (
        {key: _read_simple_cfg_key(lines, key) for key in _RETROARCH_REMAP_PORT_KEYS} if not is_windows else {}
    )
    existing_turbo = {key: _read_simple_cfg_key(lines, key) for key in _RETROARCH_TURBO_KEYS} if not is_windows else {}
    changed_combo = False
    changed_all_users = False
    changed_analog = False
    changed_libretro = False
    changed_remap = False
    changed_turbo = False
    if _retroarch_menu_combo_requires_migration(existing_combo) or not cfg_path.exists():
        lines, changed_combo = _upsert_simple_cfg_key(
            lines,
            _RETROARCH_MENU_COMBO_KEY,
            _RETROARCH_MENU_COMBO_VALUE,
        )
    if _retroarch_all_users_menu_requires_migration(existing_all_users) or not cfg_path.exists():
        lines, changed_all_users = _upsert_simple_cfg_key(
            lines,
            _RETROARCH_ALL_USERS_MENU_KEY,
            _RETROARCH_ALL_USERS_MENU_VALUE,
        )
    if not is_windows:
        for key in _RETROARCH_ANALOG_DPAD_KEYS:
            existing_value = existing_analog.get(key)
            if not existing_value or existing_value != _RETROARCH_ANALOG_DPAD_VALUE or not cfg_path.exists():
                lines, changed = _upsert_simple_cfg_key(lines, key, _RETROARCH_ANALOG_DPAD_VALUE)
                changed_analog |= changed
        for key in _RETROARCH_LIBRETRO_DEVICE_KEYS:
            desired = _RETROARCH_LIBRETRO_DEVICE_VALUES.get(key, _RETROARCH_LIBRETRO_DEVICE_DEFAULT)
            existing_value = existing_libretro.get(key)
            if not existing_value or existing_value != desired or not cfg_path.exists():
                lines, changed = _upsert_simple_cfg_key(lines, key, desired)
                changed_libretro |= changed
        for key in _RETROARCH_REMAP_PORT_KEYS:
            desired_port = _RETROARCH_REMAP_PORT_VALUES.get(key)
            existing_value = existing_remap.get(key)
            if desired_port is not None and (
                not existing_value or existing_value != desired_port or not cfg_path.exists()
            ):
                lines, changed = _upsert_simple_cfg_key(lines, key, desired_port)
                changed_remap |= changed
        for key, desired in _RETROARCH_TURBO_KEYS.items():
            existing_value = existing_turbo.get(key)
            if not existing_value or existing_value != desired or not cfg_path.exists():
                lines, changed = _upsert_simple_cfg_key(lines, key, desired)
                changed_turbo |= changed
    if (
        changed_combo
        or changed_all_users
        or (not is_windows and (changed_analog or changed_libretro or changed_remap or changed_turbo))
        or not cfg_path.exists()
    ):
        _write_ini_atomic(cfg_path, lines)
    core_lines = _read_ini_lines(core_options_path)
    core_changed = False
    for key, value in _RETROARCH_PSX_CORE_OPTIONS.items():
        existing_value = _read_simple_cfg_key(core_lines, key)
        if existing_value != value or not core_options_path.exists():
            core_lines, changed = _upsert_simple_cfg_key(core_lines, key, value)
            core_changed |= changed
    if core_changed or not core_options_path.exists():
        _write_ini_atomic(core_options_path, core_lines)
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


def _configure_pcsx2_runtime(
    config: GamehubConfig,
    dry_run: bool,
    verbose: bool,
    writer: Callable[[str], None],
) -> Path:
    override_bios_dir = config.linux.pcsx2_bios_dir.expanduser() if config.linux.pcsx2_bios_dir is not None else None
    pcsx2_raw = resolve_emulator_executable("pcsx2").strip('"')
    pcsx2_exe = Path(pcsx2_raw)
    prefer_flatpak = is_flatpak_command(pcsx2_exe, PCSX2_FLATPAK_APP_ID) or (
        PCSX2_FLATPAK_APP_ID.casefold() in pcsx2_raw.casefold()
    )
    if override_bios_dir is not None:
        bios_dir = override_bios_dir
    elif prefer_flatpak:
        bios_dir = linux_flatpak_pcsx2_root() / "bios"
    else:
        bios_dir = config.firmware_dir / "PS2"

    bios_dir_for_config = bios_dir.resolve(strict=False)
    ini_path = _default_pcsx2_ini_path(config=config)
    if dry_run:
        if verbose:
            writer(f"pcsx2\tdry-run\tconfigure\t{ini_path}\tbios={bios_dir_for_config}")
        return bios_dir_for_config

    lines = _read_ini_lines(ini_path)
    lines, changed_ui = _upsert_ini_key(lines, "UI", "SetupWizardIncomplete", "false")
    lines, changed_bios = _upsert_ini_key(lines, "Folders", "Bios", str(bios_dir_for_config))
    if changed_ui or changed_bios or not ini_path.exists():
        _write_ini_atomic(ini_path, lines)
    bios_dir_for_config.mkdir(parents=True, exist_ok=True)
    if verbose:
        writer(f"pcsx2\tconfigured\t{ini_path}\tbios={bios_dir_for_config}")
    return bios_dir_for_config


def _configure_dolphin_runtime(
    config: GamehubConfig,
    dry_run: bool,
    verbose: bool,
    writer: Callable[[str], None],
) -> Path:
    runtime_user_dir = _resolve_dolphin_runtime_user_dir(config=config)
    ini_paths = [_default_dolphin_ini_path(config=config)]
    extra_ini_paths = [path / "Config" / "Dolphin.ini" for path in _resolve_dolphin_config_dirs(config=config)]
    for candidate in extra_ini_paths:
        if candidate not in ini_paths:
            ini_paths.append(candidate)
    if dry_run:
        if verbose:
            for ini_path in ini_paths:
                writer(
                    f"dolphin\tdry-run\tconfigure\t{ini_path}\t"
                    "fullscreen=true\tconfirm_stop=false\tbackground_input=true"
                )
        return runtime_user_dir / "Config" / "Dolphin.ini"

    for ini_path in ini_paths:
        lines = _read_ini_lines(ini_path)
        lines, changed_fullscreen = _upsert_ini_key(lines, "Display", "Fullscreen", "True")
        lines, changed_confirm_stop = _upsert_ini_key(lines, "Interface", "ConfirmStop", "False")
        lines, changed_background_input = _upsert_ini_key(lines, "Interface", "BackgroundInput", "True")
        if changed_fullscreen or changed_confirm_stop or changed_background_input or not ini_path.exists():
            _write_ini_atomic(ini_path, lines)

        if verbose:
            writer(f"dolphin\tconfigured\t{ini_path}\tfullscreen=true\tconfirm_stop=false\tbackground_input=true")
    return runtime_user_dir / "Config" / "Dolphin.ini"


def _configure_azahar_runtime(
    config: GamehubConfig,
    dry_run: bool,
    verbose: bool,
    writer: Callable[[str], None] = print,
) -> Path:
    ini_path = _default_azahar_qt_config_path(config=config)
    details_parts = ["fullscreen=true", "confirm_exit_dialog=false"]
    details = "\t".join(details_parts)
    if dry_run:
        if verbose:
            writer(f"azahar\tdry-run\tconfigure\t{ini_path}\t{details}")
        return ini_path

    lines = _read_ini_lines(ini_path)
    lines, changed_fullscreen = _upsert_qsettings_key(lines, _AZAHAR_FULLSCREEN_KEY, _AZAHAR_FULLSCREEN_VALUE)
    lines, changed_fullscreen_default = _upsert_qsettings_key(
        lines, _AZAHAR_FULLSCREEN_DEFAULT_KEY, _AZAHAR_FULLSCREEN_DEFAULT_VALUE
    )
    lines, changed_confirm_close = _upsert_qsettings_key(lines, _AZAHAR_CONFIRM_CLOSE_KEY, _AZAHAR_CONFIRM_CLOSE_VALUE)
    lines, changed_confirm_close_default = _upsert_qsettings_key(
        lines, _AZAHAR_CONFIRM_CLOSE_DEFAULT_KEY, _AZAHAR_CONFIRM_CLOSE_DEFAULT_VALUE
    )
    if (
        changed_fullscreen
        or changed_fullscreen_default
        or changed_confirm_close
        or changed_confirm_close_default
        or not ini_path.exists()
    ):
        _write_ini_atomic(ini_path, lines)

    if verbose:
        writer(f"azahar\tconfigured\t{ini_path}\t{details}")
    return ini_path


def deploy_firmware_to_emulators(
    config: GamehubConfig,
    index: LibraryIndex,
    dry_run: bool,
    verbose: bool,
    writer: Callable[[str], None] = print,
) -> None:
    requested = 0
    applied = 0
    skipped = 0
    has_retroarch = any(system.name in _RETROARCH_SYSTEM_NAMES for system in index.systems)
    if has_retroarch:
        _configure_retroarch_runtime(
            config=config,
            dry_run=dry_run,
            verbose=verbose,
            writer=writer,
        )
    has_ps2 = any(system.name == "PS2" for system in index.systems)
    ps2_bios_target: Path | None = None
    if has_ps2:
        ps2_bios_target = _configure_pcsx2_runtime(config=config, dry_run=dry_run, verbose=verbose, writer=writer)
    has_dolphin = any(system.name in {"GC", "Wii"} for system in index.systems)
    if has_dolphin:
        _configure_dolphin_runtime(config=config, dry_run=dry_run, verbose=verbose, writer=writer)
    has_n3ds = any(system.name == "N3DS" for system in index.systems)
    if has_n3ds:
        _configure_azahar_runtime(config=config, dry_run=dry_run, verbose=verbose, writer=writer)

    for system in index.systems:
        if system.name == "PS2":
            target_dirs = [ps2_bios_target] if ps2_bios_target is not None else []
        else:
            target_dirs = _target_dirs_for_system(system.name, config=config)
        if not target_dirs:
            continue
        for firmware in system.firmware:
            source = config.firmware_dir / system.name / firmware.filename
            for target_dir in target_dirs:
                destination = target_dir / firmware.filename
                requested += 1
                if not source.exists():
                    if verbose:
                        writer(f"firmware\tmissing-source\t{source}\t->\t{destination}")
                    skipped += 1
                    continue
                if dry_run:
                    if verbose:
                        writer(f"firmware\tdry-run\t{source}\t->\t{destination}")
                    continue
                result = _copy_or_link(source, destination)
                if verbose:
                    writer(f"firmware\t{result}\t{source}\t->\t{destination}")
                if result == "up_to_date":
                    skipped += 1
                else:
                    applied += 1

    if dry_run:
        if verbose and requested > 0:
            writer(f"Firmware deployment dry-run targets: {requested}")
        return
    if requested == 0:
        return
    writer(f"Firmware deployment: targets={requested} applied={applied} skipped={skipped}")
