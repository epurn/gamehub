from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


RETROARCH_FLATPAK_APP_ID = "org.libretro.RetroArch"
PCSX2_FLATPAK_APP_ID = "net.pcsx2.PCSX2"
DOLPHIN_FLATPAK_APP_ID = "org.DolphinEmu.dolphin-emu"


def linux_flatpak_retroarch_root() -> Path:
    return Path.home() / ".var" / "app" / RETROARCH_FLATPAK_APP_ID / "config" / "retroarch"


def linux_flatpak_pcsx2_root() -> Path:
    return Path.home() / ".var" / "app" / PCSX2_FLATPAK_APP_ID / "config" / "PCSX2"


def linux_flatpak_dolphin_root() -> Path:
    return Path.home() / ".var" / "app" / DOLPHIN_FLATPAK_APP_ID / "data" / "dolphin-emu"


def is_flatpak_command(path_value: str | Path, app_id: str) -> bool:
    if isinstance(path_value, Path):
        raw = path_value.as_posix()
    else:
        raw = str(path_value)
    normalized = raw.strip().strip('"').replace("\\", "/").casefold()
    app = app_id.casefold()
    return normalized.endswith(f"/{app}") or f"flatpak/exports/bin/{app}" in normalized


def unique_paths(values: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[Path] = set()
    for value in values:
        candidate = value.expanduser()
        if candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)
    return result


def parse_simple_kv_config(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    parsed: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or raw.startswith(";") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        parsed[key.strip().lower()] = value.strip().strip('"').strip("'")
    return parsed


def retroarch_cfg_candidates(explicit_cfg_path: Path | None = None) -> list[Path]:
    values: list[Path] = []
    if explicit_cfg_path is not None:
        values.append(explicit_cfg_path.expanduser())

    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        values.append(Path(appdata) / "RetroArch" / "retroarch.cfg")

    home = Path.home()
    values.append(home / ".config" / "retroarch" / "retroarch.cfg")
    values.append(linux_flatpak_retroarch_root() / "retroarch.cfg")
    return unique_paths(values)
