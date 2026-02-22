from __future__ import annotations

import re
import zlib
from pathlib import Path

import vdf

from .io import _atomic_write_bytes
from .types import (
    GAMEHUB_SYSTEM_PREFIX,
    GAMEHUB_TAG,
    GAMEHUB_TITLE_PREFIX,
    ShortcutSyncResult,
    SteamContext,
    SteamShortcutSpec,
)


def _normalize_shortcuts_tags(tags: object) -> list[str]:
    if isinstance(tags, dict):
        values = []
        for key in sorted(tags, key=lambda k: int(str(k)) if str(k).isdigit() else str(k)):
            value = tags[key]
            if isinstance(value, str):
                values.append(value)
        return values
    if isinstance(tags, list):
        return [item for item in tags if isinstance(item, str)]
    return []


def _tags_to_vdf_map(tags: list[str]) -> dict[str, str]:
    return {str(index): value for index, value in enumerate(tags)}


def _extract_tag_value(tags: list[str], prefix: str) -> str | None:
    for tag in tags:
        if tag.startswith(prefix):
            return tag[len(prefix) :]
    return None


def _normalize_launch_options(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _emulator_family(command: object) -> str:
    if not isinstance(command, str):
        return ""
    normalized = command.casefold()
    if "retroarch" in normalized:
        return "retroarch"
    if "pcsx2" in normalized:
        return "pcsx2"
    if "dolphin" in normalized:
        return "dolphin"
    if "azahar" in normalized:
        return "azahar"
    return ""


def _legacy_shortcut_matches(entry: dict, spec: SteamShortcutSpec) -> bool:
    app_name = entry.get("AppName")
    if not isinstance(app_name, str) or app_name.casefold() != spec.title_name.casefold():
        return False
    existing_family = _emulator_family(entry.get("Exe"))
    desired_family = _emulator_family(spec.exe)
    if existing_family and desired_family and existing_family == desired_family:
        return True

    existing_basenames = _extract_path_basenames(entry.get("LaunchOptions"))
    desired_basenames = _extract_path_basenames(spec.launch_options)
    if existing_basenames and desired_basenames and existing_basenames.intersection(desired_basenames):
        return True
    return False


def _extract_path_basenames(value: object) -> set[str]:
    if not isinstance(value, str):
        return set()

    def _basename_candidate(token: str) -> str | None:
        normalized = token.strip().strip('"').strip("'").replace("\\", "/")
        if not normalized or normalized == "@@":
            return None
        basename = normalized.rsplit("/", 1)[-1]
        if "." not in basename:
            return None
        return basename.casefold()

    basenames: set[str] = set()
    for token in re.findall(r'"([^"]+)"', value):
        candidate = _basename_candidate(token)
        if candidate:
            basenames.add(candidate)
    if basenames:
        return basenames
    for token in value.split():
        candidate = _basename_candidate(token)
        if candidate:
            basenames.add(candidate)
    return basenames


def _pop_legacy_match(entries: list[dict], spec: SteamShortcutSpec) -> dict | None:
    for index, entry in enumerate(entries):
        if _legacy_shortcut_matches(entry, spec):
            return entries.pop(index)
    return None


def _is_managed_shortcut(entry: dict) -> bool:
    tags = _normalize_shortcuts_tags(entry.get("tags"))
    return GAMEHUB_TAG in tags and _extract_tag_value(tags, GAMEHUB_TITLE_PREFIX) is not None


def _parse_shortcuts_table(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("rb") as handle:
        payload = vdf.binary_load(handle)
    table = payload.get("shortcuts", {}) if isinstance(payload, dict) else {}
    if not isinstance(table, dict):
        return []
    entries: list[dict] = []
    for key in sorted(table, key=lambda value: int(str(value)) if str(value).isdigit() else str(value)):
        raw = table[key]
        if isinstance(raw, dict):
            entries.append(dict(raw))
    return entries


def _encode_shortcuts(entries: list[dict]) -> bytes:
    payload = {"shortcuts": {str(index): entry for index, entry in enumerate(entries)}}
    return bytes(vdf.binary_dumps(payload))


def _compute_shortcut_app_id(exe: str, app_name: str) -> str:
    seed = f"{exe}{app_name}"
    value = zlib.crc32(seed.encode("utf-8")) & 0xFFFFFFFF
    return str(value | 0x80000000)


def _canonical_unsigned_app_id(app_id: str) -> str:
    text = str(app_id).strip()
    if not text:
        return text
    if not text.lstrip("-").isdigit():
        return text
    value = int(text)
    return str(value % (2**32))


def _canonical_signed_app_id_from_unsigned(unsigned_app_id: str) -> str | None:
    text = str(unsigned_app_id).strip()
    if not text or not text.isdigit():
        return None
    value = int(text)
    if value <= 0x7FFFFFFF:
        return None
    return str(value - (2**32))


def _extract_persisted_app_id(entry: dict) -> str | None:
    raw = entry.get("appid")
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.lstrip("-").isdigit():
        return text
    return None


def _build_shortcut_entry(spec: SteamShortcutSpec, existing: dict | None = None) -> dict:
    entry = dict(existing) if existing is not None else {}
    persisted_app_id = _extract_persisted_app_id(entry)
    if persisted_app_id is None:
        unsigned = _compute_shortcut_app_id(spec.exe, spec.title_name)
        persisted_app_id = _canonical_signed_app_id_from_unsigned(unsigned) or unsigned
    tags = [GAMEHUB_TAG, f"{GAMEHUB_TITLE_PREFIX}{spec.title_id}", f"{GAMEHUB_SYSTEM_PREFIX}{spec.system}", spec.system]
    entry.update(
        {
            "AppName": spec.title_name,
            "Exe": spec.exe,
            "StartDir": spec.start_dir,
            "icon": spec.icon_path,
            "ShortcutPath": "",
            "LaunchOptions": spec.launch_options,
            "IsHidden": "0",
            "AllowDesktopConfig": "1",
            "AllowOverlay": "1",
            "OpenVR": "0",
            "Devkit": "0",
            "DevkitGameID": "",
            "LastPlayTime": "0",
            "appid": persisted_app_id,
            "tags": _tags_to_vdf_map(tags),
        }
    )
    return entry


def upsert_shortcuts(context: SteamContext, desired_shortcuts: list[SteamShortcutSpec]) -> ShortcutSyncResult:
    existing_entries = _parse_shortcuts_table(context.shortcuts_path)
    unmanaged_entries: list[dict] = []
    managed_by_title: dict[str, dict] = {}
    for entry in existing_entries:
        if not _is_managed_shortcut(entry):
            unmanaged_entries.append(entry)
            continue
        title_id = _extract_tag_value(_normalize_shortcuts_tags(entry.get("tags")), GAMEHUB_TITLE_PREFIX)
        if title_id:
            managed_by_title[title_id] = entry

    remaining_unmanaged = list(unmanaged_entries)
    managed_entries: list[dict] = []
    for shortcut in desired_shortcuts:
        existing = managed_by_title.get(shortcut.title_id)
        if existing is None:
            existing = _pop_legacy_match(remaining_unmanaged, shortcut)
        managed_entries.append(_build_shortcut_entry(shortcut, existing))

    next_entries = [*remaining_unmanaged, *managed_entries]

    payload = _encode_shortcuts(next_entries)
    _atomic_write_bytes(context.shortcuts_path, payload)

    persisted = _parse_shortcuts_table(context.shortcuts_path)
    app_ids_by_title: dict[str, str] = {}
    app_ids_by_system: dict[str, set[str]] = {}
    for entry in persisted:
        if not _is_managed_shortcut(entry):
            continue
        tags = _normalize_shortcuts_tags(entry.get("tags"))
        title_id = _extract_tag_value(tags, GAMEHUB_TITLE_PREFIX)
        system_name = _extract_tag_value(tags, GAMEHUB_SYSTEM_PREFIX)
        if not title_id or not system_name:
            continue
        app_id = _extract_persisted_app_id(entry)
        if app_id is None:
            app_id = _compute_shortcut_app_id(str(entry.get("Exe", "")), str(entry.get("AppName", "")))
        app_ids_by_title[title_id] = app_id
        app_ids_by_system.setdefault(system_name, set()).add(app_id)

    sorted_system_map = {system: sorted(app_ids_by_system[system], key=int) for system in sorted(app_ids_by_system)}
    return ShortcutSyncResult(
        app_ids_by_title=app_ids_by_title,
        app_ids_by_system=sorted_system_map,
        total_shortcuts=len(persisted),
    )
