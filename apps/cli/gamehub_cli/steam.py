from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import zlib

import vdf

from .fsops import replace_file


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


def _run_process_best_effort(command: list[str], timeout_seconds: int = 10) -> None:
    try:
        subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return


def _candidate_userdata_dirs() -> list[Path]:
    candidates: list[Path] = []
    if os.name == "nt":
        pf86 = os.environ.get("PROGRAMFILES(X86)")
        pf = os.environ.get("PROGRAMFILES")
        if pf86:
            candidates.append(Path(pf86) / "Steam" / "userdata")
        if pf:
            candidates.append(Path(pf) / "Steam" / "userdata")
    home = Path.home()
    candidates.append(home / ".steam" / "steam" / "userdata")
    candidates.append(home / ".local" / "share" / "Steam" / "userdata")
    candidates.append(home / ".var" / "app" / "com.valvesoftware.Steam" / ".steam" / "steam" / "userdata")
    candidates.append(home / ".var" / "app" / "com.valvesoftware.Steam" / "data" / "Steam" / "userdata")
    return candidates


def steam_id64_from_userdata_id(userdata_id: str) -> str | None:
    if not userdata_id.isdigit():
        return None
    value = int(userdata_id)
    if value >= STEAM_ID64_BASE:
        return str(value)
    return str(value + STEAM_ID64_BASE)


def _preferred_steam_id_candidates(preferred_steam_id: str) -> list[str]:
    if not preferred_steam_id.isdigit():
        return []
    value = int(preferred_steam_id)
    values = [str(value)]
    if value >= STEAM_ID64_BASE:
        account_id = value - STEAM_ID64_BASE
        if account_id > 0:
            values.append(str(account_id))
    else:
        values.append(str(value + STEAM_ID64_BASE))
    unique: list[str] = []
    seen: set[str] = set()
    for item in values:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def discover_userdata_dir(explicit: Path | None) -> Path | None:
    env_override = os.environ.get("GAMEHUB_STEAM_USERDATA_DIR")
    if env_override:
        candidate = Path(env_override).expanduser()
        if candidate.exists():
            return candidate
        return None
    if explicit is not None:
        if explicit.exists():
            return explicit
        return None
    for candidate in _candidate_userdata_dirs():
        if candidate.exists():
            return candidate
    return None


def discover_steam_id(userdata_dir: Path, preferred_steam_id: str | None = None) -> str | None:
    if preferred_steam_id is not None:
        if not preferred_steam_id.isdigit():
            raise ValueError(f"Configured steam_id is not numeric: {preferred_steam_id}")
        candidates = _preferred_steam_id_candidates(preferred_steam_id)
        for candidate in candidates:
            target = userdata_dir / candidate
            if target.exists() and target.is_dir():
                return candidate
        raise ValueError(
            "Configured steam_id was not found in userdata: "
            f"{preferred_steam_id} (tried: {', '.join(candidates)})"
        )
    numeric_dirs = [item for item in userdata_dir.iterdir() if item.is_dir() and item.name.isdigit()]
    if not numeric_dirs:
        return None
    if len(numeric_dirs) == 1:
        return numeric_dirs[0].name

    def _profile_score(profile_dir: Path) -> float:
        config_dir = profile_dir / "config"
        candidates = [
            config_dir / "localconfig.vdf",
            config_dir / "shortcuts.vdf",
            profile_dir,
        ]
        newest = 0.0
        for candidate in candidates:
            try:
                newest = max(newest, candidate.stat().st_mtime)
            except FileNotFoundError:
                continue
        return newest

    ranked = sorted(numeric_dirs, key=lambda item: (-_profile_score(item), item.name))
    return ranked[0].name


def build_context(userdata_dir: Path, steam_id: str, steam_exe: Path | None) -> SteamContext:
    config_dir = userdata_dir / steam_id / "config"
    cloudstorage_path = config_dir / "cloudstorage" / "cloud-storage-namespace-1.json"
    return SteamContext(
        userdata_dir=userdata_dir,
        steam_id=steam_id,
        shortcuts_path=config_dir / "shortcuts.vdf",
        localconfig_path=config_dir / "localconfig.vdf",
        steam_exe=steam_exe,
        cloudstorage_path=cloudstorage_path,
    )


def is_steam_running() -> bool:
    if os.name == "nt":
        completed = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq steam.exe"],
            check=False,
            capture_output=True,
            text=True,
        )
        return "steam.exe" in completed.stdout.lower()
    completed = subprocess.run(["pgrep", "-f", "steam"], check=False, capture_output=True, text=True)
    return completed.returncode == 0


def close_steam_best_effort() -> None:
    if os.name == "nt":
        # First attempt graceful close; then force kill as fallback.
        _run_process_best_effort(["taskkill", "/IM", "steam.exe", "/T"])
        _run_process_best_effort(["taskkill", "/F", "/IM", "steam.exe", "/T"])
        return
    _run_process_best_effort(["pkill", "-f", "steam"])
    _run_process_best_effort(["pkill", "-9", "-f", "steam"])


def wait_for_steam_exit(timeout_seconds: int = 20) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not is_steam_running():
            return True
        time.sleep(0.5)
    return not is_steam_running()


def backup_steam_configs(context: SteamContext) -> list[Path]:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backups: list[Path] = []
    sources: list[Path] = [context.shortcuts_path, context.localconfig_path]
    if context.cloudstorage_path is not None:
        sources.append(context.cloudstorage_path)
    for source in sources:
        if not source.exists():
            continue
        destination = source.with_name(f"{source.name}.{timestamp}.bak")
        shutil.copy2(source, destination)
        backups.append(destination)
    return backups


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.tmp")
    with tmp.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    replace_file(tmp, path)


def _atomic_write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    replace_file(tmp, path)


def _unlink_best_effort(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except PermissionError:
        try:
            os.chmod(path, 0o666)
            path.unlink()
            return True
        except OSError:
            return False
    except OSError:
        return False


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
    return ""


def _legacy_shortcut_matches(entry: dict, spec: SteamShortcutSpec) -> bool:
    app_name = entry.get("AppName")
    if not isinstance(app_name, str) or app_name.casefold() != spec.title_name.casefold():
        return False
    existing_family = _emulator_family(entry.get("Exe"))
    desired_family = _emulator_family(spec.exe)
    if not existing_family or not desired_family:
        return False
    return existing_family == desired_family


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
    return vdf.binary_dumps(payload)


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
        collections = metadata.get("collections")
        if not isinstance(collections, list):
            collections = []
        return list(collections), "dict", metadata
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
            collections = metadata.get("collections")
            if not isinstance(collections, list):
                collections = []
            return list(collections), "dict", metadata
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
    return vdf.dumps(payload, pretty=True)


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
            "added": [_to_int_if_numeric(_canonical_unsigned_app_id(str(app_id))) for app_id in app_ids_by_system[system_name]],
            "removed": [],
        }
        desired_json = json.dumps(desired_value, separators=(",", ":"), sort_keys=True)

        pair = entry_by_key.get(key)
        current_payload: dict[str, object] | None = None
        if pair is not None and isinstance(pair[1], dict):
            current_payload = pair[1]
        if current_payload and current_payload.get("is_deleted") is not True and current_payload.get("value") == desired_json:
            continue

        payload = {
            "key": key,
            "timestamp": now,
            "value": desired_json,
            "version": str(next_version),
        }
        next_version += 1
        if pair is None:
            entries.append([key, payload])
            entry_by_key[key] = entries[-1]
        else:
            pair[1] = payload
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
    user_collections_path = _find_key_path(payload, USER_COLLECTIONS_KEY)
    canonical_path = list(DEFAULT_USER_COLLECTIONS_PATH)
    canonical_raw = _resolve_path(payload, canonical_path)
    if canonical_raw is not None:
        user_collections_path = canonical_path
    elif user_collections_path is None:
        user_collections_path = canonical_path
        _set_path(payload, user_collections_path, json.dumps({"collections": []}, separators=(",", ":"), sort_keys=True))
    elif user_collections_path == ["UserLocalConfigStore", USER_COLLECTIONS_KEY]:
        # Migrate legacy GAMEHUB location to Steam's nested WebStorage path.
        legacy_raw = _resolve_path(payload, user_collections_path)
        _set_path(
            payload,
            canonical_path,
            legacy_raw if legacy_raw is not None else json.dumps({"collections": []}, separators=(",", ":"), sort_keys=True),
        )
        user_collections_path = canonical_path

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
        desired = sorted({_canonical_unsigned_app_id(str(app_id)) for app_id in app_ids_by_system[name]}, key=int)
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
            {_canonical_unsigned_app_id(str(app_id)) for app_id in app_ids_by_system[system_name]},
            key=int,
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

    if style == "list":
        serialized_target: object = next_collections
    else:
        next_metadata = dict(metadata)
        next_metadata["collections"] = next_collections
        serialized_target = next_metadata
    serialized = json.dumps(serialized_target, separators=(",", ":"), sort_keys=True)
    _set_path(payload, user_collections_path, serialized)
    _atomic_write_text(context.localconfig_path, _dump_localconfig(payload))
    return updates


def copy_grid_art(context: SteamContext, assignments: list[SteamArtworkAssignment]) -> list[Path]:
    copied_files: list[Path] = []
    if not assignments:
        return copied_files

    grid_dir = context.userdata_dir / context.steam_id / "config" / "grid"
    grid_dir.mkdir(parents=True, exist_ok=True)
    suffixes_by_kind = {
        # Write both portrait and landscape variants for grid artwork.
        "grid": ("p", ""),
        "hero": "_hero",
        "logo": "_logo",
        "icon": "_icon",
    }

    for assignment in assignments:
        app_id = _canonical_unsigned_app_id(assignment.steam_app_id)
        if not app_id:
            continue
        for kind, source in assignment.assets_by_kind.items():
            if kind not in suffixes_by_kind:
                continue
            if not source.exists():
                continue
            raw_suffixes = suffixes_by_kind[kind]
            suffixes = raw_suffixes if isinstance(raw_suffixes, tuple) else (raw_suffixes,)
            for suffix in suffixes:
                destination = grid_dir / f"{app_id}{suffix}{source.suffix.lower() or '.png'}"
                shutil.copy2(source, destination)
                copied_files.append(destination)
    return copied_files


def prune_grid_noncanonical_variants(context: SteamContext, steam_app_ids: list[str]) -> int:
    grid_dir = context.userdata_dir / context.steam_id / "config" / "grid"
    if not grid_dir.exists():
        return 0

    removed = 0
    suffixes = ("p", "", "_hero", "_logo", "_icon")
    extensions = (".png", ".jpg", ".jpeg", ".ico", ".webp")
    for app_id in steam_app_ids:
        canonical_unsigned = _canonical_unsigned_app_id(app_id)
        legacy_signed = _canonical_signed_app_id_from_unsigned(canonical_unsigned)
        if not legacy_signed:
            continue
        for suffix in suffixes:
            for extension in extensions:
                canonical = grid_dir / f"{canonical_unsigned}{suffix}{extension}"
                legacy = grid_dir / f"{legacy_signed}{suffix}{extension}"
                if not (canonical.exists() and canonical.is_file()):
                    continue
                if not (legacy.exists() and legacy.is_file()):
                    continue
                if _unlink_best_effort(legacy):
                    removed += 1
    return removed


def _spawn_detached(command: list[str], *, shell: bool = False) -> None:
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "shell": shell,
    }
    if os.name != "nt":
        kwargs["start_new_session"] = True
    subprocess.Popen(command, **kwargs)


def reopen_steam(context: SteamContext) -> bool:
    if context.steam_exe and context.steam_exe.exists():
        _spawn_detached([str(context.steam_exe)])
        return True
    if os.name == "nt":
        _spawn_detached(["cmd", "/c", "start", "", "steam://open/main"], shell=False)
        return True
    launchers: list[list[str]] = []
    if shutil.which("steam"):
        launchers.append(["steam", "steam://open/main"])
    if shutil.which("xdg-open"):
        launchers.append(["xdg-open", "steam://open/main"])
    if shutil.which("flatpak"):
        launchers.append(["flatpak", "run", "com.valvesoftware.Steam", "steam://open/main"])
    for command in launchers:
        try:
            _spawn_detached(command)
            return True
        except OSError:
            continue
    return False
