from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SteamContext:
    userdata_dir: Path
    steam_id: str
    shortcuts_path: Path
    localconfig_path: Path
    steam_exe: Path | None
    cloudstorage_path: Path | None = None


@dataclass(frozen=True)
class SteamShortcutSpec:
    title_id: str
    system: str
    title_name: str
    exe: str
    launch_options: str
    start_dir: str = ""
    icon_path: str = ""
    allow_desktop_config: bool | None = None


@dataclass(frozen=True)
class SteamArtworkAssignment:
    steam_app_id: str
    assets_by_kind: dict[str, Path]


@dataclass(frozen=True)
class ShortcutSyncResult:
    app_ids_by_title: dict[str, str]
    app_ids_by_system: dict[str, list[str]]
    total_shortcuts: int


GAMEHUB_TAG = "GAMEHUB"
GAMEHUB_TITLE_PREFIX = "GAMEHUB_TITLE:"
GAMEHUB_SYSTEM_PREFIX = "GAMEHUB_SYSTEM:"
USER_COLLECTIONS_KEY = "user-collections"
STEAM_ID64_BASE = 76561197960265728
DEFAULT_USER_COLLECTIONS_PATH = [
    "UserLocalConfigStore",
    "WebStorage",
    USER_COLLECTIONS_KEY,
]
LINUX_STEAM_PROCESS_NAMES = ("steam", "steam.sh", "steamwebhelper")
