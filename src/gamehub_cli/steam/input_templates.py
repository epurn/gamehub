from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from gamehub_common.models import LibraryIndex

from .io import _atomic_write_bytes
from .types import ShortcutSyncResult, SteamContext

_DECK_TEMPLATE_FILENAME = "controller_neptune.vdf"
_DECK_TEMPLATE_SYSTEM_ORDER = ("Wii", "GC", "N3DS")
_DECK_TEMPLATE_SEED_ROOT = Path(__file__).resolve().parent / "template_seeds" / "steamdeck"
_DECK_TEMPLATE_SEED_BY_SYSTEM = {
    "Wii": _DECK_TEMPLATE_SEED_ROOT / "wii_gc" / _DECK_TEMPLATE_FILENAME,
    "GC": _DECK_TEMPLATE_SEED_ROOT / "wii_gc" / _DECK_TEMPLATE_FILENAME,
    "N3DS": _DECK_TEMPLATE_SEED_ROOT / "n3ds" / _DECK_TEMPLATE_FILENAME,
}
_WHITESPACE_RE = re.compile(r"\s+")

_PathIdentity: TypeAlias = tuple[str, int, int] | tuple[str, str]


@dataclass(frozen=True)
class TemplateSyncResult:
    targets: int
    written: int
    unchanged: int
    errors: int
    systems_applied: tuple[str, ...]


def normalize_steam_input_title_dir(title_name: str) -> str:
    normalized = title_name.casefold().strip().replace("/", " ").replace("\\", " ")
    normalized = _WHITESPACE_RE.sub(" ", normalized).strip()
    return normalized or "untitled"


def discover_deck_steam_input_roots(steam_id: str) -> list[Path]:
    home = Path.home()
    candidates = [
        home
        / ".local"
        / "share"
        / "Steam"
        / "steamapps"
        / "common"
        / "Steam Controller Configs"
        / steam_id
        / "config",
        home
        / ".steam"
        / "steam"
        / "steamapps"
        / "common"
        / "Steam Controller Configs"
        / steam_id
        / "config",
        home
        / ".steam"
        / "root"
        / "steamapps"
        / "common"
        / "Steam Controller Configs"
        / steam_id
        / "config",
    ]
    unique: list[Path] = []
    seen: set[_PathIdentity] = set()
    for candidate in candidates:
        identity = _path_identity(candidate)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(candidate)
    return unique


def _path_identity(path: Path) -> _PathIdentity:
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        resolved = path
    try:
        stat = resolved.stat()
    except OSError:
        return ("path", str(resolved).casefold())
    return ("inode", int(stat.st_dev), int(stat.st_ino))


def _resolve_deck_steam_input_root(steam_id: str, *, strict: bool) -> Path | None:
    candidates = discover_deck_steam_input_roots(steam_id)
    existing = [candidate for candidate in candidates if candidate.exists()]
    writable = [candidate for candidate in existing if candidate.is_dir() and os.access(candidate, os.W_OK)]
    if writable:
        return writable[0]

    if strict:
        tried = ", ".join(str(path) for path in candidates) or "<none>"
        raise RuntimeError(
            "Steam Deck template sync strict mode: no writable Steam Controller Configs root was found "
            f"(tried: {tried})"
        )

    if not candidates:
        return None
    target = candidates[0]
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return target if os.access(target, os.W_OK) else None


def _seed_path_for_system(system_name: str) -> Path | None:
    return _DECK_TEMPLATE_SEED_BY_SYSTEM.get(system_name)


def _load_seed_payloads(required_systems: list[str], *, strict: bool) -> tuple[dict[str, bytes], int]:
    payloads: dict[str, bytes] = {}
    errors = 0
    for system_name in required_systems:
        seed_path = _seed_path_for_system(system_name)
        if seed_path is None:
            if strict:
                raise RuntimeError(f"Steam Deck template sync strict mode: no seed mapping for system '{system_name}'")
            errors += 1
            continue
        if not seed_path.exists():
            if strict:
                raise RuntimeError(
                    f"Steam Deck template sync strict mode: missing template seed for {system_name} ({seed_path})"
                )
            errors += 1
            continue
        try:
            payloads[system_name] = seed_path.read_bytes()
        except OSError as exc:
            if strict:
                raise RuntimeError(
                    f"Steam Deck template sync strict mode: failed reading seed for {system_name} ({seed_path}): {exc}"
                ) from exc
            errors += 1
    return payloads, errors


def apply_deck_steam_input_templates(
    context: SteamContext,
    index: LibraryIndex,
    shortcut_result: ShortcutSyncResult,
    *,
    strict: bool,
) -> TemplateSyncResult:
    managed_title_ids = set(shortcut_result.app_ids_by_title)
    if not managed_title_ids:
        return TemplateSyncResult(targets=0, written=0, unchanged=0, errors=0, systems_applied=())

    managed_titles = [
        title
        for title in sorted(index.titles, key=lambda item: (item.system, item.title_name.casefold(), item.title_id))
        if title.title_id in managed_title_ids and title.system in _DECK_TEMPLATE_SEED_BY_SYSTEM
    ]
    if not managed_titles:
        return TemplateSyncResult(targets=0, written=0, unchanged=0, errors=0, systems_applied=())

    required_systems = [
        system_name for system_name in _DECK_TEMPLATE_SYSTEM_ORDER if any(t.system == system_name for t in managed_titles)
    ]
    seed_payloads, errors = _load_seed_payloads(required_systems, strict=strict)
    applied_systems = tuple(system_name for system_name in required_systems if system_name in seed_payloads)
    if not seed_payloads:
        return TemplateSyncResult(targets=0, written=0, unchanged=0, errors=errors, systems_applied=applied_systems)

    root = _resolve_deck_steam_input_root(context.steam_id, strict=strict)
    if root is None:
        return TemplateSyncResult(targets=0, written=0, unchanged=0, errors=errors + 1, systems_applied=applied_systems)

    targets = 0
    written = 0
    unchanged = 0

    for title in managed_titles:
        payload = seed_payloads.get(title.system)
        if payload is None:
            continue
        target_path = root / normalize_steam_input_title_dir(title.title_name) / _DECK_TEMPLATE_FILENAME
        targets += 1
        try:
            if target_path.exists() and target_path.read_bytes() == payload:
                unchanged += 1
                continue
            _atomic_write_bytes(target_path, payload)
            written += 1
        except OSError as exc:
            if strict:
                raise RuntimeError(
                    "Steam Deck template sync strict mode: failed writing template file "
                    f"for title '{title.title_name}' ({target_path}): {exc}"
                ) from exc
            errors += 1

    return TemplateSyncResult(
        targets=targets,
        written=written,
        unchanged=unchanged,
        errors=errors,
        systems_applied=applied_systems,
    )
