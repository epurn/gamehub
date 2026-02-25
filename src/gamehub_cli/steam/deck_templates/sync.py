from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gamehub_common.models import LibraryIndex

from ..io import _atomic_write_bytes
from ..shortcuts import _canonical_unsigned_app_id
from ..types import ShortcutSyncResult, SteamContext
from .configset import sync_deck_template_selection_configsets
from .roots import normalize_steam_input_title_dir, path_identity, resolve_deck_steam_input_roots
from .seeds import (
    DECK_TEMPLATE_SEED_BY_SYSTEM,
    DECK_TEMPLATE_SYSTEM_ORDER,
    load_seed_payloads,
    template_filenames_for_system,
)

_STEAM_INPUT_ROOT_MARKER = ("steamapps", "common", "steam controller configs")


@dataclass(frozen=True)
class TemplateSyncResult:
    targets: int
    written: int
    unchanged: int
    systems_applied: tuple[str, ...]


def _steam_root_for_deck_template_root(root: Path) -> Path | None:
    parts = list(root.parts)
    folded = [part.casefold() for part in parts]
    marker_len = len(_STEAM_INPUT_ROOT_MARKER)
    for index in range(len(parts) - marker_len + 1):
        if tuple(folded[index : index + marker_len]) != _STEAM_INPUT_ROOT_MARKER:
            continue
        if index == 0:
            return None
        return Path(*parts[:index])
    return None


def _local_override_roots_for_template_roots(roots: list[Path]) -> tuple[Path, ...]:
    unique_roots: list[Path] = []
    seen: set[tuple[str, int, int] | tuple[str, str]] = set()
    for root in roots:
        steam_root = _steam_root_for_deck_template_root(root)
        if steam_root is None:
            continue
        override_root = steam_root / "controller_config"
        identity = path_identity(override_root)
        if identity in seen:
            continue
        seen.add(identity)
        unique_roots.append(override_root)
    return tuple(unique_roots)


def apply_deck_steam_input_templates(
    context: SteamContext,
    index: LibraryIndex,
    shortcut_result: ShortcutSyncResult,
    *,
    overwrite_existing: bool = False,
) -> TemplateSyncResult:
    managed_title_ids = set(shortcut_result.app_ids_by_title)
    if not managed_title_ids:
        return TemplateSyncResult(targets=0, written=0, unchanged=0, systems_applied=())

    candidate_titles = [
        title
        for title in sorted(index.titles, key=lambda item: (item.system, item.title_name.casefold(), item.title_id))
        if title.title_id in managed_title_ids
    ]
    managed_titles = [title for title in candidate_titles if title.system in DECK_TEMPLATE_SEED_BY_SYSTEM]
    if not managed_titles:
        return TemplateSyncResult(targets=0, written=0, unchanged=0, systems_applied=())

    required_systems = [
        system_name
        for system_name in DECK_TEMPLATE_SYSTEM_ORDER
        if any(title.system == system_name for title in managed_titles)
    ]
    seed_payloads = load_seed_payloads(required_systems)
    applied_systems = tuple(system_name for system_name in required_systems if system_name in seed_payloads)

    roots = resolve_deck_steam_input_roots(context)
    override_roots = _local_override_roots_for_template_roots(roots)

    targets = 0
    written = 0
    unchanged = 0

    for title in managed_titles:
        payload = seed_payloads.get(title.system)
        if payload is None:
            continue
        filenames = template_filenames_for_system(title.system)
        targets += 1
        title_changed = False
        app_id = shortcut_result.app_ids_by_title.get(title.title_id)
        for root in roots:
            title_dir = root / normalize_steam_input_title_dir(title.title_name)
            for filename in filenames:
                target_path = title_dir / filename
                if target_path.exists():
                    if not overwrite_existing:
                        continue
                _atomic_write_bytes(target_path, payload)
                title_changed = True
        if app_id is not None:
            unsigned_app_id = _canonical_unsigned_app_id(str(app_id).strip())
            if unsigned_app_id and unsigned_app_id.isdigit():
                override_filename = f"app_{unsigned_app_id}.vdf"
                for override_root in override_roots:
                    override_path = override_root / override_filename
                    if override_path.exists():
                        if not overwrite_existing:
                            continue
                    _atomic_write_bytes(override_path, payload)
                    title_changed = True
        if title_changed:
            written += 1
        else:
            unchanged += 1

    for root in roots:
        sync_deck_template_selection_configsets(
            root=root,
            managed_titles=managed_titles,
            shortcut_result=shortcut_result,
        )

    return TemplateSyncResult(
        targets=targets,
        written=written,
        unchanged=unchanged,
        systems_applied=applied_systems,
    )
