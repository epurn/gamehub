from __future__ import annotations

import sys
from pathlib import Path

from ..common.config import GamehubConfig
from ..firmware.targets import resolve_dolphin_config_dirs, resolve_dolphin_runtime_user_dir
from .apply_ini import apply_managed_ini_sections, parse_ini_sections
from .detection import detect_xbox_controllers
from .profiles import PROFILE_KBM, PROFILE_XBOX_1P, PROFILE_XBOX_2P, load_profile_file


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
        return f"evdev/0/{controllers[0].name}", "XInput2/0/Virtual core pointer"
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


def _override_dolphin_device_sections(
    sections: dict[str, dict[str, str]],
    *,
    profile_name: str,
) -> dict[str, dict[str, str]]:
    if sys.platform.startswith("linux"):
        if profile_name == PROFILE_KBM:
            pad_device0, pad_device1 = "XInput2/0/Virtual core pointer", "None"
            hotkey_device0, hotkey_device1 = "XInput2/0/Virtual core pointer", "XInput2/0/Virtual core pointer"
        else:
            pad_device0, pad_device1 = _dolphin_linux_device_pair()
            hotkey_device0, hotkey_device1 = "All Devices", "All Devices"
    elif sys.platform.startswith("win"):
        pad_device0, pad_device1 = _dolphin_windows_device_pair(profile_name)
        hotkey_device0, hotkey_device1 = pad_device0, pad_device1
    else:
        return sections
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
        return "ESCAPE"
    return "((`BACK` | `Back` | `SELECT` | `Select` | `Button 6`) & (`START` | `Start` | `Button 7`))"


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


def apply_dolphin_profile(config: GamehubConfig, profile_name: str) -> list[Path]:
    touched: list[Path] = []
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
            sections = _override_dolphin_device_sections(sections, profile_name=profile_name)
            sections = _override_dolphin_hotkey_sections(sections, profile_name=profile_name)
            target_path = target_dir / filename
            apply_managed_ini_sections(target_path=target_path, sections=sections)
            touched.append(target_path)
    return touched
