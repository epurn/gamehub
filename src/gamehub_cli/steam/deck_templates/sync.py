from __future__ import annotations

from dataclasses import dataclass

from gamehub_common.models import LibraryIndex

from ..io import _atomic_write_bytes
from ..shortcuts import _canonical_unsigned_app_id
from ..types import ShortcutSyncResult, SteamContext
from .configset import sync_deck_template_selection_configsets
from .roots import normalize_steam_input_title_dir, resolve_deck_steam_input_roots
from .seeds import (
    DECK_TEMPLATE_SEED_BY_SYSTEM,
    DECK_TEMPLATE_SYSTEM_ORDER,
    load_seed_payloads,
    template_filenames_for_system,
)


@dataclass(frozen=True)
class TemplateSyncResult:
    targets: int
    written: int
    unchanged: int
    systems_applied: tuple[str, ...]


def _template_dir_keys_for_title(*, title_name: str, app_id: str | None) -> tuple[str, ...]:
    keys: list[str] = []
    normalized_title = normalize_steam_input_title_dir(title_name)
    if normalized_title:
        keys.append(normalized_title)
    if app_id is not None:
        unsigned_app_id = _canonical_unsigned_app_id(str(app_id).strip())
        if unsigned_app_id and unsigned_app_id.isdigit() and unsigned_app_id not in keys:
            keys.append(unsigned_app_id)
    return tuple(keys)


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
        template_dir_keys = _template_dir_keys_for_title(title_name=title.title_name, app_id=app_id)
        for root in roots:
            for dir_key in template_dir_keys:
                title_dir = root / dir_key
                for filename in filenames:
                    target_path = title_dir / filename
                    if target_path.exists():
                        if not overwrite_existing:
                            continue
                    _atomic_write_bytes(target_path, payload)
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
