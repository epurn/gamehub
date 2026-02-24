from __future__ import annotations

from pathlib import Path

import vdf

from gamehub_common.models import TitleEntry

from ..io import _atomic_write_text
from ..shortcuts import _canonical_unsigned_app_id
from ..types import ShortcutSyncResult
from .roots import normalize_steam_input_title_dir, path_identity
from .seeds import template_selection_name_for_system

_DECK_TEMPLATE_CONFIGSET_FILENAME = "configset_controller_neptune.vdf"
_DECK_TEMPLATE_CONFIGSET_GLOB = "configset_*.vdf"


def template_reference_for_title(title: TitleEntry) -> str:
    selection_name = template_selection_name_for_system(title.system)
    title_key = normalize_steam_input_title_dir(title.title_name)
    return f"CLOUD_{title_key}/{selection_name}"


def _forced_controller_config_entry(*, title: TitleEntry) -> dict[str, str]:
    return {"template": template_reference_for_title(title)}


def _canonical_signed_app_id(app_id: str) -> str | None:
    text = str(app_id).strip()
    if not text or not text.lstrip("-").isdigit():
        return None
    unsigned = int(_canonical_unsigned_app_id(text))
    if unsigned <= 0x7FFFFFFF:
        return None
    return str(unsigned - (2**32))


def _configset_key_sort_key(value: str) -> tuple[int, int | str]:
    text = str(value).strip()
    if text.lstrip("-").isdigit():
        return (0, int(text))
    return (1, text.casefold())


def _configset_entry_keys(title_name: str, app_id: str | None) -> tuple[str, ...]:
    keys: set[str] = set()
    raw_title = str(title_name).strip()
    if raw_title:
        keys.add(raw_title)
        keys.add(normalize_steam_input_title_dir(raw_title))
    if app_id is not None:
        raw_app_id = str(app_id).strip()
        if raw_app_id:
            keys.add(raw_app_id)
            unsigned_app_id = _canonical_unsigned_app_id(raw_app_id)
            if unsigned_app_id:
                keys.add(unsigned_app_id)
                signed_app_id = _canonical_signed_app_id(unsigned_app_id)
                if signed_app_id:
                    keys.add(signed_app_id)
    return tuple(sorted(keys, key=_configset_key_sort_key))


def sync_deck_template_selection_configset(
    *,
    configset_path: Path,
    managed_titles: list[TitleEntry],
    shortcut_result: ShortcutSyncResult,
) -> None:
    try:
        if configset_path.exists():
            payload_raw = vdf.loads(configset_path.read_text(encoding="utf-8"))
            payload = dict(payload_raw) if isinstance(payload_raw, dict) else {}
        else:
            payload = {}
    except (OSError, Exception) as exc:
        raise RuntimeError(
            f"Steam Deck template sync failed: failed loading template configset ({configset_path}): {exc}"
        ) from exc

    changed = False
    controller_config = payload.get("controller_config")
    if not isinstance(controller_config, dict):
        controller_config = {}
        payload["controller_config"] = controller_config
        changed = True

    for title in managed_titles:
        app_id = shortcut_result.app_ids_by_title.get(title.title_id)
        title_keys = set(_configset_entry_keys(title.title_name, app_id))
        for key in title_keys:
            forced_entry = _forced_controller_config_entry(title=title)
            existing_entry = controller_config.get(key)
            if not isinstance(existing_entry, dict) or existing_entry != forced_entry:
                controller_config[key] = dict(forced_entry)
                changed = True
        normalized_title = normalize_steam_input_title_dir(title.title_name)
        for existing_key in list(controller_config):
            if not isinstance(existing_key, str):
                continue
            if existing_key in title_keys:
                continue
            if normalize_steam_input_title_dir(existing_key) != normalized_title:
                continue
            del controller_config[existing_key]
            changed = True

    if not changed:
        return
    try:
        _atomic_write_text(configset_path, str(vdf.dumps(payload, pretty=True)))
    except OSError as exc:
        raise RuntimeError(
            f"Steam Deck template sync failed: failed writing template configset ({configset_path}): {exc}"
        ) from exc


def _iter_target_configset_paths(root: Path) -> list[Path]:
    required = root / _DECK_TEMPLATE_CONFIGSET_FILENAME
    paths: list[Path] = [required]
    for candidate in sorted(root.glob(_DECK_TEMPLATE_CONFIGSET_GLOB), key=lambda p: p.name.casefold()):
        if not candidate.is_file():
            continue
        name = candidate.name.casefold()
        if name == _DECK_TEMPLATE_CONFIGSET_FILENAME:
            continue
        if name == "configset_awaiting_logon.vdf":
            continue
        paths.append(candidate)
    unique: list[Path] = []
    seen: set[tuple[str, int, int] | tuple[str, str]] = set()
    for path in paths:
        identity = path_identity(path)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(path)
    return unique


def sync_deck_template_selection_configsets(
    *,
    root: Path,
    managed_titles: list[TitleEntry],
    shortcut_result: ShortcutSyncResult,
) -> None:
    for configset_path in _iter_target_configset_paths(root):
        sync_deck_template_selection_configset(
            configset_path=configset_path,
            managed_titles=managed_titles,
            shortcut_result=shortcut_result,
        )
