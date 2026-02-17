from __future__ import annotations

from pathlib import Path
import os
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
    if profile_name == PROFILE_KBM:
        return sections
    if not sys.platform.startswith("linux"):
        return sections
    device0, device1 = _dolphin_linux_device_pair()
    updated: dict[str, dict[str, str]] = {section: dict(values) for section, values in sections.items()}
    for section_name, device in (
        ("GCPad1", device0),
        ("GCPad2", device1),
        ("Wiimote1", device0),
        ("Wiimote2", device1),
        ("Hotkeys1", device0),
        ("Hotkeys2", device1),
        ("Hotkeys", device0),
    ):
        if section_name not in updated:
            continue
        updated[section_name]["Device"] = device
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
    for target_path in _azahar_target_config_paths():
        lines = read_ini_lines(target_path)
        changed = False
        for key, value in pairs.items():
            if _read_qsettings_key(lines, key) == value:
                continue
            lines, key_changed = _upsert_qsettings_key(lines, key, value)
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
