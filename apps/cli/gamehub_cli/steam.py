from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class SteamContext:
    userdata_dir: Path
    steam_id: str
    shortcuts_path: Path
    localconfig_path: Path
    steam_exe: Path | None


def _candidate_userdata_dirs() -> list[Path]:
    candidates: list[Path] = []
    if os.name == "nt":
        pf86 = os.environ.get("PROGRAMFILES(X86)")
        pf = os.environ.get("PROGRAMFILES")
        if pf86:
            candidates.append(Path(pf86) / "Steam" / "userdata")
        if pf:
            candidates.append(Path(pf) / "Steam" / "userdata")
    home = Path.home()
    candidates.append(home / ".steam" / "steam" / "userdata")
    candidates.append(home / ".local" / "share" / "Steam" / "userdata")
    return candidates


def discover_userdata_dir(explicit: Path | None) -> Path | None:
    if explicit and explicit.exists():
        return explicit
    for candidate in _candidate_userdata_dirs():
        if candidate.exists():
            return candidate
    return None


def discover_steam_id(userdata_dir: Path) -> str | None:
    numeric_dirs = [item.name for item in userdata_dir.iterdir() if item.is_dir() and item.name.isdigit()]
    if not numeric_dirs:
        return None
    return sorted(numeric_dirs)[0]


def build_context(userdata_dir: Path, steam_id: str, steam_exe: Path | None) -> SteamContext:
    config_dir = userdata_dir / steam_id / "config"
    return SteamContext(
        userdata_dir=userdata_dir,
        steam_id=steam_id,
        shortcuts_path=config_dir / "shortcuts.vdf",
        localconfig_path=config_dir / "localconfig.vdf",
        steam_exe=steam_exe,
    )


def is_steam_running() -> bool:
    if os.name == "nt":
        completed = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq steam.exe"],
            check=False,
            capture_output=True,
            text=True,
        )
        return "steam.exe" in completed.stdout.lower()
    completed = subprocess.run(["pgrep", "-f", "steam"], check=False, capture_output=True, text=True)
    return completed.returncode == 0


def close_steam_best_effort() -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/IM", "steam.exe", "/T"], check=False, capture_output=True)
        return
    subprocess.run(["pkill", "-f", "steam"], check=False, capture_output=True)


def wait_for_steam_exit(timeout_seconds: int = 20) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not is_steam_running():
            return True
        time.sleep(0.5)
    return not is_steam_running()


def backup_steam_configs(context: SteamContext) -> list[Path]:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backups: list[Path] = []
    for source in (context.shortcuts_path, context.localconfig_path):
        if not source.exists():
            continue
        destination = source.with_name(f"{source.name}.{timestamp}.bak")
        shutil.copy2(source, destination)
        backups.append(destination)
    return backups


def upsert_shortcuts_placeholder() -> None:
    return


def update_collections_placeholder() -> None:
    return


def copy_grid_art_placeholder() -> None:
    return


def reopen_steam(context: SteamContext) -> None:
    if context.steam_exe and context.steam_exe.exists():
        subprocess.Popen([str(context.steam_exe)])
        return
    if os.name == "nt":
        subprocess.Popen(["cmd", "/c", "start", "", "steam://open/main"], shell=False)
