from __future__ import annotations

import json
import time
from pathlib import Path

import vdf

from .io import _atomic_write_text
from .shortcuts import _canonical_unsigned_app_id
from .types import DEFAULT_USER_COLLECTIONS_PATH, USER_COLLECTIONS_KEY, SteamContext


def _find_key_path(payload: object, target: str, path: list[str] | None = None) -> list[str] | None:
    if path is None:
        path = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key) == target:
                return [*path, str(key)]
            found = _find_key_path(value, target, [*path, str(key)])
            if found:
                return found
    return None


def _resolve_path(payload: dict, keys: list[str]) -> object:
    current: object = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _set_path(payload: dict, keys: list[str], value: object) -> None:
    current: dict = payload
    for key in keys[:-1]:
        next_value = current.get(key)
        if not isinstance(next_value, dict):
            next_value = {}
            current[key] = next_value
        current = next_value
    current[keys[-1]] = value


def _decode_user_collections(raw: object) -> tuple[list[object], str, dict[str, object]]:
    """
    Decode user collections from dict/list/string variants.

    Returns: (collections, style, metadata_dict)
    style: "dict" (default Steam style) or "list" (legacy/alternate style)
    """
    if isinstance(raw, dict):
        metadata = dict(raw)
        collections_obj = metadata.get("collections")
        collections = list(collections_obj) if isinstance(collections_obj, list) else []
        return collections, "dict", metadata
    if isinstance(raw, list):
        return list(raw), "list", {}
    if not isinstance(raw, str) or not raw.strip():
        return [], "dict", {}

    candidates = [raw]
    if raw.startswith('"') and raw.endswith('"'):
        candidates.append(raw[1:-1])
    candidates.append(raw.replace('\\"', '"'))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            return list(parsed), "list", {}
        if isinstance(parsed, dict):
            metadata = dict(parsed)
            collections_obj = metadata.get("collections")
            collections = list(collections_obj) if isinstance(collections_obj, list) else []
            return collections, "dict", metadata
    return [], "dict", {}


def _load_localconfig(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        parsed = vdf.loads(text)
    except Exception:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _dump_localconfig(payload: dict) -> str:
    return str(vdf.dumps(payload, pretty=True))


def _collection_id_for_system(system_name: str) -> str:
    sanitized = "".join(ch.lower() if ch.isalnum() else "-" for ch in system_name).strip("-")
    return f"gamehub-{sanitized or 'system'}"


def _to_int_if_numeric(value: str) -> int | str:
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    return text


def _load_cloudstorage_entries(path: Path) -> list[list[object]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    entries: list[list[object]] = []
    for item in payload:
        if not isinstance(item, list) or len(item) != 2:
            continue
        key = item[0]
        value = item[1]
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        entries.append([key, dict(value)])
    return entries


def _write_cloudstorage_entries(path: Path, entries: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(entries, separators=(",", ":"))
    _atomic_write_text(path, payload)


def _next_cloudstorage_version(entries: list[list[object]]) -> int:
    max_version = 0
    for _key, value in entries:
        if not isinstance(value, dict):
            continue
        raw = value.get("version")
        if raw is None:
            continue
        text = str(raw).strip()
        if text.isdigit():
            max_version = max(max_version, int(text))
    return max_version + 1


def update_cloud_collections(context: SteamContext, app_ids_by_system: dict[str, list[str]]) -> int:
    if context.cloudstorage_path is None:
        return 0
    entries = _load_cloudstorage_entries(context.cloudstorage_path)
    entry_by_key: dict[str, list[object]] = {}
    for pair in entries:
        key = pair[0]
        if isinstance(key, str):
            entry_by_key[key] = pair

    now = int(time.time())
    next_version = _next_cloudstorage_version(entries)
    updates = 0
    desired_keys: set[str] = set()

    for system_name in sorted(app_ids_by_system):
        collection_id = _collection_id_for_system(system_name)
        key = f"user-collections.{collection_id}"
        desired_keys.add(key)
        desired_value = {
            "id": collection_id,
            "name": system_name,
            "added": [
                _to_int_if_numeric(_canonical_unsigned_app_id(str(app_id))) for app_id in app_ids_by_system[system_name]
            ],
            "removed": [],
        }
        desired_json = json.dumps(desired_value, separators=(",", ":"), sort_keys=True)

        existing_pair = entry_by_key.get(key)
        current_payload: dict[str, object] | None = None
        if existing_pair is not None and isinstance(existing_pair[1], dict):
            current_payload = existing_pair[1]
        if (
            current_payload
            and current_payload.get("is_deleted") is not True
            and current_payload.get("value") == desired_json
        ):
            continue

        payload = {
            "key": key,
            "timestamp": now,
            "value": desired_json,
            "version": str(next_version),
        }
        next_version += 1
        if existing_pair is None:
            entries.append([key, payload])
            entry_by_key[key] = entries[-1]
        else:
            existing_pair[1] = payload
        updates += 1

    # Mark stale GAMEHUB-managed cloud collections as deleted.
    for key, pair in list(entry_by_key.items()):
        if not key.startswith("user-collections.gamehub-"):
            continue
        if key in desired_keys:
            continue
        value = pair[1]
        if not isinstance(value, dict):
            continue
        if value.get("is_deleted") is True:
            continue
        pair[1] = {
            "key": key,
            "timestamp": now,
            "is_deleted": True,
            "version": str(next_version),
        }
        next_version += 1
        updates += 1

    if updates > 0:
        _write_cloudstorage_entries(context.cloudstorage_path, entries)
    return updates


def update_collections(context: SteamContext, app_ids_by_system: dict[str, list[str]]) -> int:
    payload = _load_localconfig(context.localconfig_path)
    before_dump = _dump_localconfig(payload)
    structure_changed = False
    user_collections_path = _find_key_path(payload, USER_COLLECTIONS_KEY)
    canonical_path = list(DEFAULT_USER_COLLECTIONS_PATH)
    canonical_raw = _resolve_path(payload, canonical_path)
    if canonical_raw is not None:
        user_collections_path = canonical_path
    elif user_collections_path is None:
        user_collections_path = canonical_path
        _set_path(
            payload, user_collections_path, json.dumps({"collections": []}, separators=(",", ":"), sort_keys=True)
        )
        structure_changed = True
    elif user_collections_path == ["UserLocalConfigStore", USER_COLLECTIONS_KEY]:
        # Migrate legacy GAMEHUB location to Steam's nested WebStorage path.
        legacy_raw = _resolve_path(payload, user_collections_path)
        _set_path(
            payload,
            canonical_path,
            legacy_raw
            if legacy_raw is not None
            else json.dumps({"collections": []}, separators=(",", ":"), sort_keys=True),
        )
        user_collections_path = canonical_path
        structure_changed = True

    raw = _resolve_path(payload, user_collections_path)
    existing_collections, style, metadata = _decode_user_collections(raw)

    managed_names = set(app_ids_by_system)
    next_collections: list[object] = []
    managed_seen: set[str] = set()
    updates = 0
    for entry in existing_collections:
        if not isinstance(entry, dict):
            next_collections.append(entry)
            continue
        name = entry.get("name")
        is_managed = bool(entry.get("gamehub_managed"))
        if not isinstance(name, str) or not is_managed:
            next_collections.append(entry)
            continue
        if name not in managed_names:
            updates += 1
            continue
        managed_seen.add(name)
        updated = dict(entry)
        desired = sorted(
            {_to_int_if_numeric(_canonical_unsigned_app_id(str(app_id))) for app_id in app_ids_by_system[name]},
            key=lambda item: int(item) if isinstance(item, (int, str)) and str(item).isdigit() else str(item),
        )
        if updated.get("added") != desired:
            updated["added"] = desired
            updates += 1
        updated["removed"] = []
        updated["name"] = name
        updated["gamehub_managed"] = True
        next_collections.append(updated)

    for system_name in sorted(managed_names):
        if system_name in managed_seen:
            continue
        desired = sorted(
            {_to_int_if_numeric(_canonical_unsigned_app_id(str(app_id))) for app_id in app_ids_by_system[system_name]},
            key=lambda item: int(item) if isinstance(item, (int, str)) and str(item).isdigit() else str(item),
        )
        next_collections.append(
            {
                "name": system_name,
                "added": desired,
                "removed": [],
                "gamehub_managed": True,
            }
        )
        updates += 1

    if updates == 0 and not structure_changed:
        return 0

    if style == "list":
        serialized_target: object = next_collections
    else:
        next_metadata = dict(metadata)
        next_metadata["collections"] = next_collections
        serialized_target = next_metadata
    serialized = json.dumps(serialized_target, separators=(",", ":"), sort_keys=True)
    _set_path(payload, user_collections_path, serialized)
    after_dump = _dump_localconfig(payload)
    if after_dump == before_dump:
        return updates
    _atomic_write_text(context.localconfig_path, after_dump)
    return updates
