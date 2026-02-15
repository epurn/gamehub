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


from .steam_collections import (  # noqa: E402
    _collection_id_for_system,
    _decode_user_collections,
    _dump_localconfig,
    _find_key_path,
    _load_cloudstorage_entries,
    _load_localconfig,
    _next_cloudstorage_version,
    _resolve_path,
    _set_path,
    _to_int_if_numeric,
    _write_cloudstorage_entries,
    update_cloud_collections,
    update_collections,
)
from .steam_artwork import (  # noqa: E402
    _unlink_best_effort,
    backup_steam_configs,
    copy_grid_art,
    prune_grid_noncanonical_variants,
)
from .steam_io import _atomic_write_bytes, _atomic_write_text  # noqa: E402
from .steam_lifecycle import (  # noqa: E402
    _candidate_userdata_dirs,
    _preferred_steam_id_candidates,
    _run_process_best_effort,
    _spawn_detached,
    _wait_for_steam_start,
    build_context,
    close_steam_best_effort,
    discover_steam_id,
    discover_userdata_dir,
    is_steam_running,
    reopen_steam,
    steam_id64_from_userdata_id,
    wait_for_steam_exit,
)
from .steam_shortcuts import (  # noqa: E402
    _build_shortcut_entry,
    _canonical_signed_app_id_from_unsigned,
    _canonical_unsigned_app_id,
    _compute_shortcut_app_id,
    _emulator_family,
    _encode_shortcuts,
    _extract_path_basenames,
    _extract_persisted_app_id,
    _extract_tag_value,
    _is_managed_shortcut,
    _legacy_shortcut_matches,
    _normalize_launch_options,
    _normalize_shortcuts_tags,
    _parse_shortcuts_table,
    _pop_legacy_match,
    _tags_to_vdf_map,
    upsert_shortcuts,
)


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
