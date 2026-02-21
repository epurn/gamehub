from __future__ import annotations

from pathlib import Path

from ..common.config import GamehubConfig
from ..firmware.targets import default_pcsx2_ini_path
from .apply_ini import apply_managed_ini_sections, parse_ini_sections
from .profiles import load_profile_file

_MANAGED_PCSX2_SECTIONS = ("InputSources", "Pad1", "Pad2", "Hotkeys", "UI")


def apply_pcsx2_profile(config: GamehubConfig, profile_name: str) -> list[Path]:
    profile_lines = load_profile_file(
        config,
        emulator_name="pcsx2",
        profile_name=profile_name,
        filename="PCSX2.ini",
    )
    sections = parse_ini_sections(profile_lines)
    managed_sections = {
        section_name: dict(sections.get(section_name, {}))
        for section_name in _MANAGED_PCSX2_SECTIONS
        if section_name in sections
    }
    managed_sections.setdefault("UI", {})["ConfirmShutdown"] = "false"
    target = default_pcsx2_ini_path(config=config)
    apply_managed_ini_sections(target_path=target, sections=managed_sections)
    return [target]
