from __future__ import annotations

import os
import sys
from pathlib import Path

from ..common.config import GamehubConfig
from ..common.config_edit import parse_qsettings_pairs, read_qsettings_key, upsert_qsettings_key
from ..common.platform_paths import AZAHAR_FLATPAK_APP_ID
from ..firmware.pcsx2_ini import read_ini_lines, write_ini_atomic
from .detection import is_steam_deck_linux
from .profiles import PROFILE_KBM, load_profile_file
from .sdl_guid import (
    _azahar_detect_sdl_identity,
    _azahar_normalize_sdl_port,
    _discover_host_sdl_guid,
    _inject_azahar_sdl_identity,
    _probe_azahar_flatpak_guid,
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


def _default_azahar_qt_config_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        return Path(appdata) / "Azahar" / "config" / "qt-config.ini"
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


_DECK_TOUCHPAD_MOUSE_FALLBACKS: dict[str, str] = {
    r"profiles\1\touch_device": '"engine:emu_window"',
    r"profiles\1\use_touch_from_button": "false",
    "hideInactiveMouse": "false",
}


def _apply_azahar_deck_touchpad_mouse_fallback(lines: list[str]) -> tuple[list[str], bool]:
    if not sys.platform.startswith("linux") or not is_steam_deck_linux():
        return lines, False
    changed = False
    updated = lines
    for key, value in _DECK_TOUCHPAD_MOUSE_FALLBACKS.items():
        existing = read_qsettings_key(updated, key)
        if existing is not None:
            continue
        updated, key_changed = upsert_qsettings_key(updated, key, value)
        changed |= key_changed
    return updated, changed


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
        is_flatpak_target = sys.platform.startswith("linux") and _is_azahar_flatpak_config_path(target_path)
        if controller_mode:
            existing_guid, detected_port = _azahar_detect_sdl_identity(lines)
            normalized_port = _azahar_normalize_sdl_port(detected_port)
            runtime_guid: str | None = None
            host_guid: str | None = None
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
                selected_guid = runtime_guid or host_guid or existing_guid
            else:
                # Host SDL GUIDs are not reliably interchangeable with Flatpak runtime GUIDs.
                selected_guid = runtime_guid or existing_guid
        changed = False
        for key, value in pairs.items():
            existing = read_qsettings_key(lines, key)
            desired = value
            managed_button_key = _is_managed_azahar_button_key(key)
            if controller_mode and existing is not None and not managed_button_key:
                continue
            if controller_mode and key.startswith("profiles\\1\\"):
                desired = _inject_azahar_sdl_identity(
                    value,
                    guid=selected_guid,
                    port=detected_port,
                    strip_guid=False,
                )
                if existing is not None and _is_pointer_related_azahar_key(key):
                    continue
                if existing is not None and (
                    "engine:sdl" in existing.casefold() or "engine$0sdl" in existing.casefold()
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
        if controller_mode:
            lines, fallback_changed = _apply_azahar_deck_touchpad_mouse_fallback(lines)
            changed |= fallback_changed
        if changed or not target_path.exists():
            write_ini_atomic(target_path, lines)
        touched.append(target_path)
    return touched
