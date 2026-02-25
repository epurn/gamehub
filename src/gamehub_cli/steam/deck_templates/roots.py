from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TypeAlias

from ..lifecycle import steam_id64_from_userdata_id
from ..types import SteamContext

_STEAM_INPUT_CLOUD_APP_ID = "241100"
_WHITESPACE_RE = re.compile(r"\s+")
_APOSTROPHE_RE = re.compile(r"['\u2019]")
_PathIdentity: TypeAlias = tuple[str, int, int] | tuple[str, str]


def normalize_steam_input_title_dir(title_name: str) -> str:
    normalized = title_name.casefold().strip().replace("/", " ").replace("\\", " ")
    normalized = _WHITESPACE_RE.sub(" ", normalized).strip()
    return normalized or "untitled"


def steam_input_title_dir_aliases(title_name: str) -> tuple[str, ...]:
    normalized = normalize_steam_input_title_dir(title_name)
    aliases = [normalized]
    apostrophe_safe = _WHITESPACE_RE.sub(" ", _APOSTROPHE_RE.sub(" ", normalized)).strip()
    if apostrophe_safe and apostrophe_safe != normalized:
        aliases.append(apostrophe_safe)
    return tuple(aliases)


def discover_deck_steam_input_roots(steam_id: str) -> list[Path]:
    home = Path.home()
    candidates = [
        home / ".local" / "share" / "Steam" / "steamapps" / "common" / "Steam Controller Configs" / steam_id / "config",
        home / ".steam" / "steam" / "steamapps" / "common" / "Steam Controller Configs" / steam_id / "config",
        home / ".steam" / "root" / "steamapps" / "common" / "Steam Controller Configs" / steam_id / "config",
    ]
    return _dedupe_paths(candidates)


def path_identity(path: Path) -> _PathIdentity:
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        resolved = path
    try:
        stat = resolved.stat()
    except OSError:
        return ("path", str(resolved).casefold())
    return ("inode", int(stat.st_dev), int(stat.st_ino))


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[_PathIdentity] = set()
    for path in paths:
        identity = path_identity(path)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(path)
    return unique


def _discover_steam_input_cloud_roots(context: SteamContext) -> list[Path]:
    base = context.userdata_dir / context.steam_id / _STEAM_INPUT_CLOUD_APP_ID / "remote"
    steam_ids = [context.steam_id]
    steam_id64 = steam_id64_from_userdata_id(context.steam_id)
    if steam_id64 is not None and steam_id64 not in steam_ids:
        steam_ids.append(steam_id64)
    roots: list[Path] = []
    for steam_id in steam_ids:
        roots.append(base / steam_id / "config")
        roots.append(base / steam_id)
    roots.append(base / "config")
    roots.append(base)
    return roots


def _expand_steam_input_root_variants(candidates: list[Path]) -> list[Path]:
    expanded: list[Path] = []
    for candidate in candidates:
        expanded.append(candidate)
        if candidate.name.casefold() == "config":
            expanded.append(candidate.parent)
    return expanded


def resolve_deck_steam_input_roots(context: SteamContext) -> list[Path]:
    candidates = _expand_steam_input_root_variants(
        [
            *discover_deck_steam_input_roots(context.steam_id),
            *_discover_steam_input_cloud_roots(context),
        ]
    )
    unique_candidates = _dedupe_paths(candidates)
    writable = [
        candidate
        for candidate in unique_candidates
        if candidate.exists() and candidate.is_dir() and os.access(candidate, os.W_OK)
    ]
    writable = _dedupe_paths(writable)
    if writable:
        return writable
    tried = ", ".join(str(path) for path in unique_candidates) or "<none>"
    raise RuntimeError(
        f"Steam Deck template sync failed: no writable Steam input config root was found (tried: {tried})"
    )
