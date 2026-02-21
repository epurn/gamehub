from __future__ import annotations

from . import lifecycle as _lifecycle
from .artwork import backup_steam_configs, copy_grid_art, prune_grid_noncanonical_variants
from .collections import update_cloud_collections, update_collections
from .lifecycle import (
    build_context,
    close_steam_best_effort,
    is_steam_running,
    reopen_steam,
    steam_id64_from_userdata_id,
    wait_for_steam_exit,
)
from .shortcuts import upsert_shortcuts
from .types import (
    DEFAULT_USER_COLLECTIONS_PATH,
    GAMEHUB_SYSTEM_PREFIX,
    GAMEHUB_TAG,
    GAMEHUB_TITLE_PREFIX,
    LINUX_STEAM_PROCESS_NAMES,
    STEAM_ID64_BASE,
    USER_COLLECTIONS_KEY,
    ShortcutSyncResult,
    SteamArtworkAssignment,
    SteamContext,
    SteamShortcutSpec,
)

_candidate_userdata_dirs = _lifecycle._candidate_userdata_dirs


def discover_userdata_dir(explicit_userdata_dir=None):
    _lifecycle._candidate_userdata_dirs = _candidate_userdata_dirs
    return _lifecycle.discover_userdata_dir(explicit_userdata_dir)


def discover_steam_id(userdata_dir, preferred_steam_id=None):
    return _lifecycle.discover_steam_id(userdata_dir, preferred_steam_id=preferred_steam_id)


__all__ = [
    "DEFAULT_USER_COLLECTIONS_PATH",
    "GAMEHUB_SYSTEM_PREFIX",
    "GAMEHUB_TAG",
    "GAMEHUB_TITLE_PREFIX",
    "LINUX_STEAM_PROCESS_NAMES",
    "STEAM_ID64_BASE",
    "ShortcutSyncResult",
    "SteamArtworkAssignment",
    "SteamContext",
    "SteamShortcutSpec",
    "USER_COLLECTIONS_KEY",
    "_candidate_userdata_dirs",
    "backup_steam_configs",
    "build_context",
    "close_steam_best_effort",
    "copy_grid_art",
    "discover_steam_id",
    "discover_userdata_dir",
    "is_steam_running",
    "prune_grid_noncanonical_variants",
    "reopen_steam",
    "steam_id64_from_userdata_id",
    "update_cloud_collections",
    "update_collections",
    "upsert_shortcuts",
    "wait_for_steam_exit",
]
