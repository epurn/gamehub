from __future__ import annotations

from pathlib import Path
import ctypes
import ctypes.util
import os
import re
import sys
from typing import Callable

from .config import GamehubConfig
from .controller_profiles import (
    PROFILE_KBM,
    VALID_PROFILES,
    load_profile_file,
    profile_name_for_controller_count,
)
from .controller_detection import detect_xbox_controllers
from .firmware_targets import default_pcsx2_ini_path, resolve_dolphin_config_dirs, resolve_dolphin_runtime_user_dir
from .platform_paths import AZAHAR_FLATPAK_APP_ID
from .pcsx2_ini import read_ini_lines, upsert_ini_key, write_ini_atomic

_MANAGED_PCSX2_SECTIONS = ("InputSources", "Pad1", "Pad2", "Hotkeys")
_AZAHAR_QT_CONFIG_FILENAME = "qt-config.ini"
_AZAHAR_GUID_RE = re.compile(r"guid(?::|\$0)(?P<guid>[0-9a-fA-F]+)")
_AZAHAR_PORT_RE = re.compile(r"port(?::|\$0)(?P<port>\d+)")
_AZAHAR_ANALOG_GUID_RE = re.compile(r"\$1guid\$0[0-9a-fA-F]+", flags=re.IGNORECASE)
_AZAHAR_ANALOG_PORT_RE = re.compile(r"\$1port\$0\d+")
_AZAHAR_ANALOG_ENGINE_RE = re.compile(r"engine\$0sdl", flags=re.IGNORECASE)


class _SDLJoystickGUID(ctypes.Structure):
    _fields_ = [("data", ctypes.c_uint8 * 16)]


def _parse_ini_sections(lines: list[str]) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    current_section: str | None = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = stripped[1:-1].strip()
            sections.setdefault(current_section, {})
            continue
        if "=" not in line or current_section is None:
            continue
        key, value = line.split("=", 1)
        sections.setdefault(current_section, {})[key.strip()] = value.strip()
    return sections


def _apply_managed_ini_sections(
    *,
    target_path: Path,
    sections: dict[str, dict[str, str]],
) -> bool:
    lines = read_ini_lines(target_path)
    changed = False
    for section_name, values in sections.items():
        for key, value in values.items():
            lines, key_changed = upsert_ini_key(lines, section_name, key, value)
            changed |= key_changed
    if changed or not target_path.exists():
        write_ini_atomic(target_path, lines)
    return changed


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


def _parse_qsettings_pairs(lines: list[str]) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        pairs[key.strip()] = value.strip()
    return pairs


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


def _discover_linux_sdl_guid(*, port: int) -> str | None:
    if not sys.platform.startswith("linux"):
        return None

    library_candidates: list[str] = []
    detected = ctypes.util.find_library("SDL2")
    if detected:
        library_candidates.append(detected)
    library_candidates.extend(["libSDL2-2.0.so.0", "libSDL2.so"])

    sdl = None
    for candidate in library_candidates:
        try:
            sdl = ctypes.CDLL(candidate)
            break
        except OSError:
            continue
    if sdl is None:
        return None

    try:
        sdl.SDL_Init.argtypes = [ctypes.c_uint32]
        sdl.SDL_Init.restype = ctypes.c_int
        sdl.SDL_Quit.argtypes = []
        sdl.SDL_Quit.restype = None
        sdl.SDL_NumJoysticks.argtypes = []
        sdl.SDL_NumJoysticks.restype = ctypes.c_int
        sdl.SDL_JoystickGetDeviceGUID.argtypes = [ctypes.c_int]
        sdl.SDL_JoystickGetDeviceGUID.restype = _SDLJoystickGUID
        sdl.SDL_JoystickGetGUIDString.argtypes = [_SDLJoystickGUID, ctypes.c_char_p, ctypes.c_int]
        sdl.SDL_JoystickGetGUIDString.restype = None
    except AttributeError:
        return None

    # SDL_INIT_JOYSTICK
    if sdl.SDL_Init(0x00000200) != 0:
        return None

    try:
        count = int(sdl.SDL_NumJoysticks())
        if count <= 0 or port < 0 or port >= count:
            return None
        guid_value = sdl.SDL_JoystickGetDeviceGUID(port)
        text = ctypes.create_string_buffer(33)
        sdl.SDL_JoystickGetGUIDString(guid_value, text, len(text))
        guid = text.value.decode("ascii", errors="ignore").strip().lower()
        if len(guid) != 32 or set(guid) == {"0"}:
            return None
        return guid
    finally:
        sdl.SDL_Quit()


def _azahar_normalize_sdl_port(value: int) -> int:
    if value < 0:
        return 0
    if value > 15:
        return 15
    return value


def _inject_azahar_sdl_identity(value: str, *, guid: str | None, port: int) -> str:
    normalized_port = _azahar_normalize_sdl_port(port)
    raw = value.strip()
    lowered = raw.casefold()

    if "engine$0sdl" in lowered:
        updated = _AZAHAR_ANALOG_PORT_RE.sub(f"$1port$0{normalized_port}", raw)
        if guid:
            if _AZAHAR_ANALOG_GUID_RE.search(updated):
                updated = _AZAHAR_ANALOG_GUID_RE.sub(f"$1guid$0{guid}", updated)
            else:
                updated = _AZAHAR_ANALOG_ENGINE_RE.sub(f"engine$0sdl$1guid$0{guid}", updated, count=1)
        return updated

    if "engine:sdl" not in lowered:
        return raw

    quote = '"' if len(raw) >= 2 and raw[0] == raw[-1] == '"' else ""
    body = raw[1:-1] if quote else raw
    parts = [part.strip() for part in body.split(",") if part.strip()]
    updated_parts: list[str] = []
    has_port = False
    has_guid = False
    inserted_guid_after_engine = False
    for part in parts:
        token = part.casefold()
        if token.startswith("port:"):
            updated_parts.append(f"port:{normalized_port}")
            has_port = True
            continue
        if token.startswith("guid:"):
            if guid:
                updated_parts.append(f"guid:{guid}")
                has_guid = True
            continue
        updated_parts.append(part)
        if token == "engine:sdl" and guid:
            updated_parts.append(f"guid:{guid}")
            has_guid = True
            inserted_guid_after_engine = True
    if guid and not has_guid and not inserted_guid_after_engine:
        updated_parts.append(f"guid:{guid}")
    if not has_port:
        updated_parts.append(f"port:{normalized_port}")
    payload = ",".join(updated_parts)
    return f'"{payload}"' if quote else payload


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


def _apply_pcsx2_profile(config: GamehubConfig, profile_name: str) -> list[Path]:
    profile_lines = load_profile_file(
        config,
        emulator_name="pcsx2",
        profile_name=profile_name,
        filename="PCSX2.ini",
    )
    sections = _parse_ini_sections(profile_lines)
    managed_sections = {
        section_name: dict(sections.get(section_name, {}))
        for section_name in _MANAGED_PCSX2_SECTIONS
        if section_name in sections
    }
    target = default_pcsx2_ini_path(config=config)
    _apply_managed_ini_sections(target_path=target, sections=managed_sections)
    return [target]


def _dolphin_target_config_dirs(config: GamehubConfig) -> list[Path]:
    paths: list[Path] = []
    runtime = resolve_dolphin_runtime_user_dir(config=config) / "Config"
    paths.append(runtime)
    for candidate in resolve_dolphin_config_dirs(config=config):
        config_dir = candidate / "Config"
        if config_dir not in paths:
            paths.append(config_dir)
    return paths


def _dolphin_linux_device_pair() -> tuple[str, str]:
    controllers = detect_xbox_controllers(max_devices=2)
    if len(controllers) >= 2:
        return f"evdev/0/{controllers[0].name}", f"evdev/1/{controllers[1].name}"
    if len(controllers) == 1:
        return f"evdev/0/{controllers[0].name}", "SDL/1/Gamepad"
    return "SDL/0/Gamepad", "SDL/1/Gamepad"


def _override_dolphin_device_sections(
    sections: dict[str, dict[str, str]],
    *,
    profile_name: str,
) -> dict[str, dict[str, str]]:
    if not sys.platform.startswith("linux"):
        return sections
    if profile_name == PROFILE_KBM:
        pad_device0, pad_device1 = "All Devices", "All Devices"
    else:
        pad_device0, pad_device1 = _dolphin_linux_device_pair()
    # Keep gameplay device tokens precise, but let hotkeys resolve from any backend.
    hotkey_device0, hotkey_device1 = "All Devices", "All Devices"
    updated: dict[str, dict[str, str]] = {section: dict(values) for section, values in sections.items()}
    for section_name, device in (
        ("GCPad1", pad_device0),
        ("GCPad2", pad_device1),
        ("Wiimote1", pad_device0),
        ("Wiimote2", pad_device1),
        ("Hotkeys1", hotkey_device0),
        ("Hotkeys2", hotkey_device1),
        ("Hotkeys", hotkey_device0),
    ):
        if section_name not in updated:
            continue
        updated[section_name]["Device"] = device
    return updated


def _dolphin_hotkey_expression_for_profile(profile_name: str) -> str:
    if profile_name == PROFILE_KBM:
        return "`Escape`"
    return "(`Back` & `Start`) | (`BACK` & `START`) | (`SELECT` & `START`) | (`Button 6` & `Button 7`)"


def _override_dolphin_hotkey_sections(
    sections: dict[str, dict[str, str]],
    *,
    profile_name: str,
) -> dict[str, dict[str, str]]:
    updated: dict[str, dict[str, str]] = {section: dict(values) for section, values in sections.items()}
    hotkey_expr = _dolphin_hotkey_expression_for_profile(profile_name)
    for section_name in ("Hotkeys1", "Hotkeys2"):
        if section_name not in updated:
            continue
        updated[section_name]["Keys/Stop"] = hotkey_expr
        updated[section_name]["Keys/Exit"] = hotkey_expr
    if "Hotkeys" in updated:
        updated["Hotkeys"]["General/Stop"] = hotkey_expr
        updated["Hotkeys"]["General/Exit"] = hotkey_expr
    return updated


def _apply_dolphin_profile(config: GamehubConfig, profile_name: str) -> list[Path]:
    touched: list[Path] = []
    for target_dir in _dolphin_target_config_dirs(config):
        for filename in ("GCPadNew.ini", "WiimoteNew.ini", "Hotkeys.ini"):
            profile_lines = load_profile_file(
                config,
                emulator_name="dolphin",
                profile_name=profile_name,
                filename=filename,
            )
            sections = _parse_ini_sections(profile_lines)
            sections = _override_dolphin_device_sections(sections, profile_name=profile_name)
            sections = _override_dolphin_hotkey_sections(sections, profile_name=profile_name)
            target_path = target_dir / filename
            _apply_managed_ini_sections(target_path=target_path, sections=sections)
            touched.append(target_path)
    return touched


def _apply_azahar_profile(config: GamehubConfig, profile_name: str) -> list[Path]:
    profile_lines = load_profile_file(
        config,
        emulator_name="azahar",
        profile_name=profile_name,
        filename="qt-config.ini",
    )
    pairs = _parse_qsettings_pairs(profile_lines)
    touched: list[Path] = []
    linux_controller_mode = sys.platform.startswith("linux") and profile_name != PROFILE_KBM
    for target_path in _azahar_target_config_paths():
        lines = read_ini_lines(target_path)
        detected_guid: str | None = None
        detected_port = 0
        if linux_controller_mode:
            detected_guid, detected_port = _azahar_detect_sdl_identity(lines)
            if detected_guid is None:
                detected_guid = _discover_linux_sdl_guid(port=detected_port)
        changed = False
        for key, value in pairs.items():
            existing = _read_qsettings_key(lines, key)
            desired = value
            if linux_controller_mode and key.startswith("profiles\\1\\"):
                desired = _inject_azahar_sdl_identity(value, guid=detected_guid, port=detected_port)
                if existing is not None and ("engine:sdl" in existing.casefold() or "engine$0sdl" in existing.casefold()):
                    # Preserve existing SDL mappings, but upgrade legacy entries lacking GUID when
                    # we have a discovered controller identity.
                    if (
                        detected_guid is not None
                        and "guid:" not in existing.casefold()
                        and "guid$0" not in existing.casefold()
                    ):
                        upgraded = _inject_azahar_sdl_identity(existing, guid=detected_guid, port=detected_port)
                        if upgraded != existing:
                            lines, key_changed = _upsert_qsettings_key(lines, key, upgraded)
                            changed |= key_changed
                    continue
            if existing == desired:
                continue
            lines, key_changed = _upsert_qsettings_key(lines, key, desired)
            changed |= key_changed
        if changed or not target_path.exists():
            write_ini_atomic(target_path, lines)
        touched.append(target_path)
    return touched


def apply_controller_profile(
    config: GamehubConfig,
    *,
    emulator_name: str,
    controller_count: int,
    verbose: bool = False,
    writer: Callable[[str], None] = print,
) -> str:
    profile_name = profile_name_for_controller_count(controller_count)
    return apply_named_controller_profile(
        config,
        emulator_name=emulator_name,
        profile_name=profile_name,
        verbose=verbose,
        writer=writer,
    )


def apply_named_controller_profile(
    config: GamehubConfig,
    *,
    emulator_name: str,
    profile_name: str,
    verbose: bool = False,
    writer: Callable[[str], None] = print,
) -> str:
    normalized_name = emulator_name.casefold()
    selected_profile = profile_name if profile_name in VALID_PROFILES else PROFILE_KBM

    if "pcsx2" in normalized_name:
        targets = _apply_pcsx2_profile(config, selected_profile)
    elif "dolphin" in normalized_name:
        targets = _apply_dolphin_profile(config, selected_profile)
    elif "azahar" in normalized_name:
        targets = _apply_azahar_profile(config, selected_profile)
    else:
        raise ValueError(f"Unsupported controller profile emulator: {emulator_name}")

    if verbose:
        for target in targets:
            writer(
                f"controller-autoconfig\tapplied\temulator={normalized_name}\tprofile={selected_profile}\ttarget={target}"
            )
    return selected_profile
