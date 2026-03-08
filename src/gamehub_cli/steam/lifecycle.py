from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .types import LINUX_STEAM_PROCESS_NAMES, MACOS_STEAM_PROCESS_NAMES, STEAM_ID64_BASE, SteamContext


def _run_process_best_effort(command: list[str], timeout_seconds: int = 10) -> None:
    try:
        subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return


def _is_macos() -> bool:
    return os.name == "posix" and sys.platform == "darwin"


def _unique_paths(values: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for value in values:
        candidate = value.expanduser()
        if candidate in seen:
            continue
        seen.add(candidate)
        unique.append(candidate)
    return unique


def _normalize_macos_steam_app_path(path: Path | None) -> Path | None:
    if path is None:
        return None
    expanded = path.expanduser()
    if expanded.name.casefold() == "steam.app":
        return expanded
    for parent in expanded.parents:
        if parent.name.casefold() == "steam.app":
            return parent
    return None


def _candidate_macos_steam_apps(explicit: Path | None = None) -> list[Path]:
    candidates: list[Path] = []
    normalized_explicit = _normalize_macos_steam_app_path(explicit)
    if normalized_explicit is not None:
        candidates.append(normalized_explicit)
    home = Path.home()
    candidates.append(home / "Applications" / "Steam.app")
    candidates.append(Path("/Applications/Steam.app"))
    return _unique_paths(candidates)


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
    if _is_macos():
        candidates.append(home / "Library" / "Application Support" / "Steam" / "userdata")
    candidates.append(home / ".steam" / "steam" / "userdata")
    candidates.append(home / ".steam" / "root" / "userdata")
    candidates.append(home / ".local" / "share" / "Steam" / "userdata")
    candidates.append(home / ".var" / "app" / "com.valvesoftware.Steam" / ".steam" / "steam" / "userdata")
    candidates.append(home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam" / "userdata")
    candidates.append(home / ".var" / "app" / "com.valvesoftware.Steam" / "data" / "Steam" / "userdata")
    return candidates


def steam_id64_from_userdata_id(userdata_id: str) -> str | None:
    if not userdata_id.isdigit():
        return None
    value = int(userdata_id)
    if value >= STEAM_ID64_BASE:
        return str(value)
    return str(value + STEAM_ID64_BASE)


def _preferred_steam_id_candidates(preferred_steam_id: str) -> list[str]:
    if not preferred_steam_id.isdigit():
        return []
    value = int(preferred_steam_id)
    values = [str(value)]
    if value >= STEAM_ID64_BASE:
        account_id = value - STEAM_ID64_BASE
        if account_id > 0:
            values.append(str(account_id))
    else:
        values.append(str(value + STEAM_ID64_BASE))
    unique: list[str] = []
    seen: set[str] = set()
    for item in values:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def discover_userdata_dir(explicit: Path | None) -> Path | None:
    if explicit is not None:
        if explicit.exists():
            return explicit
        return None
    for candidate in _candidate_userdata_dirs():
        if candidate.exists():
            return candidate
    return None


def discover_steam_id(userdata_dir: Path, preferred_steam_id: str | None = None) -> str | None:
    if preferred_steam_id is not None:
        if not preferred_steam_id.isdigit():
            raise ValueError(f"Configured steam_id is not numeric: {preferred_steam_id}")
        candidates = _preferred_steam_id_candidates(preferred_steam_id)
        for candidate in candidates:
            target = userdata_dir / candidate
            if target.exists() and target.is_dir():
                return candidate
        raise ValueError(
            f"Configured steam_id was not found in userdata: {preferred_steam_id} (tried: {', '.join(candidates)})"
        )
    numeric_dirs = [item for item in userdata_dir.iterdir() if item.is_dir() and item.name.isdigit()]
    if not numeric_dirs:
        return None
    if len(numeric_dirs) == 1:
        return numeric_dirs[0].name

    def _profile_score(profile_dir: Path) -> float:
        config_dir = profile_dir / "config"
        candidates = [
            config_dir / "localconfig.vdf",
            config_dir / "shortcuts.vdf",
            profile_dir,
        ]
        newest = 0.0
        for candidate in candidates:
            try:
                newest = max(newest, candidate.stat().st_mtime)
            except FileNotFoundError:
                continue
        return newest

    ranked = sorted(numeric_dirs, key=lambda item: (-_profile_score(item), item.name))
    return ranked[0].name


def build_context(userdata_dir: Path, steam_id: str, steam_exe: Path | None) -> SteamContext:
    config_dir = userdata_dir / steam_id / "config"
    cloudstorage_path = config_dir / "cloudstorage" / "cloud-storage-namespace-1.json"
    normalized_steam_exe = steam_exe.expanduser() if steam_exe is not None else None
    if _is_macos():
        normalized_steam_exe = _normalize_macos_steam_app_path(steam_exe) or normalized_steam_exe
    return SteamContext(
        userdata_dir=userdata_dir,
        steam_id=steam_id,
        shortcuts_path=config_dir / "shortcuts.vdf",
        localconfig_path=config_dir / "localconfig.vdf",
        steam_exe=normalized_steam_exe,
        cloudstorage_path=cloudstorage_path,
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
    process_names = MACOS_STEAM_PROCESS_NAMES if _is_macos() else LINUX_STEAM_PROCESS_NAMES
    for process_name in process_names:
        completed = subprocess.run(["pgrep", "-x", process_name], check=False, capture_output=True, text=True)
        if completed.returncode == 0:
            return True
    return False


def close_steam_best_effort() -> None:
    if os.name == "nt":
        # First attempt graceful close; then force kill as fallback.
        _run_process_best_effort(["taskkill", "/IM", "steam.exe", "/T"])
        _run_process_best_effort(["taskkill", "/F", "/IM", "steam.exe", "/T"])
        return
    process_names = LINUX_STEAM_PROCESS_NAMES
    if _is_macos():
        _run_process_best_effort(["osascript", "-e", 'tell application id "com.valvesoftware.steam" to quit'])
        process_names = MACOS_STEAM_PROCESS_NAMES
    for process_name in process_names:
        _run_process_best_effort(["pkill", "-x", process_name])
    for process_name in process_names:
        _run_process_best_effort(["pkill", "-9", "-x", process_name])


def wait_for_steam_exit(timeout_seconds: int = 20) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not is_steam_running():
            return True
        time.sleep(0.5)
    return not is_steam_running()


def _spawn_detached(command: list[str], *, shell: bool = False) -> subprocess.Popen:
    if os.name != "nt":
        return subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            shell=shell,
            start_new_session=True,
        )
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        shell=shell,
    )


def _wait_for_steam_start(timeout_seconds: float = 12.0) -> bool:
    deadline = time.time() + timeout_seconds
    consecutive_running = 0
    while time.time() < deadline:
        if is_steam_running():
            consecutive_running += 1
            if consecutive_running >= 2:
                return True
        else:
            consecutive_running = 0
        time.sleep(0.5)
    return is_steam_running()


def reopen_steam(context: SteamContext) -> bool:
    if _is_macos():
        for steam_app in _candidate_macos_steam_apps(context.steam_exe):
            if not steam_app.exists():
                continue
            try:
                _spawn_detached(["open", "-a", str(steam_app)])
            except OSError:
                continue
            if _wait_for_steam_start():
                return True
        return False
    if context.steam_exe and context.steam_exe.exists():
        try:
            _spawn_detached([str(context.steam_exe)])
        except OSError:
            pass
        else:
            if _wait_for_steam_start():
                return True
    if os.name == "nt":
        try:
            _spawn_detached(["cmd", "/c", "start", "", "steam://open/main"], shell=False)
        except OSError:
            return False
        return _wait_for_steam_start()
    launchers: list[list[str]] = []
    if shutil.which("steam"):
        launchers.append(["steam", "steam://open/main"])
    if shutil.which("xdg-open"):
        launchers.append(["xdg-open", "steam://open/main"])
    if shutil.which("flatpak"):
        launchers.append(["flatpak", "run", "com.valvesoftware.Steam", "steam://open/main"])
    for command in launchers:
        try:
            _spawn_detached(command)
        except OSError:
            continue
        if _wait_for_steam_start():
            return True
    return False
