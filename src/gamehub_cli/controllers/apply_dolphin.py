from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

from ..common.config import GamehubConfig
from ..common.platform_paths import macos_dolphin_root_candidates
from ..firmware.targets import resolve_dolphin_config_dirs, resolve_dolphin_runtime_user_dir
from .apply_ini import apply_managed_ini_sections, parse_ini_sections
from .detection import XboxController, detect_xbox_controllers, is_steam_deck_linux
from .profiles import PROFILE_KBM, PROFILE_XBOX_1P, PROFILE_XBOX_2P, load_profile_file
from .sdl_guid import _lookup_macos_embedded_sdl_mapping_for_identity

_DOLPHIN_KBM_FALLBACK_DEVICE_MARKERS = ("virtual core pointer", "keyboard mouse")
_DOLPHIN_NON_GAMEPAD_DEVICE_MARKERS = ("motion sensor", "accelerometer", "gyroscope", "gyro", "imu")
_DOLPHIN_GENERIC_SDL_DEVICE_NAMES = {"gamepad", "controller", "joystick"}
_DOLPHIN_STEAM_DECK_POINTER_DEVICE = "XInput2/0/Virtual core pointer"
_DOLPHIN_DEFAULT_EVDEV_FALLBACK = "evdev/0/Microsoft X-Box 360 pad 0"
_DOLPHIN_MACOS_KBM_DEVICE = "Quartz/0/Keyboard & Mouse"
_DOLPHIN_MACOS_HOTKEY_COMBO = "`Back` & `Start`"
_DOLPHIN_MACOS_KEY_TOKEN_MAP = {
    "CTRL": "Left Control",
    "ESCAPE": "Escape",
    "LCONTROL": "Left Control",
    "LSHIFT": "Left Shift",
    "RETURN": "Return",
    "SHIFT": "Left Shift",
    "UP": "Up Arrow",
    "DOWN": "Down Arrow",
    "LEFT": "Left Arrow",
    "RIGHT": "Right Arrow",
}
_DOLPHIN_MACOS_GCPAD_BINDINGS = {
    "Buttons/A": "`Button S`",
    "Buttons/B": "`Button E`",
    "Buttons/X": "`Button W`",
    "Buttons/Y": "`Button N`",
    "Buttons/Z": "`Shoulder R`",
    "Buttons/Start": "Start",
    "Main Stick/Up": "`Left Y+`",
    "Main Stick/Down": "`Left Y-`",
    "Main Stick/Left": "`Left X-`",
    "Main Stick/Right": "`Left X+`",
    "Main Stick/Modifier": "`Thumb L`",
    "C-Stick/Up": "`Right Y+`",
    "C-Stick/Down": "`Right Y-`",
    "C-Stick/Left": "`Right X-`",
    "C-Stick/Right": "`Right X+`",
    "C-Stick/Modifier": "`Thumb R`",
    "Triggers/L": "`Trigger L`",
    "Triggers/R": "`Trigger R`",
    "Triggers/L-Analog": "`Trigger L`",
    "Triggers/R-Analog": "`Trigger R`",
    "D-Pad/Up": "`Pad N`",
    "D-Pad/Down": "`Pad S`",
    "D-Pad/Left": "`Pad W`",
    "D-Pad/Right": "`Pad E`",
}
_DOLPHIN_MACOS_WIIMOTE_BINDINGS = {
    "Buttons/A": "`Button S` | `Shoulder R`",
    "Buttons/B": "`Button E` | `Trigger R`",
    "Buttons/1": "`Button W`",
    "Buttons/2": "`Button N`",
    "Buttons/-": "Back",
    "Buttons/+": "Start",
    "Buttons/Home": "Guide | `Thumb R`",
    "D-Pad/Up": "`Pad N`",
    "D-Pad/Down": "`Pad S`",
    "D-Pad/Left": "`Pad W`",
    "D-Pad/Right": "`Pad E`",
    "IR/Up": "`Right Y+`",
    "IR/Down": "`Right Y-`",
    "IR/Left": "`Right X-`",
    "IR/Right": "`Right X+`",
    "Nunchuk/Stick/Up": "`Left Y+`",
    "Nunchuk/Stick/Down": "`Left Y-`",
    "Nunchuk/Stick/Left": "`Left X-`",
    "Nunchuk/Stick/Right": "`Left X+`",
    "Nunchuk/Buttons/C": "`Shoulder L`",
    "Nunchuk/Buttons/Z": "`Trigger L`",
}


def _dolphin_target_config_dirs(config: GamehubConfig) -> list[Path]:
    paths: list[Path] = []
    runtime = resolve_dolphin_runtime_user_dir(config=config) / "Config"
    paths.append(runtime)
    if sys.platform == "darwin":
        for candidate_root in macos_dolphin_root_candidates():
            config_dir = candidate_root / "Config"
            if (candidate_root.exists() or config_dir.exists()) and config_dir not in paths:
                paths.append(config_dir)
    for candidate in resolve_dolphin_config_dirs(config=config):
        config_dir = candidate / "Config"
        if config_dir not in paths:
            paths.append(config_dir)
    return paths


def dolphin_target_config_dirs(config: GamehubConfig) -> list[Path]:
    return _dolphin_target_config_dirs(config)


def _is_xbox_like_name(name: str) -> bool:
    normalized = name.casefold()
    return any(marker in normalized for marker in ("xbox", "x-box", "xinput", "microsoft x-box"))


def _dolphin_deck_linux_device_pair(profile_name: str) -> tuple[str, str]:
    controllers = detect_xbox_controllers(max_devices=2)
    xbox_like = [controller for controller in controllers if _is_xbox_like_name(controller.name)]

    if xbox_like:
        primary = xbox_like[0]
        pad_device0 = f"evdev/{primary.slot}/{primary.name}"
    else:
        pad_device0 = _DOLPHIN_DEFAULT_EVDEV_FALLBACK

    if profile_name == PROFILE_XBOX_2P and len(xbox_like) >= 2:
        secondary = xbox_like[1]
        pad_device1 = f"evdev/{secondary.slot}/{secondary.name}"
    else:
        pad_device1 = "None"
    return pad_device0, pad_device1


def _dolphin_linux_device_pair(profile_name: str) -> tuple[str, str]:
    controllers = detect_xbox_controllers(max_devices=2)
    if is_steam_deck_linux():
        return _dolphin_deck_linux_device_pair(profile_name)
    if len(controllers) >= 2:
        return f"evdev/0/{controllers[0].name}", f"evdev/1/{controllers[1].name}"
    if len(controllers) == 1:
        if profile_name == PROFILE_XBOX_1P:
            return f"evdev/0/{controllers[0].name}", "None"
        return f"evdev/0/{controllers[0].name}", _DOLPHIN_STEAM_DECK_POINTER_DEVICE
    return "SDL/0/Gamepad", "SDL/1/Gamepad"


def _dolphin_windows_device_pair(profile_name: str) -> tuple[str, str]:
    controllers = detect_xbox_controllers(max_devices=2)
    if profile_name == PROFILE_KBM:
        return "DInput/0/Keyboard Mouse", "None"
    if profile_name == PROFILE_XBOX_2P:
        if len(controllers) >= 2:
            return (
                f"XInput/{controllers[0].slot}/Gamepad",
                f"XInput/{controllers[1].slot}/Gamepad",
            )
        return "XInput/0/Gamepad", "XInput/1/Gamepad"
    if profile_name == PROFILE_XBOX_1P:
        if len(controllers) >= 1:
            return f"XInput/{controllers[0].slot}/Gamepad", "DInput/0/Keyboard Mouse"
        return "XInput/0/Gamepad", "DInput/0/Keyboard Mouse"
    return "DInput/0/Keyboard Mouse", "DInput/0/Keyboard Mouse"


def _macos_sdl_device_name(
    slot: int,
    name: str,
    *,
    guid: str | None,
    vendor_id: int | None = None,
    product_id: int | None = None,
) -> str:
    resolved_name = name
    if guid is None:
        mapping = _lookup_macos_embedded_sdl_mapping_for_identity(
            name=name,
            vendor_id=vendor_id,
            product_id=product_id,
        )
        if mapping is not None and mapping.name.strip():
            resolved_name = mapping.name
    normalized_name = resolved_name.strip()
    if not normalized_name or normalized_name.casefold() in _DOLPHIN_GENERIC_SDL_DEVICE_NAMES:
        return f"SDL/{slot}/Gamepad"
    return f"SDL/{slot}/{normalized_name}"


def _dolphin_macos_device_pair(
    profile_name: str,
    *,
    controllers: list[XboxController] | None = None,
) -> tuple[str, str]:
    detected = controllers if controllers is not None else detect_xbox_controllers(max_devices=2)
    if profile_name == PROFILE_XBOX_2P:
        if len(detected) >= 2:
            return (
                _macos_sdl_device_name(
                    detected[0].slot,
                    detected[0].name,
                    guid=detected[0].guid,
                    vendor_id=detected[0].vendor_id,
                    product_id=detected[0].product_id,
                ),
                _macos_sdl_device_name(
                    detected[1].slot,
                    detected[1].name,
                    guid=detected[1].guid,
                    vendor_id=detected[1].vendor_id,
                    product_id=detected[1].product_id,
                ),
            )
        if len(detected) == 1:
            return (
                _macos_sdl_device_name(
                    detected[0].slot,
                    detected[0].name,
                    guid=detected[0].guid,
                    vendor_id=detected[0].vendor_id,
                    product_id=detected[0].product_id,
                ),
                "SDL/1/Gamepad",
            )
        return "SDL/0/Gamepad", "SDL/1/Gamepad"
    if len(detected) >= 1:
        return (
            _macos_sdl_device_name(
                detected[0].slot,
                detected[0].name,
                guid=detected[0].guid,
                vendor_id=detected[0].vendor_id,
                product_id=detected[0].product_id,
            ),
            "None",
        )
    return "SDL/0/Gamepad", "None"


def _is_specific_macos_sdl_device(value: str) -> bool:
    normalized = value.strip()
    if not normalized.startswith("SDL/"):
        return False
    parts = normalized.split("/", 2)
    if len(parts) != 3:
        return False
    device_name = parts[2].strip().casefold()
    if not device_name:
        return False
    if device_name in _DOLPHIN_GENERIC_SDL_DEVICE_NAMES:
        return False
    if any(marker in device_name for marker in _DOLPHIN_NON_GAMEPAD_DEVICE_MARKERS):
        return False
    return True


def _is_generic_macos_sdl_device(value: str) -> bool:
    normalized = value.strip()
    if not normalized.startswith("SDL/"):
        return False
    parts = normalized.split("/", 2)
    if len(parts) != 3:
        return False
    return parts[2].strip().casefold() in _DOLPHIN_GENERIC_SDL_DEVICE_NAMES


def _override_dolphin_device_sections(
    sections: dict[str, dict[str, str]],
    *,
    profile_name: str,
    existing_sections: dict[str, dict[str, str]] | None = None,
    detected_controllers: list[XboxController] | None = None,
) -> tuple[dict[str, dict[str, str]], str, str]:
    selected_device = ""
    pad_device0 = ""
    pad_device1 = ""
    hotkey_device0 = ""
    hotkey_device1 = ""
    if sys.platform.startswith("linux"):
        if profile_name == PROFILE_KBM:
            pad_device0, pad_device1 = "XInput2/0/Virtual core pointer", "None"
            hotkey_device0, hotkey_device1 = "XInput2/0/Virtual core pointer", "XInput2/0/Virtual core pointer"
        else:
            pad_device0, pad_device1 = _dolphin_linux_device_pair(profile_name)
            if profile_name == PROFILE_XBOX_1P:
                pad_device1 = "None"
            hotkey_device0, hotkey_device1 = "All Devices", "All Devices"
    elif sys.platform == "darwin":
        if profile_name == PROFILE_KBM:
            pad_device0, pad_device1 = _DOLPHIN_MACOS_KBM_DEVICE, "None"
            hotkey_device0, hotkey_device1 = _DOLPHIN_MACOS_KBM_DEVICE, _DOLPHIN_MACOS_KBM_DEVICE
        else:
            pad_device0, pad_device1 = _dolphin_macos_device_pair(profile_name, controllers=detected_controllers)
            hotkey_device0, hotkey_device1 = pad_device0, pad_device1
    elif sys.platform.startswith("win"):
        pad_device0, pad_device1 = _dolphin_windows_device_pair(profile_name)
        hotkey_device0, hotkey_device1 = pad_device0, pad_device1
    else:
        return sections, "rebind", selected_device
    selected_device = pad_device0
    updated: dict[str, dict[str, str]] = {section: dict(values) for section, values in sections.items()}
    device_identity_mode = "preserve"

    def _looks_valid_existing_device(value: str) -> bool:
        normalized = value.strip()
        if not normalized:
            return False
        if normalized.casefold() == "none":
            return False
        return normalized.startswith(("evdev/", "SDL/", "SteamDeck/", "XInput2/", "XInput/", "DInput/", "Quartz/"))

    def _should_preserve_linux_controller_device(value: str) -> bool:
        if not _looks_valid_existing_device(value):
            return False
        normalized = value.strip()
        lowered = normalized.casefold()
        if any(marker in lowered for marker in _DOLPHIN_KBM_FALLBACK_DEVICE_MARKERS):
            return False
        if any(marker in lowered for marker in _DOLPHIN_NON_GAMEPAD_DEVICE_MARKERS):
            return False
        if lowered.startswith("sdl/"):
            parts = normalized.split("/", 2)
            if len(parts) != 3:
                return False
            if parts[2].strip().casefold() in _DOLPHIN_GENERIC_SDL_DEVICE_NAMES:
                return False
        return True

    for section_name, device in (
        ("GCPad1", pad_device0),
        ("GCPad2", pad_device1),
        ("Wiimote1", pad_device0),
        ("Wiimote2", pad_device1),
    ):
        if section_name not in updated:
            continue
        existing_device = None
        if existing_sections is not None:
            existing_device = existing_sections.get(section_name, {}).get("Device")
        if sys.platform.startswith("linux") and profile_name != PROFILE_KBM and existing_device is not None:
            preserve_existing = (not is_steam_deck_linux()) and _should_preserve_linux_controller_device(
                existing_device
            )
            if preserve_existing:
                updated[section_name]["Device"] = existing_device
                continue
        if sys.platform == "darwin" and profile_name != PROFILE_KBM and existing_device is not None:
            preserve_existing = (
                not detected_controllers
                and _is_specific_macos_sdl_device(existing_device)
                and _is_generic_macos_sdl_device(device)
            )
            if preserve_existing:
                updated[section_name]["Device"] = existing_device
                if not selected_device and section_name in {"GCPad1", "Wiimote1"}:
                    selected_device = existing_device
                continue
        updated[section_name]["Device"] = device
        device_identity_mode = "rebind"

    for section_name, device in (
        ("Hotkeys1", hotkey_device0),
        ("Hotkeys2", hotkey_device1),
        ("Hotkeys", hotkey_device0),
    ):
        if section_name not in updated:
            continue
        updated[section_name]["Device"] = device
    return updated, device_identity_mode, selected_device


def _dolphin_hotkey_expression_for_profile(
    profile_name: str,
) -> str:
    if profile_name == PROFILE_KBM:
        return "ESCAPE"
    if sys.platform == "darwin":
        return _DOLPHIN_MACOS_HOTKEY_COMBO
    return "((`BACK` | `Back` | `SELECT` | `Select` | `Button 6`) & (`START` | `Start` | `Button 7`))"


def _dolphin_hotkey_exit_expression_for_profile(
    profile_name: str,
) -> str:
    if profile_name == PROFILE_KBM:
        return "ESCAPE"
    return _dolphin_hotkey_expression_for_profile(profile_name)


def _dolphin_general_hotkey_expression_for_profile(profile_name: str) -> str:
    if profile_name == PROFILE_KBM:
        return "ESCAPE"
    if sys.platform == "darwin":
        return _DOLPHIN_MACOS_HOTKEY_COMBO
    return _dolphin_hotkey_expression_for_profile(profile_name)


def _override_dolphin_hotkey_sections(
    sections: dict[str, dict[str, str]],
    *,
    profile_name: str,
) -> dict[str, dict[str, str]]:
    updated: dict[str, dict[str, str]] = {section: dict(values) for section, values in sections.items()}
    hotkey_expr = _dolphin_hotkey_expression_for_profile(profile_name)
    hotkey_exit_expr = _dolphin_hotkey_exit_expression_for_profile(profile_name)
    for section_name in ("Hotkeys1", "Hotkeys2"):
        if section_name not in updated:
            continue
        updated[section_name]["Keys/Stop"] = hotkey_expr
        updated[section_name]["Keys/Exit"] = hotkey_exit_expr
    if "Hotkeys" in updated:
        updated["Hotkeys"]["General/Stop"] = _dolphin_general_hotkey_expression_for_profile(profile_name)
        updated["Hotkeys"]["General/Exit"] = _dolphin_general_hotkey_expression_for_profile(profile_name)
    return updated


def _normalize_macos_keyboard_binding(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return value
    if normalized.startswith("@(") and normalized.endswith(")"):
        expression = normalized[2:-1]
        expression = expression.replace("RETURN", "Return")
        expression = expression.replace("ESCAPE", "Escape")
        return f"@({expression})"
    wrapped = normalized.startswith("`") and normalized.endswith("`") and len(normalized) >= 2
    inner = normalized[1:-1] if wrapped else normalized
    mapped = _DOLPHIN_MACOS_KEY_TOKEN_MAP.get(inner.strip().upper())
    if mapped is None:
        return value
    if wrapped or " " in mapped:
        return f"`{mapped}`"
    return mapped


def _normalize_macos_kbm_sections(sections: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    updated: dict[str, dict[str, str]] = {section: dict(values) for section, values in sections.items()}
    for values in updated.values():
        for key, current_value in list(values.items()):
            if key == "Device":
                continue
            values[key] = _normalize_macos_keyboard_binding(current_value)
    return updated


def _normalize_macos_controller_sections(
    sections: dict[str, dict[str, str]],
    *,
    profile_name: str,
) -> dict[str, dict[str, str]]:
    updated: dict[str, dict[str, str]] = {section: dict(values) for section, values in sections.items()}

    controller_gc_sections = ("GCPad1",) if profile_name == PROFILE_XBOX_1P else ("GCPad1", "GCPad2")
    controller_wii_sections = ("Wiimote1",) if profile_name == PROFILE_XBOX_1P else ("Wiimote1", "Wiimote2")

    for section_name in controller_gc_sections:
        values = updated.get(section_name)
        if values is None:
            continue
        values.update(_DOLPHIN_MACOS_GCPAD_BINDINGS)

    for section_name in controller_wii_sections:
        values = updated.get(section_name)
        if values is None:
            continue
        values.update(_DOLPHIN_MACOS_WIIMOTE_BINDINGS)

    return updated


def _apply_deck_wiimote_pointer_defaults(section: dict[str, str]) -> None:
    section["IR/Up"] = "`XInput2/0/Virtual core pointer:Cursor Y-`"
    section["IR/Down"] = "`XInput2/0/Virtual core pointer:Cursor Y+`"
    section["IR/Left"] = "`XInput2/0/Virtual core pointer:Cursor X-`"
    section["IR/Right"] = "`XInput2/0/Virtual core pointer:Cursor X+`"


def _merge_dolphin_deck_pointer_sections(
    managed_sections: dict[str, dict[str, str]],
    *,
    profile_name: str,
) -> dict[str, dict[str, str]]:
    if not sys.platform.startswith("linux"):
        return managed_sections
    if profile_name == PROFILE_KBM:
        return managed_sections
    if not is_steam_deck_linux():
        return managed_sections
    updated: dict[str, dict[str, str]] = {section: dict(values) for section, values in managed_sections.items()}
    managed_wiimote = updated.get("Wiimote1")
    if managed_wiimote is None:
        return updated
    # Deck behavior is deterministic here: always seed Wii IR to mouse pointer mapping.
    _apply_deck_wiimote_pointer_defaults(managed_wiimote)
    return updated


def apply_dolphin_profile(
    config: GamehubConfig,
    profile_name: str,
    *,
    audit_writer: Callable[[str], None] | None = None,
) -> list[Path]:
    touched: list[Path] = []
    device_identity_modes: list[str] = []
    selected_devices: list[str] = []
    macos_controllers = detect_xbox_controllers(max_devices=2) if sys.platform == "darwin" else []
    for target_dir in _dolphin_target_config_dirs(config):
        dolphin_ini = target_dir / "Dolphin.ini"
        dolphin_sections = {
            "Core": {"SIDevice0": "6", "SIDevice1": "6"},
            "Controls": {"WiimoteSource0": "1", "WiimoteSource1": "1"},
        }
        apply_managed_ini_sections(target_path=dolphin_ini, sections=dolphin_sections)
        touched.append(dolphin_ini)
        for filename in ("GCPadNew.ini", "WiimoteNew.ini", "Hotkeys.ini"):
            profile_lines = load_profile_file(
                config,
                emulator_name="dolphin",
                profile_name=profile_name,
                filename=filename,
            )
            sections = parse_ini_sections(profile_lines)
            target_path = target_dir / filename
            existing_sections = (
                parse_ini_sections(target_path.read_text(encoding="utf-8").splitlines()) if target_path.exists() else {}
            )
            sections, device_identity_mode, selected_device = _override_dolphin_device_sections(
                sections,
                profile_name=profile_name,
                existing_sections=existing_sections,
                detected_controllers=macos_controllers,
            )
            sections = _merge_dolphin_deck_pointer_sections(
                sections,
                profile_name=profile_name,
            )
            sections = _override_dolphin_hotkey_sections(
                sections,
                profile_name=profile_name,
            )
            if sys.platform == "darwin":
                if profile_name == PROFILE_KBM:
                    sections = _normalize_macos_kbm_sections(sections)
                else:
                    sections = _normalize_macos_controller_sections(sections, profile_name=profile_name)
            apply_managed_ini_sections(target_path=target_path, sections=sections)
            touched.append(target_path)
            device_identity_modes.append(device_identity_mode)
            if selected_device:
                selected_devices.append(selected_device)
    if device_identity_modes:
        overall_mode = "preserve" if all(mode == "preserve" for mode in device_identity_modes) else "rebind"
        if audit_writer is not None:
            if selected_devices:
                audit_writer(f"controller-autoconfig\tdolphin_device_selected={selected_devices[0]}")
            audit_writer(f"controller-autoconfig\tdevice_identity_mode={overall_mode}")
    return touched
