from __future__ import annotations

import os
from pathlib import Path
import tempfile

from ..common.fsops import replace_file

PCSX2_OPEN_PAUSE_MENU_HOTKEY = "SDL-0/Back & SDL-0/Start"


def read_ini_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="ignore").splitlines()


def read_ini_key(lines: list[str], section: str, key: str) -> str | None:
    section_name = section.lower()
    key_name = key.lower()
    in_section = False
    for line in lines:
        stripped = line.strip()
        is_section = stripped.startswith("[") and stripped.endswith("]")
        if is_section:
            current = stripped[1:-1].strip().lower()
            in_section = current == section_name
            continue
        if not in_section or "=" not in line:
            continue
        current_key, value = line.split("=", 1)
        if current_key.strip().lower() != key_name:
            continue
        return value.strip()
    return None


def is_missing_pad_binding(value: str | None) -> bool:
    if value is None:
        return True
    normalized = value.strip().strip('"').strip("'").casefold()
    return normalized in {"", "none", "nul", "null", "unbound"}


def is_keyboard_or_mouse_binding(value: str | None) -> bool:
    if value is None:
        return False
    normalized = value.strip().strip('"').strip("'").casefold()
    return "keyboard/" in normalized or "mouse/" in normalized


def pcsx2_pad_bindings(pad_index: int) -> tuple[tuple[str, str], ...]:
    prefix = f"SDL-{pad_index}/"
    return (
        ("Up", f"{prefix}DPadUp"),
        ("Right", f"{prefix}DPadRight"),
        ("Down", f"{prefix}DPadDown"),
        ("Left", f"{prefix}DPadLeft"),
        ("Triangle", f"{prefix}Y"),
        ("Circle", f"{prefix}B"),
        ("Cross", f"{prefix}A"),
        ("Square", f"{prefix}X"),
        ("Select", f"{prefix}Back"),
        ("Start", f"{prefix}Start"),
        ("L1", f"{prefix}LeftShoulder"),
        ("L2", f"{prefix}+LeftTrigger"),
        ("R1", f"{prefix}RightShoulder"),
        ("R2", f"{prefix}+RightTrigger"),
        ("L3", f"{prefix}LeftStick"),
        ("R3", f"{prefix}RightStick"),
        ("LUp", f"{prefix}-LeftY"),
        ("LRight", f"{prefix}+LeftX"),
        ("LDown", f"{prefix}+LeftY"),
        ("LLeft", f"{prefix}-LeftX"),
        ("RUp", f"{prefix}-RightY"),
        ("RRight", f"{prefix}+RightX"),
        ("RDown", f"{prefix}+RightY"),
        ("RLeft", f"{prefix}-RightX"),
        ("LargeMotor", f"{prefix}LargeMotor"),
        ("SmallMotor", f"{prefix}SmallMotor"),
    )


def upsert_ini_key(lines: list[str], section: str, key: str, value: str) -> tuple[list[str], bool]:
    section_name = section.lower()
    key_name = key.lower()
    output: list[str] = []
    in_section = False
    section_found = False
    key_found = False
    changed = False

    for line in lines:
        stripped = line.strip()
        is_section = stripped.startswith("[") and stripped.endswith("]")
        if is_section:
            if in_section and not key_found:
                output.append(f"{key} = {value}")
                key_found = True
                changed = True
            current = stripped[1:-1].strip().lower()
            in_section = current == section_name
            if in_section:
                section_found = True
            output.append(line)
            continue

        if in_section and "=" in line:
            current_key = line.split("=", 1)[0].strip().lower()
            if current_key == key_name:
                desired = f"{key} = {value}"
                if stripped != desired:
                    output.append(desired)
                    changed = True
                else:
                    output.append(line)
                key_found = True
                continue

        output.append(line)

    if in_section and not key_found:
        output.append(f"{key} = {value}")
        changed = True
        key_found = True

    if not section_found:
        if output and output[-1].strip():
            output.append("")
        output.append(f"[{section}]")
        output.append(f"{key} = {value}")
        changed = True

    return output, changed


def bootstrap_pcsx2_controllers(lines: list[str]) -> tuple[list[str], bool]:
    changed = False
    lines, changed_sdl = upsert_ini_key(lines, "InputSources", "SDL", "true")
    changed |= changed_sdl
    for pad_index in (1, 2):
        section = f"Pad{pad_index}"
        pad_type = read_ini_key(lines, section, "Type")
        if is_missing_pad_binding(pad_type):
            lines, changed_type = upsert_ini_key(lines, section, "Type", "DualShock2")
            changed |= changed_type
        for key, value in pcsx2_pad_bindings(pad_index - 1):
            existing = read_ini_key(lines, section, key)
            if not is_missing_pad_binding(existing) and not is_keyboard_or_mouse_binding(existing):
                continue
            lines, changed_binding = upsert_ini_key(lines, section, key, value)
            changed |= changed_binding
    return lines, changed


def should_bootstrap_hotkey_binding(value: str | None) -> bool:
    if is_missing_pad_binding(value):
        return True
    return is_keyboard_or_mouse_binding(value)


def bootstrap_pcsx2_hotkeys(lines: list[str]) -> tuple[list[str], bool]:
    changed = False
    existing_open_pause_menu = read_ini_key(lines, "Hotkeys", "OpenPauseMenu")
    if should_bootstrap_hotkey_binding(existing_open_pause_menu):
        lines, changed_open_pause_menu = upsert_ini_key(
            lines,
            "Hotkeys",
            "OpenPauseMenu",
            PCSX2_OPEN_PAUSE_MENU_HOTKEY,
        )
        changed |= changed_open_pause_menu
    return lines, changed


def write_ini_atomic(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(lines).rstrip() + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp") as tmp:
        tmp.write(payload)
        tmp.flush()
        os.fsync(tmp.fileno())
        # Keep temp path in the same concrete path type as `path` (WindowsPath on Windows),
        # even when tests monkeypatch os.name/sys.platform for Linux-branch simulation.
        tmp_path = path.parent / os.path.basename(tmp.name)
    replace_file(tmp_path, path)
