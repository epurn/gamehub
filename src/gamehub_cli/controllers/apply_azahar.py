from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from ..common.config import GamehubConfig
from ..common.config_edit import parse_qsettings_pairs, read_qsettings_key, upsert_qsettings_key
from ..common.platform_paths import AZAHAR_FLATPAK_APP_ID, macos_azahar_qt_config_candidates
from ..firmware.pcsx2_ini import read_ini_lines
from .apply_ini import write_controller_config_lines_atomic
from .profiles import PROFILE_KBM, load_profile_file
from .sdl_guid import (
    _azahar_detect_sdl_identity,
    _azahar_normalize_sdl_port,
    _discover_host_sdl_guid,
    _inject_azahar_sdl_identity,
    _lookup_macos_embedded_sdl_mapping_for_port,
    _probe_azahar_flatpak_guid,
    _SDLControllerMapping,
)

_AZAHAR_QT_CONFIG_FILENAME = "qt-config.ini"
_AZAHAR_MANAGED_BUTTON_KEYS = {
    "button_a",
    "button_b",
    "button_x",
    "button_y",
    "button_select",
    "button_start",
    "button_l",
    "button_r",
    "button_zl",
    "button_zr",
    "button_home",
    "button_up",
    "button_down",
    "button_left",
    "button_right",
    "circle_pad",
    "c_stick",
}
_AZAHAR_POINTER_KEY_MARKERS = ("touch", "mouse", "pointer")
_AZAHAR_SDL_BUTTON_TOKEN_RE = re.compile(r"^b(?P<button>\d+)$")
_AZAHAR_SDL_AXIS_TOKEN_RE = re.compile(r"^a(?P<axis>\d+)$")
_AZAHAR_SDL_HAT_TOKEN_RE = re.compile(r"^h(?P<hat>\d+)\.(?P<direction>\d+)$")
_AZAHAR_SDL_HAT_DIRECTIONS = {
    "1": "up",
    "2": "right",
    "4": "down",
    "8": "left",
}
_AZAHAR_MACOS_SDL_BUTTON_FIELDS = {
    "button_a": "b",
    "button_b": "a",
    "button_x": "y",
    "button_y": "x",
    "button_select": "back",
    "button_start": "start",
    "button_l": "leftshoulder",
    "button_r": "rightshoulder",
    "button_zl": "lefttrigger",
    "button_zr": "righttrigger",
    "button_home": "guide",
    "button_up": "dpup",
    "button_down": "dpdown",
    "button_left": "dpleft",
    "button_right": "dpright",
}
_AZAHAR_MACOS_SDL_ANALOG_FIELDS = {
    "circle_pad": ("leftx", "lefty"),
    "c_stick": ("rightx", "righty"),
}


def _default_azahar_qt_config_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        return Path(appdata) / "Azahar" / "config" / "qt-config.ini"
    if sys.platform == "darwin":
        candidates = macos_azahar_qt_config_candidates()
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]
    home = Path.home()
    flatpak_qt_candidates = (
        home / ".var" / "app" / AZAHAR_FLATPAK_APP_ID / "config" / "azahar-emu" / _AZAHAR_QT_CONFIG_FILENAME,
        home / ".var" / "app" / AZAHAR_FLATPAK_APP_ID / "config" / "azahar" / _AZAHAR_QT_CONFIG_FILENAME,
    )
    if sys.platform.startswith("linux"):
        for candidate in flatpak_qt_candidates:
            if candidate.exists():
                return candidate
        for candidate in flatpak_qt_candidates:
            if candidate.parent.exists():
                return candidate
    return home / ".config" / "azahar-emu" / "qt-config.ini"


def _azahar_target_config_paths() -> list[Path]:
    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        return [Path(appdata) / "Azahar" / "config" / _AZAHAR_QT_CONFIG_FILENAME]
    if sys.platform == "darwin":
        candidates = macos_azahar_qt_config_candidates()
        existing = [candidate for candidate in candidates if candidate.exists()]
        if existing:
            return existing
        return [candidates[0]]

    home = Path.home()
    candidates = [
        home / ".var" / "app" / AZAHAR_FLATPAK_APP_ID / "config" / "azahar-emu" / _AZAHAR_QT_CONFIG_FILENAME,
        home / ".var" / "app" / AZAHAR_FLATPAK_APP_ID / "config" / "azahar" / _AZAHAR_QT_CONFIG_FILENAME,
        home / ".config" / "azahar-emu" / _AZAHAR_QT_CONFIG_FILENAME,
    ]
    existing = [candidate for candidate in candidates if candidate.exists()]
    if existing:
        return existing
    return [_default_azahar_qt_config_path()]


def azahar_target_config_paths() -> list[Path]:
    return _azahar_target_config_paths()


def _is_azahar_flatpak_config_path(path: Path) -> bool:
    flatpak_root = Path.home() / ".var" / "app" / AZAHAR_FLATPAK_APP_ID
    return flatpak_root in path.parents


def _azahar_profile_key_name(key: str) -> str | None:
    prefix = "profiles\\1\\"
    if not key.startswith(prefix):
        return None
    suffix = key[len(prefix) :]
    if suffix.endswith("\\default"):
        suffix = suffix[: -len("\\default")]
    return suffix


def _is_azahar_profile_default_key(key: str) -> bool:
    return key.startswith("profiles\\1\\") and key.endswith("\\default")


def _is_managed_azahar_button_key(key: str) -> bool:
    profile_key = _azahar_profile_key_name(key)
    if profile_key is None:
        return False
    return profile_key in _AZAHAR_MANAGED_BUTTON_KEYS


def _is_pointer_related_azahar_key(key: str) -> bool:
    profile_key = _azahar_profile_key_name(key)
    if profile_key is None:
        return False
    lowered = profile_key.casefold()
    return any(marker in lowered for marker in _AZAHAR_POINTER_KEY_MARKERS)


def _azahar_macos_sdl_button_value(control: str, *, port: int) -> str | None:
    normalized = control.strip().casefold()
    button_match = _AZAHAR_SDL_BUTTON_TOKEN_RE.match(normalized)
    if button_match is not None:
        return f'"button:{int(button_match.group("button"))},engine:sdl,port:{port}"'
    axis_match = _AZAHAR_SDL_AXIS_TOKEN_RE.match(normalized)
    if axis_match is not None:
        return f'"axis:{int(axis_match.group("axis"))},direction:+,engine:sdl,port:{port},threshold:0.5"'
    hat_match = _AZAHAR_SDL_HAT_TOKEN_RE.match(normalized)
    if hat_match is not None:
        direction = _AZAHAR_SDL_HAT_DIRECTIONS.get(hat_match.group("direction"))
        if direction is None:
            return None
        return f'"hat:{int(hat_match.group("hat"))},direction:{direction},engine:sdl,port:{port}"'
    return None


def _azahar_macos_sdl_analog_value(*, axis_x: str, axis_y: str, port: int) -> str | None:
    axis_x_match = _AZAHAR_SDL_AXIS_TOKEN_RE.match(axis_x.strip().casefold())
    axis_y_match = _AZAHAR_SDL_AXIS_TOKEN_RE.match(axis_y.strip().casefold())
    if axis_x_match is None or axis_y_match is None:
        return None
    axis_x_index = int(axis_x_match.group("axis"))
    axis_y_index = int(axis_y_match.group("axis"))
    return (
        f'"down:axis$0{axis_y_index}$1direction$0+$1engine$0sdl$1port$0{port}$1threshold$00.5,'
        "engine:analog_from_button,"
        f"left:axis$0{axis_x_index}$1direction$0-$1engine$0sdl$1port$0{port}$1threshold$00-0.5,"
        "modifier:code$068$1engine$0keyboard,modifier_scale:0.500000,"
        f"right:axis$0{axis_x_index}$1direction$0+$1engine$0sdl$1port$0{port}$1threshold$00.5,"
        f'up:axis$0{axis_y_index}$1direction$0-$1engine$0sdl$1port$0{port}$1threshold$00-0.5"'
    )


def _azahar_macos_binding_overrides(
    mapping: _SDLControllerMapping | None,
    *,
    port: int,
) -> dict[str, str]:
    if mapping is None:
        return {}
    overrides: dict[str, str] = {}
    for profile_key, field_name in _AZAHAR_MACOS_SDL_BUTTON_FIELDS.items():
        control = mapping.fields.get(field_name)
        if control is None:
            continue
        value = _azahar_macos_sdl_button_value(control, port=port)
        if value is not None:
            overrides[profile_key] = value
    for profile_key, (field_x, field_y) in _AZAHAR_MACOS_SDL_ANALOG_FIELDS.items():
        axis_x = mapping.fields.get(field_x)
        axis_y = mapping.fields.get(field_y)
        if axis_x is None or axis_y is None:
            continue
        value = _azahar_macos_sdl_analog_value(axis_x=axis_x, axis_y=axis_y, port=port)
        if value is not None:
            overrides[profile_key] = value
    return overrides


def apply_azahar_profile(config: GamehubConfig, profile_name: str) -> list[Path]:
    profile_lines = load_profile_file(
        config,
        emulator_name="azahar",
        profile_name=profile_name,
        filename="qt-config.ini",
    )
    pairs = parse_qsettings_pairs(profile_lines)
    touched: list[Path] = []
    controller_mode = profile_name != PROFILE_KBM
    runtime_guid_cache: dict[int, str | None] = {}
    host_guid_cache: dict[int, str | None] = {}
    for target_path in _azahar_target_config_paths():
        lines = read_ini_lines(target_path)
        existing_guid: str | None = None
        detected_port = 0
        selected_guid: str | None = None
        macos_binding_overrides: dict[str, str] = {}
        is_flatpak_target = sys.platform.startswith("linux") and _is_azahar_flatpak_config_path(target_path)
        if controller_mode:
            existing_guid, detected_port = _azahar_detect_sdl_identity(lines)
            normalized_port = _azahar_normalize_sdl_port(detected_port)
            runtime_guid: str | None = None
            host_guid: str | None = None
            macos_mapping: _SDLControllerMapping | None = None
            if is_flatpak_target:
                if normalized_port in runtime_guid_cache:
                    runtime_guid = runtime_guid_cache[normalized_port]
                else:
                    runtime_guid = _probe_azahar_flatpak_guid(port=normalized_port)
                    runtime_guid_cache[normalized_port] = runtime_guid
            if not is_flatpak_target:
                if normalized_port in host_guid_cache:
                    host_guid = host_guid_cache[normalized_port]
                else:
                    host_guid = _discover_host_sdl_guid(port=normalized_port)
                    host_guid_cache[normalized_port] = host_guid
                if sys.platform == "darwin":
                    # Preserve Azahar-written runtime GUIDs when present. On macOS these can differ
                    # from the host SDL / embedded mapping GUIDs even when the button layout matches.
                    selected_guid = existing_guid or runtime_guid or host_guid
                else:
                    selected_guid = runtime_guid or host_guid or existing_guid
            else:
                # Host SDL GUIDs are not reliably interchangeable with Flatpak runtime GUIDs.
                selected_guid = runtime_guid or existing_guid
            if sys.platform == "darwin":
                macos_mapping = _lookup_macos_embedded_sdl_mapping_for_port(port=normalized_port)
                if selected_guid is None and macos_mapping is not None:
                    selected_guid = macos_mapping.guid
                macos_binding_overrides = _azahar_macos_binding_overrides(macos_mapping, port=normalized_port)
        changed = False
        for key, value in pairs.items():
            existing = read_qsettings_key(lines, key)
            desired = value
            managed_button_key = _is_managed_azahar_button_key(key)
            is_default_key = _is_azahar_profile_default_key(key)
            if controller_mode and existing is not None and not managed_button_key:
                continue
            if controller_mode and key.startswith("profiles\\1\\"):
                profile_key = _azahar_profile_key_name(key)
                if profile_key is not None and not is_default_key:
                    desired = macos_binding_overrides.get(profile_key, value)
                    desired = _inject_azahar_sdl_identity(
                        desired,
                        guid=selected_guid,
                        port=detected_port,
                        strip_guid=False,
                    )
                if existing is not None and _is_pointer_related_azahar_key(key):
                    continue
                if (
                    not is_default_key
                    and existing is not None
                    and ("engine:sdl" in existing.casefold() or "engine$0sdl" in existing.casefold())
                    and (profile_key is None or profile_key not in macos_binding_overrides)
                ):
                    # Preserve existing SDL mappings, but normalize identity tokens.
                    upgraded = _inject_azahar_sdl_identity(
                        existing,
                        guid=selected_guid,
                        port=detected_port,
                        strip_guid=False,
                    )
                    if upgraded != existing:
                        lines, key_changed = upsert_qsettings_key(lines, key, upgraded)
                        changed |= key_changed
                    continue
            if existing == desired:
                continue
            lines, key_changed = upsert_qsettings_key(lines, key, desired)
            changed |= key_changed
        if changed or not target_path.exists():
            write_controller_config_lines_atomic(
                target_path,
                lines,
                keep_limit=config.backups.keep_limit,
            )
        touched.append(target_path)
    return touched
