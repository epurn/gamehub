from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

import vdf

from gamehub_common.models import LibraryIndex, TitleEntry

from .io import _atomic_write_bytes, _atomic_write_text
from .lifecycle import steam_id64_from_userdata_id
from .shortcuts import _canonical_unsigned_app_id
from .types import ShortcutSyncResult, SteamContext

_DECK_TEMPLATE_SEED_WII_FILENAME = "wii_0.vdf"
_DECK_TEMPLATE_SEED_N3DS_FILENAME = "3ds_0.vdf"
_DECK_TEMPLATE_WII_FILENAME = "gamehub_wii.vdf"
_DECK_TEMPLATE_N3DS_FILENAME = "gamehub_3ds.vdf"
_DECK_TEMPLATE_CONFIGSET_FILENAME = "configset_controller_neptune.vdf"
_DECK_TEMPLATE_CONFIGSET_AUTOSAVE = "1"
_DECK_TEMPLATE_CONFIGSET_GLOB = "configset_*.vdf"
_DECK_TEMPLATE_LEGACY_AUTOCLOUD_FILENAME = "steam_autocloud.vdf"
_DECK_TEMPLATE_SYSTEM_ORDER = ("Wii", "N3DS")
_DECK_TEMPLATE_SEED_ROOT = Path(__file__).resolve().parent / "template_seeds" / "steamdeck"
_DECK_TEMPLATE_SEED_BY_SYSTEM = {
    "Wii": _DECK_TEMPLATE_SEED_ROOT / "wii_gc" / _DECK_TEMPLATE_SEED_WII_FILENAME,
    "N3DS": _DECK_TEMPLATE_SEED_ROOT / "n3ds" / _DECK_TEMPLATE_SEED_N3DS_FILENAME,
}
_DECK_TEMPLATE_FILENAMES_BY_SYSTEM = {
    # Managed Deck template targets are system-fixed filenames.
    "Wii": (_DECK_TEMPLATE_WII_FILENAME,),
    "N3DS": (_DECK_TEMPLATE_N3DS_FILENAME,),
}
_DECK_TEMPLATE_DISABLED_SYSTEMS = {"GC"}
_STEAM_INPUT_CLOUD_APP_ID = "241100"
_DECK_TEMPLATE_UI_TITLE_BY_SYSTEM = {
    "Wii": "GameHub Wii",
    "N3DS": "GameHub 3DS",
}
_DECK_TEMPLATE_UI_DESCRIPTION_BY_SYSTEM = {
    "Wii": "GameHub managed Wii pointer template",
    "N3DS": "GameHub managed 3DS touch template",
}
_DECK_TEMPLATE_METADATA_CREATOR = "0"
_DECK_TEMPLATE_METADATA_PROGENITOR = ""
_DECK_TEMPLATE_METADATA_TIMESTAMP = "0"
_DECK_MANAGED_TEMPLATE_SELECTIONS = frozenset(
    {
        "controller_neptune",
        "wii_0",
        "3ds_0",
        "gamehub_wii",
        "gamehub_3ds",
    }
)
_DECK_MANAGED_TEMPLATE_FILENAMES_FOR_CLEANUP = (
    "controller_neptune.vdf",
    "wii_0.vdf",
    "3ds_0.vdf",
    "gamehub_wii.vdf",
    "gamehub_3ds.vdf",
)
_DECK_MANAGED_TEMPLATE_GLOBS = (
    "controller_*.vdf",
    "wii_*.vdf",
    "3ds_*.vdf",
    "gamehub_*.vdf",
)
_WHITESPACE_RE = re.compile(r"\s+")
_KV_SINGLE_VALUE_PATTERN = re.compile(r'(?P<prefix>"(?P<key>[^"]+)"\s+)"(?P<value>[^"\n]*)"')

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
        home / ".local" / "share" / "Steam" / "steamapps" / "common" / "Steam Controller Configs" / steam_id / "config",
        home / ".steam" / "steam" / "steamapps" / "common" / "Steam Controller Configs" / steam_id / "config",
        home / ".steam" / "root" / "steamapps" / "common" / "Steam Controller Configs" / steam_id / "config",
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


def _resolve_deck_steam_input_roots(context: SteamContext, *, strict: bool) -> list[Path]:
    candidates = _expand_steam_input_root_variants(
        [
            *discover_deck_steam_input_roots(context.steam_id),
            *_discover_steam_input_cloud_roots(context),
        ]
    )
    unique_candidates: list[Path] = []
    seen_candidates: set[_PathIdentity] = set()
    for candidate in candidates:
        identity = _path_identity(candidate)
        if identity in seen_candidates:
            continue
        seen_candidates.add(identity)
        unique_candidates.append(candidate)

    existing = [candidate for candidate in unique_candidates if candidate.exists()]
    writable = [candidate for candidate in existing if candidate.is_dir() and os.access(candidate, os.W_OK)]
    if writable:
        unique_writable: list[Path] = []
        seen_writable: set[_PathIdentity] = set()
        for path in writable:
            identity = _path_identity(path)
            if identity in seen_writable:
                continue
            seen_writable.add(identity)
            unique_writable.append(path)
        return unique_writable

    if strict:
        tried = ", ".join(str(path) for path in unique_candidates) or "<none>"
        raise RuntimeError(
            f"Steam Deck template sync strict mode: no writable Steam input config root was found (tried: {tried})"
        )

    if not unique_candidates:
        return []
    target = unique_candidates[0]
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        return []
    if not os.access(target, os.W_OK):
        return []
    return [target]


def _seed_path_for_system(system_name: str) -> Path | None:
    return _DECK_TEMPLATE_SEED_BY_SYSTEM.get(system_name)


def _template_filenames_for_system(system_name: str) -> tuple[str, ...]:
    return _DECK_TEMPLATE_FILENAMES_BY_SYSTEM.get(system_name, ())


def _template_selection_name_for_system(system_name: str) -> str:
    filenames = _template_filenames_for_system(system_name)
    if not filenames:
        raise RuntimeError(f"Steam Deck template sync strict mode: no template filename for system '{system_name}'")
    first_name = filenames[0]
    if first_name.casefold().endswith(".vdf"):
        return first_name[:-4]
    return first_name


def _template_reference_for_title(title: TitleEntry) -> str:
    selection_name = _template_selection_name_for_system(title.system)
    title_key = normalize_steam_input_title_dir(title.title_name)
    return f"CLOUD_{title_key}/{selection_name}"


def _forced_controller_config_entry(*, title: TitleEntry) -> dict[str, str]:
    return {"template": _template_reference_for_title(title)}


def _is_managed_template_name(value: str) -> bool:
    normalized = str(value).strip().casefold()
    if not normalized:
        return False
    base = normalized[:-4] if normalized.endswith(".vdf") else normalized
    if base in _DECK_MANAGED_TEMPLATE_SELECTIONS:
        return True
    if normalized.startswith("cloud_"):
        for selection in _DECK_MANAGED_TEMPLATE_SELECTIONS:
            if normalized.endswith(f"/{selection}") or normalized.endswith(f"/{selection}.vdf"):
                return True
    return False


def _replace_first_key_value(text: str, *, key: str, value: str) -> str:
    target_key = key.casefold()
    for match in _KV_SINGLE_VALUE_PATTERN.finditer(text):
        if match.group("key").casefold() != target_key:
            continue
        return f"{text[: match.start('value')]}{value}{text[match.end('value') :]}"
    return text


def _replace_english_localization_values(text: str, *, title: str, description: str) -> str:
    marker = '"english"'
    english_index = text.find(marker)
    if english_index < 0:
        return text

    brace_open = text.find("{", english_index)
    if brace_open < 0:
        return text

    depth = 0
    brace_close = -1
    for index in range(brace_open, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                brace_close = index
                break
    if brace_close < 0:
        return text

    english_block = text[brace_open : brace_close + 1]
    english_block = _replace_first_key_value(english_block, key="title", value=title)
    english_block = _replace_first_key_value(english_block, key="description", value=description)
    return f"{text[:brace_open]}{english_block}{text[brace_close + 1 :]}"


def _render_managed_template_payload(system_name: str, payload: bytes) -> bytes:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return payload

    ui_title = _DECK_TEMPLATE_UI_TITLE_BY_SYSTEM.get(system_name, f"GameHub {system_name}")
    ui_description = _DECK_TEMPLATE_UI_DESCRIPTION_BY_SYSTEM.get(system_name, "GameHub managed controller template")
    selection_name = _template_selection_name_for_system(system_name)
    updated = text
    updated = _replace_first_key_value(updated, key="title", value=ui_title)
    updated = _replace_first_key_value(updated, key="description", value=ui_description)
    updated = _replace_first_key_value(updated, key="url", value=f"template://{selection_name}.vdf")
    updated = _replace_first_key_value(updated, key="creator", value=_DECK_TEMPLATE_METADATA_CREATOR)
    updated = _replace_first_key_value(updated, key="progenitor", value=_DECK_TEMPLATE_METADATA_PROGENITOR)
    updated = _replace_first_key_value(updated, key="timestamp", value=_DECK_TEMPLATE_METADATA_TIMESTAMP)
    updated = _replace_english_localization_values(updated, title=ui_title, description=ui_description)
    return updated.encode("utf-8")


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
            payloads[system_name] = _render_managed_template_payload(system_name, seed_path.read_bytes())
        except OSError as exc:
            if strict:
                raise RuntimeError(
                    f"Steam Deck template sync strict mode: failed reading seed for {system_name} ({seed_path}): {exc}"
                ) from exc
            errors += 1
    return payloads, errors


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


def _sync_deck_template_selection_configset(
    *,
    configset_path: Path,
    managed_titles: list[TitleEntry],
    removed_titles: list[TitleEntry],
    shortcut_result: ShortcutSyncResult,
    strict: bool,
) -> int:
    try:
        if configset_path.exists():
            payload_raw = vdf.loads(configset_path.read_text(encoding="utf-8"))
            payload = dict(payload_raw) if isinstance(payload_raw, dict) else {}
        else:
            payload = {}
    except (OSError, Exception) as exc:
        if strict:
            raise RuntimeError(
                f"Steam Deck template sync strict mode: failed loading template configset ({configset_path}): {exc}"
            ) from exc
        return 1

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

    for title in removed_titles:
        app_id = shortcut_result.app_ids_by_title.get(title.title_id)
        for key in _configset_entry_keys(title.title_name, app_id):
            existing_entry = controller_config.get(key)
            if not isinstance(existing_entry, dict):
                continue
            template_name = str(existing_entry.get("template", ""))
            autosave = str(existing_entry.get("autosave", "")).strip()
            if not _is_managed_template_name(template_name) and autosave != _DECK_TEMPLATE_CONFIGSET_AUTOSAVE:
                continue
            del controller_config[key]
            changed = True

    if not changed:
        return 0
    try:
        _atomic_write_text(configset_path, str(vdf.dumps(payload, pretty=True)))
    except OSError as exc:
        if strict:
            raise RuntimeError(
                f"Steam Deck template sync strict mode: failed writing template configset ({configset_path}): {exc}"
            ) from exc
        return 1
    return 0


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
    seen: set[_PathIdentity] = set()
    for path in paths:
        identity = _path_identity(path)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(path)
    return unique


def _sync_deck_template_selection_configsets(
    *,
    root: Path,
    managed_titles: list[TitleEntry],
    removed_titles: list[TitleEntry],
    shortcut_result: ShortcutSyncResult,
    strict: bool,
) -> int:
    errors = 0
    for configset_path in _iter_target_configset_paths(root):
        errors += _sync_deck_template_selection_configset(
            configset_path=configset_path,
            managed_titles=managed_titles,
            removed_titles=removed_titles,
            shortcut_result=shortcut_result,
            strict=strict,
        )
    return errors


def _legacy_steam_autocloud_paths(root: Path) -> list[Path]:
    candidates = [root / _DECK_TEMPLATE_LEGACY_AUTOCLOUD_FILENAME]
    if root.name.casefold() != "config":
        candidates.append(root / "config" / _DECK_TEMPLATE_LEGACY_AUTOCLOUD_FILENAME)
    unique: list[Path] = []
    seen: set[_PathIdentity] = set()
    for path in candidates:
        identity = _path_identity(path)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(path)
    return unique


def _cleanup_legacy_steam_autocloud_files(*, root: Path, strict: bool) -> int:
    errors = 0
    for candidate in _legacy_steam_autocloud_paths(root):
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            candidate.unlink()
        except OSError as exc:
            if strict:
                raise RuntimeError(
                    "Steam Deck template sync strict mode: failed removing legacy steam autocloud config "
                    f"({candidate}): {exc}"
                ) from exc
            errors += 1
    return errors


def _cleanup_managed_title_template_files(
    *,
    root: Path,
    managed_titles: list[TitleEntry],
    strict: bool,
) -> int:
    errors = 0
    for title in managed_titles:
        title_dir = root / normalize_steam_input_title_dir(title.title_name)
        if not title_dir.is_dir():
            continue
        allowed = set(_template_filenames_for_system(title.system))
        for pattern in _DECK_MANAGED_TEMPLATE_GLOBS:
            for candidate in sorted(title_dir.glob(pattern), key=lambda item: item.name.casefold()):
                if not candidate.is_file():
                    continue
                if candidate.name in allowed:
                    continue
                try:
                    candidate.unlink()
                except OSError as exc:
                    if strict:
                        raise RuntimeError(
                            "Steam Deck template sync strict mode: failed removing legacy managed template file "
                            f"for title '{title.title_name}' ({candidate}): {exc}"
                        ) from exc
                    errors += 1
    return errors


def _cleanup_disabled_title_template_files(
    *,
    root: Path,
    removed_titles: list[TitleEntry],
    strict: bool,
) -> int:
    errors = 0
    for title in removed_titles:
        title_dir = root / normalize_steam_input_title_dir(title.title_name)
        for filename in _DECK_MANAGED_TEMPLATE_FILENAMES_FOR_CLEANUP:
            target = title_dir / filename
            if not target.exists() or not target.is_file():
                continue
            try:
                target.unlink()
            except OSError as exc:
                if strict:
                    raise RuntimeError(
                        "Steam Deck template sync strict mode: failed removing disabled-system template file "
                        f"for title '{title.title_name}' ({target}): {exc}"
                    ) from exc
                errors += 1
    return errors


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

    candidate_titles = [
        title
        for title in sorted(index.titles, key=lambda item: (item.system, item.title_name.casefold(), item.title_id))
        if title.title_id in managed_title_ids
    ]
    managed_titles = [title for title in candidate_titles if title.system in _DECK_TEMPLATE_SEED_BY_SYSTEM]
    removed_titles = [title for title in candidate_titles if title.system in _DECK_TEMPLATE_DISABLED_SYSTEMS]
    if not managed_titles and not removed_titles:
        return TemplateSyncResult(targets=0, written=0, unchanged=0, errors=0, systems_applied=())

    required_systems = [
        system_name
        for system_name in _DECK_TEMPLATE_SYSTEM_ORDER
        if any(t.system == system_name for t in managed_titles)
    ]
    seed_payloads, errors = _load_seed_payloads(required_systems, strict=strict)
    applied_systems = tuple(system_name for system_name in required_systems if system_name in seed_payloads)
    if managed_titles and not seed_payloads:
        return TemplateSyncResult(targets=0, written=0, unchanged=0, errors=errors, systems_applied=applied_systems)

    roots = _resolve_deck_steam_input_roots(context, strict=strict)
    if not roots:
        return TemplateSyncResult(targets=0, written=0, unchanged=0, errors=errors + 1, systems_applied=applied_systems)

    targets = 0
    written = 0
    unchanged = 0

    for title in managed_titles:
        payload = seed_payloads.get(title.system)
        if payload is None:
            continue
        filenames = _template_filenames_for_system(title.system)
        targets += 1
        title_changed = False
        title_had_error = False
        for root in roots:
            title_dir = root / normalize_steam_input_title_dir(title.title_name)
            for filename in filenames:
                target_path = title_dir / filename
                try:
                    if target_path.exists() and target_path.read_bytes() == payload:
                        continue
                    _atomic_write_bytes(target_path, payload)
                    title_changed = True
                except OSError as exc:
                    if strict:
                        raise RuntimeError(
                            "Steam Deck template sync strict mode: failed writing template file "
                            f"for title '{title.title_name}' ({target_path}): {exc}"
                        ) from exc
                    errors += 1
                    title_had_error = True

        if title_had_error:
            continue
        if title_changed:
            written += 1
        else:
            unchanged += 1

    for root in roots:
        errors += _cleanup_legacy_steam_autocloud_files(root=root, strict=strict)
        errors += _cleanup_managed_title_template_files(
            root=root,
            managed_titles=managed_titles,
            strict=strict,
        )
        errors += _sync_deck_template_selection_configsets(
            root=root,
            managed_titles=managed_titles,
            removed_titles=removed_titles,
            shortcut_result=shortcut_result,
            strict=strict,
        )
        errors += _cleanup_disabled_title_template_files(
            root=root,
            removed_titles=removed_titles,
            strict=strict,
        )

    return TemplateSyncResult(
        targets=targets,
        written=written,
        unchanged=unchanged,
        errors=errors,
        systems_applied=applied_systems,
    )
