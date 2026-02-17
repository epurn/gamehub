from __future__ import annotations

import os
from pathlib import Path, PosixPath
import re
import shutil
import sys
from typing import Callable
from uuid import uuid4

from gamehub_common.ids import sha256_file
from gamehub_common.models import LibraryIndex

from .config import GamehubConfig
from .emulators import resolve_emulator_executable
import gamehub_cli.firmware_targets as firmware_targets
import gamehub_cli.pcsx2_ini as pcsx2_ini
from .fsops import replace_file
from .platform_paths import (
    AZAHAR_FLATPAK_APP_ID,
    PCSX2_FLATPAK_APP_ID,
    is_flatpak_command,
    linux_flatpak_azahar_root,
    linux_flatpak_azahar_config_root,
    linux_flatpak_pcsx2_root,
)

_DOLPHIN_GCPAD_BINDINGS = (
    ("Buttons/A", "SOUTH | `Button A`"),
    ("Buttons/B", "EAST | `Button B`"),
    ("Buttons/X", "WEST | `Button X`"),
    ("Buttons/Y", "NORTH | `Button Y`"),
    ("Buttons/Z", "`Trigger R`"),
    ("Buttons/Start", "START | Start"),
    ("Main Stick/Up", "`Axis 1-` | `Left Y+`"),
    ("Main Stick/Down", "`Axis 1+` | `Left Y-`"),
    ("Main Stick/Left", "`Axis 0-` | `Left X-`"),
    ("Main Stick/Right", "`Axis 0+` | `Left X+`"),
    ("Main Stick/Modifier", "`Thumb L`"),
    ("Main Stick/Modifier/Range", "50.000000000000000"),
    ("C-Stick/Up", "`Axis 3-` | `Right Y+`"),
    ("C-Stick/Down", "`Axis 3+` | `Right Y-`"),
    ("C-Stick/Left", "`Axis 2-` | `Right X-`"),
    ("C-Stick/Right", "`Axis 2+` | `Right X+`"),
    ("C-Stick/Modifier", "`Thumb R`"),
    ("C-Stick/Modifier/Range", "50.000000000000000"),
    ("Triggers/L", "`Shoulder L`"),
    ("Triggers/R", "`Shoulder R`"),
    ("Rumble/Motor", "`Motor L` | `Motor R`"),
    ("D-Pad/Up", "`Pad N`"),
    ("D-Pad/Down", "`Pad S`"),
    ("D-Pad/Left", "`Pad W`"),
    ("D-Pad/Right", "`Pad E`"),
)
_DOLPHIN_WIIMOTE_BINDINGS = (
    ("Buttons/A", "SOUTH | `Button A`"),
    ("Buttons/B", "EAST | `Button B`"),
    ("Buttons/1", "WEST | `Button X`"),
    ("Buttons/2", "NORTH | `Button Y`"),
    ("Buttons/-", "BACK | Back"),
    ("Buttons/+", "START | Start"),
    ("Buttons/Home", "GUIDE | `Thumb R`"),
    ("D-Pad/Up", "`Pad N`"),
    ("D-Pad/Down", "`Pad S`"),
    ("D-Pad/Left", "`Pad W`"),
    ("D-Pad/Right", "`Pad E`"),
    ("IR/Up", "`Axis 3-` | `Right Y-`"),
    ("IR/Down", "`Axis 3+` | `Right Y+`"),
    ("IR/Left", "`Axis 2-` | `Right X-`"),
    ("IR/Right", "`Axis 2+` | `Right X+`"),
    ("IR/Auto-Hide", "False"),
    ("Shake/X", "WEST | `Button X`"),
    ("Shake/Y", "WEST | `Button X`"),
    ("Shake/Z", "WEST | `Button X`"),
    ("Nunchuk/Stick/Up", "`Axis 1-` | `Left Y+`"),
    ("Nunchuk/Stick/Down", "`Axis 1+` | `Left Y-`"),
    ("Nunchuk/Stick/Left", "`Axis 0-` | `Left X-`"),
    ("Nunchuk/Stick/Right", "`Axis 0+` | `Left X+`"),
    ("Nunchuk/Buttons/C", "`Shoulder L`"),
    ("Nunchuk/Buttons/Z", "`Trigger L`"),
    ("Nunchuk/Shake/X", "`Trigger R`"),
    ("Nunchuk/Shake/Y", "`Trigger R`"),
    ("Nunchuk/Shake/Z", "`Trigger R`"),
    ("Rumble/Motor", "`Motor L` | `Motor R`"),
)
_PROC_INPUT_DEVICES_PATH = Path("/proc/bus/input/devices")
_INPUT_DEVICE_NAME_RE = re.compile(r'^N:\s+Name="(?P<name>.*)"$')
_INPUT_DEVICE_HANDLERS_RE = re.compile(r"^H:\s+Handlers=(?P<handlers>.+)$")
_INPUT_JS_HANDLER_RE = re.compile(r"\bjs(?P<index>\d+)\b")
_RETROARCH_SYSTEM_NAMES = {"GB", "GBA", "GBC", "GEN_MD", "N64", "NDS", "NES", "PSX", "SNES"}
_RETROARCH_MENU_COMBO_KEY = "input_menu_toggle_gamepad_combo"
_RETROARCH_MENU_COMBO_VALUE = "4"
_RETROARCH_MENU_COMBO_LABEL = "Start+Select"
_RETROARCH_ALL_USERS_MENU_KEY = "all_users_control_menu"
_RETROARCH_ALL_USERS_MENU_VALUE = "true"
_PCSX2_MENU_COMBO_LABEL = "Back+Start"
_DOLPHIN_GENERAL_STOP_MACRO = "@(SELECT+START)"
_AZAHAR_FULLSCREEN_KEY = "fullscreen"
_AZAHAR_FULLSCREEN_DEFAULT_KEY = r"fullscreen\default"
_AZAHAR_FULLSCREEN_VALUE = "true"
_AZAHAR_FULLSCREEN_DEFAULT_VALUE = "false"
_AZAHAR_CONFIRM_CLOSE_KEY = "confirmClose"
_AZAHAR_CONFIRM_CLOSE_DEFAULT_KEY = r"confirmClose\default"
_AZAHAR_CONFIRM_CLOSE_VALUE = "false"
_AZAHAR_CONFIRM_CLOSE_DEFAULT_VALUE = "false"
_AZAHAR_GUID_RE = re.compile(r"guid(?::|\$0)(?P<guid>[0-9a-fA-F]+)")
_AZAHAR_PORT_RE = re.compile(r"port(?::|\$0)(?P<port>\d+)")
_AZAHAR_BUTTON_BINDINGS: tuple[tuple[str, int], ...] = (
    ("button_a", 0),
    ("button_b", 1),
    ("button_x", 2),
    ("button_y", 3),
    ("button_select", 4),
    ("button_start", 6),
    ("button_l", 9),
    ("button_r", 10),
    ("button_up", 11),
    ("button_down", 12),
    ("button_left", 13),
    ("button_right", 14),
)


def _path_from_env_value(raw: str) -> Path:
    try:
        return Path(raw)
    except NotImplementedError:
        # Test harnesses may monkeypatch os.name="nt" on non-Windows hosts.
        # Fall back to a host-native path class so mocked Windows branches remain testable.
        return PosixPath(raw)


def _linux_detect_evdev_gamepads(*, max_devices: int = 2) -> tuple[str, ...]:
    if not sys.platform.startswith("linux"):
        return ()
    try:
        raw = _PROC_INPUT_DEVICES_PATH.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ()

    by_js_index: dict[int, str] = {}
    current_name: str | None = None
    current_handlers: str | None = None

    def _flush_entry() -> None:
        if not current_name or not current_handlers:
            return
        for match in _INPUT_JS_HANDLER_RE.finditer(current_handlers):
            js_index = int(match.group("index"))
            if js_index not in by_js_index:
                by_js_index[js_index] = current_name

    for line in [*raw.splitlines(), ""]:
        stripped = line.strip()
        if not stripped:
            _flush_entry()
            current_name = None
            current_handlers = None
            continue
        name_match = _INPUT_DEVICE_NAME_RE.match(stripped)
        if name_match:
            current_name = name_match.group("name")
            continue
        handlers_match = _INPUT_DEVICE_HANDLERS_RE.match(stripped)
        if handlers_match:
            current_handlers = handlers_match.group("handlers")

    if not by_js_index:
        return ()

    tokens: list[str] = []
    for evdev_index, js_index in enumerate(sorted(by_js_index)):
        device_name = by_js_index[js_index]
        tokens.append(f"evdev/{evdev_index}/{device_name}")
        if len(tokens) >= max_devices:
            break
    return tuple(tokens)


def _dolphin_linux_device_tokens() -> tuple[str, str]:
    detected = _linux_detect_evdev_gamepads(max_devices=2)
    if len(detected) >= 2:
        return detected[0], detected[1]
    if len(detected) == 1:
        return detected[0], "SDL/1/Gamepad"
    return "SDL/0/Gamepad", "SDL/1/Gamepad"


def _dolphin_hotkey_expression() -> str:
    # Keep one explicit AND-combo and normalize token variants inside OR groups.
    # Include Button 6/7 fallback for pads that expose numeric button names only.
    return (
        "((`BACK` | `Back` | `SELECT` | `Select` | `Button 6`) & "
        "(`START` | `Start` | `Button 7`))"
    )


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


def _azahar_profile_slot(lines: list[str]) -> int:
    raw_value = _read_qsettings_key(lines, "profile")
    if raw_value is None:
        return 1
    try:
        profile_idx = int(raw_value.strip())
    except ValueError:
        return 1
    if profile_idx < 0:
        return 1
    return profile_idx + 1


def _azahar_detect_sdl_identity(lines: list[str]) -> tuple[str | None, int]:
    guid: str | None = None
    port = 0
    for line in lines:
        stripped = line.strip()
        if not stripped or "=" not in stripped:
            continue
        value = stripped.split("=", 1)[1]
        lowered = value.casefold()
        if "engine:sdl" not in lowered and "engine$0sdl" not in lowered:
            continue
        guid_match = _AZAHAR_GUID_RE.search(value)
        if guid_match:
            guid = guid_match.group("guid")
        port_match = _AZAHAR_PORT_RE.search(value)
        if port_match:
            try:
                port = int(port_match.group("port"))
            except ValueError:
                port = 0
        if guid is not None:
            break
    return guid, port


def _azahar_should_migrate_digital_binding(binding: str | None) -> bool:
    if binding is None:
        return True
    lowered = binding.casefold()
    if "engine:sdl" in lowered:
        return False
    if "engine:keyboard" in lowered:
        return True
    # Preserve non-keyboard custom mappings (for example UDP/motion profiles).
    return False


def _azahar_should_migrate_analog_binding(binding: str | None) -> bool:
    if binding is None:
        return True
    lowered = binding.casefold()
    return "engine$0sdl" not in lowered and "engine:sdl" not in lowered


def _azahar_sdl_button_value(button_index: int, guid: str | None, port: int) -> str:
    parts = [f"button:{button_index}", "engine:sdl"]
    if guid:
        parts.append(f"guid:{guid}")
    parts.append(f"port:{port}")
    return f'"{",".join(parts)}"'


def _azahar_sdl_axis_term(axis: int, direction: str, threshold: str, guid: str | None, port: int) -> str:
    base = f"axis${axis:02d}$1direction$0{direction}$1engine$0sdl"
    if guid:
        base = f"{base}$1guid$0{guid}"
    return f"{base}$1port$0{port}$1threshold$0{threshold}"


def _azahar_sdl_stick_value(x_axis: int, y_axis: int, guid: str | None, port: int) -> str:
    down = _azahar_sdl_axis_term(y_axis, "+", "0.5", guid, port)
    left = _azahar_sdl_axis_term(x_axis, "-", "0-0.5", guid, port)
    right = _azahar_sdl_axis_term(x_axis, "+", "0.5", guid, port)
    up = _azahar_sdl_axis_term(y_axis, "-", "0-0.5", guid, port)
    payload = (
        f"down:{down},engine:analog_from_button,left:{left},"
        f"modifier:code$068$1engine$0keyboard,modifier_scale:0.500000,"
        f"right:{right},up:{up}"
    )
    return f'"{payload}"'


def _bootstrap_azahar_controllers(lines: list[str]) -> tuple[list[str], bool, str]:
    profile_slot = _azahar_profile_slot(lines)
    guid, port = _azahar_detect_sdl_identity(lines)
    changed = False
    for key_suffix, button_idx in _AZAHAR_BUTTON_BINDINGS:
        key_name = fr"profiles\{profile_slot}\{key_suffix}"
        current = _read_qsettings_key(lines, key_name)
        if not _azahar_should_migrate_digital_binding(current):
            continue
        lines, changed_binding = _upsert_qsettings_key(
            lines,
            key_name,
            _azahar_sdl_button_value(button_idx, guid, port),
        )
        lines, changed_default = _upsert_qsettings_key(lines, fr"{key_name}\default", "false")
        changed |= changed_binding or changed_default

    circle_key = fr"profiles\{profile_slot}\circle_pad"
    circle_binding = _read_qsettings_key(lines, circle_key)
    if _azahar_should_migrate_analog_binding(circle_binding):
        lines, changed_circle = _upsert_qsettings_key(lines, circle_key, _azahar_sdl_stick_value(0, 1, guid, port))
        lines, changed_circle_default = _upsert_qsettings_key(lines, fr"{circle_key}\default", "false")
        changed |= changed_circle or changed_circle_default

    c_stick_key = fr"profiles\{profile_slot}\c_stick"
    c_stick_binding = _read_qsettings_key(lines, c_stick_key)
    if _azahar_should_migrate_analog_binding(c_stick_binding):
        lines, changed_c_stick = _upsert_qsettings_key(lines, c_stick_key, _azahar_sdl_stick_value(2, 3, guid, port))
        lines, changed_c_stick_default = _upsert_qsettings_key(lines, fr"{c_stick_key}\default", "false")
        changed |= changed_c_stick or changed_c_stick_default

    details = f"controller_port={port}\tcontroller_guid={guid or 'auto'}"
    return lines, changed, details


def _retroarch_menu_combo_requires_migration(binding: str | None) -> bool:
    if not binding:
        return True
    return binding.strip().strip('"').strip("'") != _RETROARCH_MENU_COMBO_VALUE


def _retroarch_all_users_menu_requires_migration(binding: str | None) -> bool:
    if not binding:
        return True
    return binding.strip().strip('"').strip("'").casefold() != _RETROARCH_ALL_USERS_MENU_VALUE


def _sync_targets_module() -> None:
    firmware_targets.resolve_emulator_executable = resolve_emulator_executable
    firmware_targets.os = os
    firmware_targets.sys = sys
    firmware_targets.Path = Path


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
        return _path_from_env_value(appdata) / "Azahar" / "config" / "qt-config.ini"

    home = Path.home()
    flatpak_qt_config = linux_flatpak_azahar_config_root() / "qt-config.ini"
    flatpak_data_root = linux_flatpak_azahar_root()
    flatpak_export_user = home / ".local" / "share" / "flatpak" / "exports" / "bin" / AZAHAR_FLATPAK_APP_ID
    azahar_raw = resolve_emulator_executable("azahar").strip('"')
    azahar_exe = Path(azahar_raw)
    if (
        sys.platform.startswith("linux")
        and (
            is_flatpak_command(azahar_exe, AZAHAR_FLATPAK_APP_ID)
            or AZAHAR_FLATPAK_APP_ID.casefold() in azahar_raw.casefold()
            or flatpak_qt_config.parent.exists()
            or flatpak_data_root.exists()
            or flatpak_export_user.exists()
        )
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
    pcsx2_ini.os = os
    pcsx2_ini.Path = Path
    pcsx2_ini.replace_file = replace_file


def _read_ini_lines(path: Path) -> list[str]:
    _sync_pcsx2_ini_module()
    return pcsx2_ini.read_ini_lines(path)


def _upsert_ini_key(lines: list[str], section: str, key: str, value: str) -> tuple[list[str], bool]:
    _sync_pcsx2_ini_module()
    return pcsx2_ini.upsert_ini_key(lines, section, key, value)


def _remove_ini_key(lines: list[str], section: str, key: str) -> tuple[list[str], bool]:
    section_name = section.casefold()
    key_name = key.casefold()
    in_section = False
    changed = False
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1].strip().casefold()
            in_section = current == section_name
            output.append(line)
            continue
        if in_section and "=" in line:
            current_key = line.split("=", 1)[0].strip().casefold()
            if current_key == key_name:
                changed = True
                continue
        output.append(line)
    return output, changed


def _read_ini_key(lines: list[str], section: str, key: str) -> str | None:
    _sync_pcsx2_ini_module()
    return pcsx2_ini.read_ini_key(lines, section, key)


def _bootstrap_pcsx2_controllers(lines: list[str]) -> tuple[list[str], bool]:
    _sync_pcsx2_ini_module()
    return pcsx2_ini.bootstrap_pcsx2_controllers(lines)


def _bootstrap_pcsx2_hotkeys(lines: list[str]) -> tuple[list[str], bool]:
    _sync_pcsx2_ini_module()
    return pcsx2_ini.bootstrap_pcsx2_hotkeys(lines)


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

    if dry_run:
        if verbose:
            details = f"menu_combo={_RETROARCH_MENU_COMBO_LABEL}\tall_users_menu=true"
            writer(
                f"retroarch\tdry-run\tconfigure\t{cfg_path}\t{details}"
            )
        return cfg_path

    lines = _read_ini_lines(cfg_path)
    existing_combo = _read_simple_cfg_key(lines, _RETROARCH_MENU_COMBO_KEY)
    existing_all_users = _read_simple_cfg_key(lines, _RETROARCH_ALL_USERS_MENU_KEY)
    changed_combo = False
    changed_all_users = False
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
    if changed_combo or changed_all_users or not cfg_path.exists():
        _write_ini_atomic(cfg_path, lines)
    if verbose:
        details = f"menu_combo={_RETROARCH_MENU_COMBO_LABEL}\tall_users_menu=true"
        writer(
            f"retroarch\tconfigured\t{cfg_path}\t{details}"
        )
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
            writer(
                f"pcsx2\tdry-run\tconfigure\t{ini_path}\tbios={bios_dir_for_config}\t"
                f"controllers={config.linux.pcsx2_controller_autoconfig}\tmenu_combo={_PCSX2_MENU_COMBO_LABEL}"
            )
        return bios_dir_for_config

    lines = _read_ini_lines(ini_path)
    lines, changed_ui = _upsert_ini_key(lines, "UI", "SetupWizardIncomplete", "false")
    lines, changed_bios = _upsert_ini_key(lines, "Folders", "Bios", str(bios_dir_for_config))
    changed_controllers = False
    if sys.platform.startswith("linux") and config.linux.pcsx2_controller_autoconfig:
        lines, changed_controllers = _bootstrap_pcsx2_controllers(lines)
    lines, changed_hotkeys = _bootstrap_pcsx2_hotkeys(lines)
    if changed_ui or changed_bios or changed_controllers or changed_hotkeys or not ini_path.exists():
        _write_ini_atomic(ini_path, lines)
    bios_dir_for_config.mkdir(parents=True, exist_ok=True)
    if verbose:
        writer(
            f"pcsx2\tconfigured\t{ini_path}\tbios={bios_dir_for_config}\t"
            f"controllers={config.linux.pcsx2_controller_autoconfig}\tmenu_combo={_PCSX2_MENU_COMBO_LABEL}"
        )
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
    use_xinput_devices = sys.platform.startswith("win")
    if use_xinput_devices:
        device0 = "XInput/0/Gamepad"
        device1 = "XInput/1/Gamepad"
    else:
        device0, device1 = _dolphin_linux_device_tokens()
    if dry_run:
        if verbose:
            for ini_path in ini_paths:
                writer(
                    f"dolphin\tdry-run\tconfigure\t{ini_path}\tfullscreen=true\tcontrollers=2\twii=2\t"
                    f"device0={device0}\tdevice1={device1}"
                )
        return runtime_user_dir / "Config" / "Dolphin.ini"

    hotkey_expr = _dolphin_hotkey_expression()
    for ini_path in ini_paths:
        gcpad_ini = ini_path.with_name("GCPadNew.ini")
        wiimote_ini = ini_path.with_name("WiimoteNew.ini")
        hotkeys_ini = ini_path.with_name("Hotkeys.ini")

        lines = _read_ini_lines(ini_path)
        lines, changed_fullscreen = _upsert_ini_key(lines, "Display", "Fullscreen", "True")
        lines, changed_confirm_stop = _upsert_ini_key(lines, "Interface", "ConfirmStop", "False")
        lines, changed_background_input = _upsert_ini_key(lines, "Interface", "BackgroundInput", "True")
        lines, changed_pad0 = _upsert_ini_key(lines, "Core", "SIDevice0", "6")
        lines, changed_pad1 = _upsert_ini_key(lines, "Core", "SIDevice1", "6")
        lines, changed_wii0 = _upsert_ini_key(lines, "Controls", "WiimoteSource0", "1")
        lines, changed_wii1 = _upsert_ini_key(lines, "Controls", "WiimoteSource1", "1")
        if (
            changed_fullscreen
            or changed_confirm_stop
            or changed_background_input
            or changed_pad0
            or changed_pad1
            or changed_wii0
            or changed_wii1
            or not ini_path.exists()
        ):
            _write_ini_atomic(ini_path, lines)

        gcpad_lines = _read_ini_lines(gcpad_ini)
        existing_gc_device = _read_ini_key(gcpad_lines, "GCPad1", "Device")
        existing_gc_device2 = _read_ini_key(gcpad_lines, "GCPad2", "Device")
        existing_gc_a = _read_ini_key(gcpad_lines, "GCPad1", "Buttons/A")
        existing_gc_a2 = _read_ini_key(gcpad_lines, "GCPad2", "Buttons/A")
        managed_legacy_linux_gc = (
            (existing_gc_device in {"SDL/0/Gamepad", "SDL/1/Gamepad"})
            or (existing_gc_device2 in {"SDL/0/Gamepad", "SDL/1/Gamepad"})
            or (existing_gc_device in {"All Devices"})
            or (existing_gc_device2 in {"All Devices"})
            or (existing_gc_device in {"XInput/0/Gamepad", "XInput/1/Gamepad"})
            or (existing_gc_device2 in {"XInput/0/Gamepad", "XInput/1/Gamepad"})
        )
        migrate_evdev_gc_bindings = (
            (bool(existing_gc_device) and existing_gc_device.startswith("evdev/") and existing_gc_a == "`Button A`")
            or (bool(existing_gc_device2) and existing_gc_device2.startswith("evdev/") and existing_gc_a2 == "`Button A`")
        )
        if (
            not gcpad_ini.exists()
            or not existing_gc_device
            or (not use_xinput_devices and managed_legacy_linux_gc)
            or (not use_xinput_devices and migrate_evdev_gc_bindings)
        ):
            gcpad_changed = False
            for pad_number in (1, 2):
                section = f"GCPad{pad_number}"
                device = device0 if pad_number == 1 else device1
                gcpad_lines, changed_device = _upsert_ini_key(gcpad_lines, section, "Device", device)
                gcpad_changed |= changed_device
                for key, value in _DOLPHIN_GCPAD_BINDINGS:
                    gcpad_lines, changed_binding = _upsert_ini_key(gcpad_lines, section, key, value)
                    gcpad_changed |= changed_binding
            if gcpad_changed or not gcpad_ini.exists():
                _write_ini_atomic(gcpad_ini, gcpad_lines)

        wiimote_lines = _read_ini_lines(wiimote_ini)
        existing_wii_device = _read_ini_key(wiimote_lines, "Wiimote1", "Device")
        existing_wii_device2 = _read_ini_key(wiimote_lines, "Wiimote2", "Device")
        existing_wii_a = _read_ini_key(wiimote_lines, "Wiimote1", "Buttons/A")
        existing_wii_a2 = _read_ini_key(wiimote_lines, "Wiimote2", "Buttons/A")
        managed_legacy_linux_wii = (
            (existing_wii_device in {"SDL/0/Gamepad", "SDL/1/Gamepad"})
            or (existing_wii_device2 in {"SDL/0/Gamepad", "SDL/1/Gamepad"})
            or (existing_wii_device in {"All Devices"})
            or (existing_wii_device2 in {"All Devices"})
            or (existing_wii_device in {"XInput/0/Gamepad", "XInput/1/Gamepad"})
            or (existing_wii_device2 in {"XInput/0/Gamepad", "XInput/1/Gamepad"})
        )
        migrate_evdev_wii_bindings = (
            (bool(existing_wii_device) and existing_wii_device.startswith("evdev/") and existing_wii_a == "`Button A`")
            or (bool(existing_wii_device2) and existing_wii_device2.startswith("evdev/") and existing_wii_a2 == "`Button A`")
        )
        if (
            not wiimote_ini.exists()
            or not existing_wii_device
            or (not use_xinput_devices and managed_legacy_linux_wii)
            or (not use_xinput_devices and migrate_evdev_wii_bindings)
        ):
            wiimote_changed = False
            for wiimote_number in (1, 2):
                section = f"Wiimote{wiimote_number}"
                device = device0 if wiimote_number == 1 else device1
                wiimote_lines, changed_device = _upsert_ini_key(wiimote_lines, section, "Device", device)
                wiimote_changed |= changed_device
                wiimote_lines, changed_source = _upsert_ini_key(wiimote_lines, section, "Source", "1")
                wiimote_changed |= changed_source
                wiimote_lines, changed_extension = _upsert_ini_key(wiimote_lines, section, "Extension", "Nunchuk")
                wiimote_changed |= changed_extension
                for key, value in _DOLPHIN_WIIMOTE_BINDINGS:
                    wiimote_lines, changed_binding = _upsert_ini_key(wiimote_lines, section, key, value)
                    wiimote_changed |= changed_binding
            if wiimote_changed or not wiimote_ini.exists():
                _write_ini_atomic(wiimote_ini, wiimote_lines)

        hotkeys_lines = _read_ini_lines(hotkeys_ini)
        hotkeys_changed = False
        hotkeys_lines, changed_device_1 = _upsert_ini_key(hotkeys_lines, "Hotkeys1", "Device", device0)
        hotkeys_changed |= changed_device_1
        hotkeys_lines, changed_keys_stop_1 = _upsert_ini_key(hotkeys_lines, "Hotkeys1", "Keys/Stop", hotkey_expr)
        hotkeys_changed |= changed_keys_stop_1
        hotkeys_lines, changed_keys_exit_1 = _upsert_ini_key(hotkeys_lines, "Hotkeys1", "Keys/Exit", hotkey_expr)
        hotkeys_changed |= changed_keys_exit_1
        hotkeys_lines, changed_device_2 = _upsert_ini_key(hotkeys_lines, "Hotkeys2", "Device", device1)
        hotkeys_changed |= changed_device_2
        hotkeys_lines, changed_keys_stop_2 = _upsert_ini_key(hotkeys_lines, "Hotkeys2", "Keys/Stop", hotkey_expr)
        hotkeys_changed |= changed_keys_stop_2
        hotkeys_lines, changed_keys_exit_2 = _upsert_ini_key(hotkeys_lines, "Hotkeys2", "Keys/Exit", hotkey_expr)
        hotkeys_changed |= changed_keys_exit_2
        hotkeys_lines, changed_general_device = _upsert_ini_key(hotkeys_lines, "Hotkeys", "Device", device0)
        hotkeys_changed |= changed_general_device
        hotkeys_lines, changed_general_stop = _upsert_ini_key(hotkeys_lines, "Hotkeys", "General/Stop", _DOLPHIN_GENERAL_STOP_MACRO)
        hotkeys_changed |= changed_general_stop
        hotkeys_lines, removed_general_exit = _remove_ini_key(hotkeys_lines, "Hotkeys", "General/Exit")
        hotkeys_changed |= removed_general_exit
        if hotkeys_changed or not hotkeys_ini.exists():
            _write_ini_atomic(hotkeys_ini, hotkeys_lines)

        if verbose:
            writer(
                "dolphin\tconfigured\t"
                f"{ini_path}\tfullscreen=true\tcontrollers=2\twii=2\tdevice0={device0}\tdevice1={device1}\t"
                f"gcpad={gcpad_ini}\twiimote={wiimote_ini}\thotkeys={hotkeys_ini}"
            )
    return runtime_user_dir / "Config" / "Dolphin.ini"


def _configure_azahar_runtime(
    config: GamehubConfig,
    dry_run: bool,
    verbose: bool,
    writer: Callable[[str], None] = print,
) -> Path:
    ini_path = _default_azahar_qt_config_path(config=config)
    details_parts = ["fullscreen=true", "confirm_exit_dialog=false"]
    if sys.platform.startswith("linux"):
        details_parts.append("controllers=linux_sdl_autoconfig")
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
    changed_controls = False
    if sys.platform.startswith("linux"):
        lines, changed_controls, controls_details = _bootstrap_azahar_controllers(lines)
        details = f"{details}\t{controls_details}"

    if (
        changed_fullscreen
        or changed_fullscreen_default
        or changed_confirm_close
        or changed_confirm_close_default
        or changed_controls
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
