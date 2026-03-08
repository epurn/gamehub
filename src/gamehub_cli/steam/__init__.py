from __future__ import annotations

from .artwork import backup_steam_configs, copy_grid_art, prune_grid_noncanonical_variants
from .collections import repair_managed_steam_input_overrides, update_cloud_collections, update_collections
from .deck_templates import (
    TemplateSyncResult,
    apply_deck_steam_input_templates,
    discover_deck_steam_input_roots,
    normalize_steam_input_title_dir,
)
from .lifecycle import (
    build_context,
    close_steam_best_effort,
    discover_steam_id,
    discover_userdata_dir,
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

__all__ = [
    "DEFAULT_USER_COLLECTIONS_PATH",
    "GAMEHUB_SYSTEM_PREFIX",
    "GAMEHUB_TAG",
    "GAMEHUB_TITLE_PREFIX",
    "LINUX_STEAM_PROCESS_NAMES",
    "TemplateSyncResult",
    "STEAM_ID64_BASE",
    "ShortcutSyncResult",
    "SteamArtworkAssignment",
    "SteamContext",
    "SteamShortcutSpec",
    "USER_COLLECTIONS_KEY",
    "apply_deck_steam_input_templates",
    "backup_steam_configs",
    "build_context",
    "close_steam_best_effort",
    "copy_grid_art",
    "discover_deck_steam_input_roots",
    "discover_steam_id",
    "discover_userdata_dir",
    "is_steam_running",
    "normalize_steam_input_title_dir",
    "prune_grid_noncanonical_variants",
    "repair_managed_steam_input_overrides",
    "reopen_steam",
    "steam_id64_from_userdata_id",
    "update_cloud_collections",
    "update_collections",
    "upsert_shortcuts",
    "wait_for_steam_exit",
]
