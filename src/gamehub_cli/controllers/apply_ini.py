from __future__ import annotations

import logging
from pathlib import Path

from ..common.fsops import backup_existing_file
from ..firmware.pcsx2_ini import read_ini_lines, upsert_ini_key, write_ini_atomic

logger = logging.getLogger(__name__)


def parse_ini_sections(lines: list[str]) -> dict[str, dict[str, str]]:
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


def write_controller_config_lines_atomic(path: Path, lines: list[str]) -> Path | None:
    backup_path = backup_existing_file(path)
    if backup_path is not None:
        logger.info("controller config backup created path=%s backup=%s", path, backup_path)
    write_ini_atomic(path, lines)
    logger.info("controller config saved path=%s", path)
    return backup_path


def apply_managed_ini_sections(
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
        write_controller_config_lines_atomic(target_path, lines)
    return changed
