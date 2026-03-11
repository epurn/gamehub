from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Literal, cast
from urllib.parse import urljoin

from gamehub_common.ids import make_save_id
from gamehub_common.models import LibraryIndex, SaveBindingCatalog, SaveBindingSpec, SaveSpec

from ..common.config import GamehubConfig, load_config
from ..common.config_edit import upsert_simple_cfg_key
from ..common.fsops import backup_existing_file
from ..common.save_sync import (
    canonical_suffix_for_save,
    local_file_sha256,
    local_file_updated_at,
    record_converged_save_state,
    save_binding_id_for_save,
    timestamp_now_utc,
    to_utc_timestamp,
)
from ..common.shortcut_payload import ShortcutLaunchPayload, unquote_executable
from ..emulators import resolve_emulator_executable
from ..emulators.save_resolution import (
    canonical_suffix_for_learned_path,
    learn_binding_root,
    resolve_binding_local_root,
    resolve_exact_local_save_destination,
    resolve_local_save_destination,
    snapshot_binding_tree,
)
from ..firmware.pcsx2_ini import read_ini_lines, upsert_ini_key, write_ini_atomic
from ..firmware.targets import default_pcsx2_ini_path, retroarch_cfg_candidates_for_config
from ..sync.index import fetch_index_with_retries, fetch_save_bindings_with_retries, probe_server_health
from ..sync.planner import resolve_missed_upload_timestamp_decision, resolve_save_action
from ..sync.save_stage import reconcile_upload_conflict, record_uploaded_save
from ..sync.state import MISSED_POSTEXIT_UPLOAD_REASON
from ..sync.transfer import SaveUploadConflictError, stream_to_destination_atomic, upload_file_to_server
from .runtime import warn_shortcut_runtime

_SHORTCUT_HEALTHCHECK_TIMEOUT_SECONDS = 1.0
_SHORTCUT_METADATA_TIMEOUT_CAP_SECONDS = 5.0
_SHORTCUT_METADATA_FETCH_ATTEMPTS = 1
_SHORTCUT_METADATA_RETRY_BACKOFF_SECONDS = 0.0
logger = logging.getLogger(__name__)


class _ShortcutMetadataError(RuntimeError):
    """Raised when launch-session save metadata helpers cannot complete."""


@dataclass(frozen=True)
class ShortcutSaveSnapshot:
    destination: Path | None
    local_sha256: str | None
    remote_sha256: str
    allow_postexit_upload: bool
    pending_postexit_upload: bool = False


@dataclass(frozen=True)
class ShortcutTreeSnapshot:
    binding: SaveBindingSpec
    before: dict[str, str]


@dataclass(frozen=True)
class ShortcutExactBindingSnapshot:
    binding: SaveBindingSpec
    local_sha256_by_suffix: dict[str, str | None]


@dataclass
class ShortcutSaveContext:
    save_snapshots: dict[str, ShortcutSaveSnapshot]
    exact_binding_snapshots: dict[str, ShortcutExactBindingSnapshot]
    tree_snapshots: dict[str, ShortcutTreeSnapshot]


def _offline_shortcut_titles(state: Any) -> dict[str, str]:
    titles = getattr(state, "offline_shortcut_titles", None)
    if isinstance(titles, dict):
        return titles
    titles = {}
    setattr(state, "offline_shortcut_titles", titles)
    return titles


def _mark_offline_shortcut_title(state: Any, *, title_id: str | None) -> bool:
    if not title_id:
        return False
    titles = _offline_shortcut_titles(state)
    previous = titles.get(title_id)
    titles[title_id] = timestamp_now_utc()
    return previous != titles[title_id]


def _clear_offline_shortcut_title(state: Any, *, title_id: str | None) -> bool:
    if not title_id:
        return False
    titles = _offline_shortcut_titles(state)
    return titles.pop(title_id, None) is not None


def _flatpak_run_app_id(target_args: tuple[str, ...]) -> str | None:
    folded = [arg.casefold() for arg in target_args]
    try:
        run_index = folded.index("run")
    except ValueError:
        return None
    for token in target_args[run_index + 1 :]:
        if token == "--":
            break
        if token.startswith("-"):
            continue
        return token
    return None


def _flag_value(target_args: tuple[str, ...], *, flag_name: str) -> str | None:
    flag = flag_name.casefold()
    for index, token in enumerate(target_args):
        normalized = token.casefold()
        if normalized == flag and index + 1 < len(target_args):
            return target_args[index + 1]
        if normalized.startswith(f"{flag}="):
            value = token.split("=", 1)[1].strip()
            if value:
                return value
    return None


def _shortcut_flatpak_app_id(payload: ShortcutLaunchPayload) -> str | None:
    target_exe = unquote_executable(payload.target_exe).strip().casefold()
    if target_exe == "flatpak":
        return _flatpak_run_app_id(payload.target_args)
    if "azahar" in payload.emulator.casefold():
        args_folded = {arg.casefold() for arg in payload.target_args}
        if "gamehub_cli.controllers.azahar_exit_hook" in args_folded:
            return _flag_value(payload.target_args, flag_name="--app-id")
    return None


def _shortcut_resolver_config(payload: ShortcutLaunchPayload) -> GamehubConfig | None:
    if not payload.config_path:
        return None
    try:
        return load_config(Path(payload.config_path).expanduser())
    except Exception:  # noqa: BLE001
        return None


def build_shortcut_save_resolver(payload: ShortcutLaunchPayload) -> Callable[[str], str]:
    target_exe = unquote_executable(payload.target_exe).strip()
    payload_emulator = payload.emulator.casefold()
    flatpak_app_id = _shortcut_flatpak_app_id(payload)
    resolver_config = _shortcut_resolver_config(payload)
    if not target_exe:
        return resolve_emulator_executable

    expected_names: set[str] = set()
    if "retroarch" in payload_emulator:
        expected_names.update({"retroarch"})
    elif "pcsx2" in payload_emulator:
        expected_names.update({"pcsx2", "pcsx2-qt"})
    elif "dolphin" in payload_emulator:
        expected_names.update({"dolphin", "dolphin-emu"})
    elif "azahar" in payload_emulator:
        expected_names.update({"azahar", "azahar-qt"})

    def _resolve(name: str) -> str:
        normalized = name.strip().strip('"').casefold()
        if normalized in expected_names:
            if flatpak_app_id:
                return f"/flatpak/exports/bin/{flatpak_app_id}"
            return target_exe
        return resolve_emulator_executable(name)

    if resolver_config is not None:
        setattr(_resolve, "_gamehub_config", resolver_config)
    return _resolve


def _shortcut_metadata_timeout_seconds(config: GamehubConfig) -> float:
    configured = config.index_timeout_seconds if config.index_timeout_seconds is not None else 30.0
    return min(configured, _SHORTCUT_METADATA_TIMEOUT_CAP_SECONDS)


def _shortcut_server_reachable(config: GamehubConfig) -> bool:
    try:
        return bool(
            probe_server_health(
                server_url=config.server_url,
                timeout_seconds=_SHORTCUT_HEALTHCHECK_TIMEOUT_SECONDS,
            )
        )
    except Exception as exc:  # noqa: BLE001
        raise _ShortcutMetadataError(f"save sync server reachability probe failed ({exc})") from exc


def _shortcut_server_reachable_or_warn(config: GamehubConfig) -> bool:
    try:
        return _shortcut_server_reachable(config)
    except _ShortcutMetadataError as exc:
        warn_shortcut_runtime(str(exc))
        return False


def _load_shortcut_index(config: GamehubConfig, *, verbose: bool) -> LibraryIndex | None:
    timeout_seconds = _shortcut_metadata_timeout_seconds(config)
    index_url = urljoin(config.server_url.rstrip("/") + "/", "v1/index")
    try:
        raw_index = fetch_index_with_retries(
            index_url=index_url,
            timeout_seconds=timeout_seconds,
            attempts=_SHORTCUT_METADATA_FETCH_ATTEMPTS,
            retry_backoff_seconds=_SHORTCUT_METADATA_RETRY_BACKOFF_SECONDS,
            verbose=verbose,
        )
        return LibraryIndex.model_validate(raw_index)
    except Exception as exc:  # noqa: BLE001
        raise _ShortcutMetadataError(f"save sync index fetch failed ({exc})") from exc


def _load_shortcut_index_or_warn(config: GamehubConfig, *, verbose: bool) -> LibraryIndex | None:
    try:
        return _load_shortcut_index(config, verbose=verbose)
    except _ShortcutMetadataError as exc:
        warn_shortcut_runtime(str(exc))
        return None


def _load_shortcut_save_bindings(config: GamehubConfig, *, verbose: bool) -> SaveBindingCatalog | None:
    timeout_seconds = _shortcut_metadata_timeout_seconds(config)
    bindings_url = urljoin(config.server_url.rstrip("/") + "/", "v1/save-bindings")
    try:
        raw_bindings = fetch_save_bindings_with_retries(
            bindings_url=bindings_url,
            timeout_seconds=timeout_seconds,
            attempts=_SHORTCUT_METADATA_FETCH_ATTEMPTS,
            retry_backoff_seconds=_SHORTCUT_METADATA_RETRY_BACKOFF_SECONDS,
            verbose=verbose,
        )
        return SaveBindingCatalog.model_validate(raw_bindings)
    except Exception as exc:  # noqa: BLE001
        raise _ShortcutMetadataError(f"save sync binding fetch failed ({exc})") from exc


def _load_shortcut_save_bindings_or_warn(config: GamehubConfig, *, verbose: bool) -> SaveBindingCatalog | None:
    try:
        return _load_shortcut_save_bindings(config, verbose=verbose)
    except _ShortcutMetadataError as exc:
        warn_shortcut_runtime(str(exc))
        return None


def _iter_title_saves(index: LibraryIndex, title_id: str) -> tuple[SaveSpec, ...]:
    return tuple(
        sorted(
            (save for save in index.saves if save.title_id == title_id),
            key=lambda item: (item.system, item.rel_path, item.save_id),
        )
    )


def _upload_save_from_path(
    *,
    server_url: str,
    save: SaveSpec,
    source: Path,
    timeout_seconds: float,
) -> SaveSpec:
    payload = upload_file_to_server(
        server_url=server_url,
        url=f"/v1/saves/{save.save_id}",
        source=source,
        binding_id=save_binding_id_for_save(save),
        canonical_suffix=canonical_suffix_for_save(save),
        timeout_seconds=timeout_seconds,
        expected_remote_sha256=save.sha256,
    )
    return SaveSpec.model_validate(payload)


def _upload_new_save_from_path(
    *,
    server_url: str,
    save_id: str,
    binding: SaveBindingSpec,
    canonical_suffix: str,
    source: Path,
    timeout_seconds: float,
) -> SaveSpec:
    payload = upload_file_to_server(
        server_url=server_url,
        url=f"/v1/saves/{save_id}",
        source=source,
        binding_id=binding.binding_id,
        canonical_suffix=canonical_suffix,
        timeout_seconds=timeout_seconds,
        expected_remote_sha256=None,
    )
    return SaveSpec.model_validate(payload)


def _record_shortcut_save_sync(state: Any, save: SaveSpec, destination: Path, *, local_sha256: str) -> None:
    record_converged_save_state(
        save_id=save.save_id,
        save_checksums=state.save_checksums,
        save_lineage=state.save_lineage,
        unresolved_save_conflicts=state.unresolved_save_conflicts,
        local_sha256=local_sha256,
        remote_sha256=save.sha256,
        local_updated_at=local_file_updated_at(destination),
        remote_updated_at=to_utc_timestamp(save.updated_at),
    )


def _record_binding_root(state: Any, *, binding_id: str, canonical_root: str, materialized_root: str) -> None:
    state.save_binding_roots[binding_id] = {
        "canonical_root": canonical_root,
        "materialized_root": materialized_root,
    }


def _record_missed_postexit_upload(
    state: Any,
    *,
    save_id: str,
    destination: Path,
    local_sha256: str,
) -> bool:
    lineage = state.save_lineage.get(save_id)
    changed = False
    if not isinstance(lineage, dict):
        lineage = {}
        state.save_lineage[save_id] = lineage
        changed = True
    if lineage.get("local_sha256") != local_sha256:
        lineage["local_sha256"] = local_sha256
        changed = True
    local_updated_at = local_file_updated_at(destination)
    if local_updated_at is not None and lineage.get("local_updated_at") != local_updated_at:
        lineage["local_updated_at"] = local_updated_at
        changed = True
    if state.unresolved_save_conflicts.get(save_id) != MISSED_POSTEXIT_UPLOAD_REASON:
        state.unresolved_save_conflicts[save_id] = MISSED_POSTEXIT_UPLOAD_REASON
        changed = True
    return changed


def _mark_missed_postexit_uploads_from_snapshots(
    *,
    state: Any,
    context: ShortcutSaveContext,
    verbose: bool,
    audit: bool,
) -> bool:
    state_changed = False
    for save_id, snapshot in context.save_snapshots.items():
        if snapshot.destination is None or not snapshot.allow_postexit_upload:
            continue
        local_sha = local_file_sha256(snapshot.destination)
        if local_sha is None:
            continue
        if not _should_attempt_postexit_upload(snapshot, local_sha=local_sha):
            continue
        state_changed = (
            _record_missed_postexit_upload(
                state,
                save_id=save_id,
                destination=snapshot.destination,
                local_sha256=local_sha,
            )
            or state_changed
        )
        if verbose or audit:
            print(f"shortcut-save\tpostexit\tdefer\t{save_id}\t{MISSED_POSTEXIT_UPLOAD_REASON}")
    return state_changed


def _should_attempt_postexit_upload(snapshot: ShortcutSaveSnapshot, *, local_sha: str | None) -> bool:
    if local_sha is None:
        return False
    return snapshot.pending_postexit_upload or local_sha != snapshot.local_sha256


def _changed_tree_paths(before: dict[str, str], after: dict[str, str]) -> tuple[str, ...]:
    changed = {rel_path for rel_path, sha in after.items() if rel_path not in before or before[rel_path] != sha}
    return tuple(sorted(changed))


def _snapshot_exact_binding(
    binding: SaveBindingSpec,
    *,
    remote_save_ids: set[str],
    resolve_executable: Callable[[str], str],
) -> ShortcutExactBindingSnapshot | None:
    if binding.strategy != "exact_files":
        return None
    root = resolve_binding_local_root(binding, resolve_executable=resolve_executable)
    if root is None:
        return None
    local_sha256_by_suffix: dict[str, str | None] = {}
    exact_kind = cast(Literal["battery", "memory_card"], binding.kind)
    for filename in binding.candidate_filenames:
        save_id = make_save_id(f"{binding.server_rel_dir}/{filename}")
        if save_id in remote_save_ids:
            continue
        destination = resolve_exact_local_save_destination(
            system=binding.system,
            kind=exact_kind,
            root=root,
            filename=filename,
            resolve_executable=resolve_executable,
        )
        local_sha256_by_suffix[filename] = local_file_sha256(destination)
    if not local_sha256_by_suffix:
        return None
    return ShortcutExactBindingSnapshot(binding=binding, local_sha256_by_suffix=local_sha256_by_suffix)


def _run_shortcut_postexit_exact_binding_sync(
    *,
    state: Any,
    current_saves: dict[str, SaveSpec],
    exact_snapshots: dict[str, ShortcutExactBindingSnapshot],
    resolve_executable: Callable[[str], str],
    server_url: str,
    timeout_seconds: float,
    verbose: bool,
    audit: bool,
) -> bool:
    state_changed = False
    for exact_snapshot in exact_snapshots.values():
        binding = exact_snapshot.binding
        root = resolve_binding_local_root(binding, resolve_executable=resolve_executable)
        if root is None:
            continue
        exact_kind = cast(Literal["battery", "memory_card"], binding.kind)
        for filename in binding.candidate_filenames:
            before_sha = exact_snapshot.local_sha256_by_suffix.get(filename)
            if filename not in exact_snapshot.local_sha256_by_suffix:
                continue
            destination = resolve_exact_local_save_destination(
                system=binding.system,
                kind=exact_kind,
                root=root,
                filename=filename,
                resolve_executable=resolve_executable,
            )
            local_sha = local_file_sha256(destination)
            if local_sha is None:
                continue
            save_id = make_save_id(f"{binding.server_rel_dir}/{filename}")
            save = current_saves.get(save_id)
            if save is not None:
                if local_sha == save.sha256:
                    _record_shortcut_save_sync(state, save, destination, local_sha256=local_sha)
                    state_changed = True
                    if verbose or audit:
                        print(f"shortcut-save\tpostexit\tskip\t{save_id}\talready-synced")
                    continue
                state.unresolved_save_conflicts[save_id] = "create-race-content-mismatch"
                state_changed = True
                if verbose or audit:
                    print(f"shortcut-save\tpostexit\tconflict\t{save_id}\tcreate-race-content-mismatch")
                continue
            try:
                created_save = _upload_new_save_from_path(
                    server_url=server_url,
                    save_id=save_id,
                    binding=binding,
                    canonical_suffix=filename,
                    source=destination,
                    timeout_seconds=timeout_seconds,
                )
                record_uploaded_save(
                    state=state,
                    save_id=save_id,
                    destination=destination,
                    save=created_save,
                )
                state_changed = True
                action = "auto-create" if before_sha is None else "auto-create-existing-local"
                if verbose or audit:
                    print(f"shortcut-save\tpostexit\tupload\t{save_id}\t{action}")
            except SaveUploadConflictError as exc:
                if (
                    reconcile_upload_conflict(
                        state=state,
                        save_id=save_id,
                        destination=destination,
                        exc=exc,
                    )
                    is not None
                ):
                    state_changed = True
                    if verbose or audit:
                        print(f"shortcut-save\tpostexit\tskip\t{save_id}\talready-synced")
                    continue
                state.unresolved_save_conflicts[save_id] = "create-race-or-upload-failed"
                state_changed = True
                warn_shortcut_runtime(f"post-exit save upload failed for {save_id} ({exc})")
            except Exception as exc:  # noqa: BLE001
                state.unresolved_save_conflicts[save_id] = "create-race-or-upload-failed"
                state_changed = True
                warn_shortcut_runtime(f"post-exit save upload failed for {save_id} ({exc})")
    return state_changed


def _psx_runtime_candidate_filenames(payload: ShortcutLaunchPayload) -> tuple[str, ...]:
    if not payload.title_id:
        return ()
    values = [f"GH_{payload.title_id}_1.mcd", f"GH_{payload.title_id}_2.mcd"]
    if payload.rom_rel_path:
        rom_stem = PurePosixPath(payload.rom_rel_path).stem.strip()
        if rom_stem:
            values.extend((f"{rom_stem}.srm", f"{rom_stem}_1.mcd", f"{rom_stem}_2.mcd"))
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return tuple(deduped)


def _preferred_psx_memory_card_filenames(
    payload: ShortcutLaunchPayload,
) -> tuple[str, str]:
    if not payload.title_id:
        return "", ""
    default_slot1 = f"GH_{payload.title_id}_1.mcd"
    default_slot2 = f"GH_{payload.title_id}_2.mcd"
    candidate_filenames = _psx_runtime_candidate_filenames(payload)
    if not candidate_filenames:
        return default_slot1, default_slot2
    binding = SaveBindingSpec(
        binding_id="savebind_runtime_psx",
        title_id=payload.title_id,
        system="PSX",
        kind="memory_card",
        server_rel_dir="saves/PSX/runtime/memory_card",
        local_root="retroarch_saves_psx",
        strategy="exact_files",
        candidate_filenames=candidate_filenames,
        learn_rule=None,
        portable=True,
    )
    resolve_executable = build_shortcut_save_resolver(payload)
    root = resolve_binding_local_root(binding, resolve_executable=resolve_executable)
    if root is None:
        return default_slot1, default_slot2

    rom_stem = PurePosixPath(payload.rom_rel_path).stem.strip() if payload.rom_rel_path else ""
    slot1_candidates = [default_slot1]
    slot2_candidates = [default_slot2]
    if rom_stem:
        slot1_candidates.extend((f"{rom_stem}.srm", f"{rom_stem}_1.mcd"))
        slot2_candidates.append(f"{rom_stem}_2.mcd")

    def _first_existing(candidates: list[str]) -> str | None:
        for candidate in candidates:
            path = resolve_exact_local_save_destination(
                system="PSX",
                kind="memory_card",
                root=root,
                filename=candidate,
                resolve_executable=resolve_executable,
            )
            if path.exists() and path.name == candidate:
                return candidate
        return None

    return _first_existing(slot1_candidates) or default_slot1, _first_existing(slot2_candidates) or default_slot2


def ensure_managed_memory_card_paths(payload: ShortcutLaunchPayload, config: GamehubConfig) -> bool:
    if not payload.title_id or payload.system not in {"PSX", "PS2"}:
        return False

    if payload.system == "PS2":
        targets = {
            "Slot1_Filename": f"GH_{payload.title_id}_1.ps2",
            "Slot2_Filename": f"GH_{payload.title_id}_2.ps2",
            "Slot1_Enable": "true",
            "Slot2_Enable": "true",
        }
        path = default_pcsx2_ini_path(config=config)
        lines = read_ini_lines(path)
        changed = False
        for key, value in targets.items():
            lines, key_changed = upsert_ini_key(lines, "MemoryCards", key, value)
            changed |= key_changed
        if changed or not path.exists():
            if path.exists():
                backup = backup_existing_file(path)
                if backup is not None:
                    logger.info("managed memory-card backup created path=%s backup=%s", path, backup)
            write_ini_atomic(path, lines)
            logger.info(
                "managed memory-card config updated path=%s system=%s title_id=%s",
                path,
                payload.system,
                payload.title_id,
            )
        return changed

    cfg_candidates = list(retroarch_cfg_candidates_for_config(config=config))
    target_executable = unquote_executable(payload.target_exe).strip()
    if target_executable and target_executable.casefold() != "flatpak":
        target_path = Path(target_executable)
        if target_path.suffix:
            target_cfg = target_path.with_name("retroarch.cfg")
            cfg_candidates = [target_cfg, *(item for item in cfg_candidates if item != target_cfg)]
    cfg_path = next(
        (candidate for candidate in cfg_candidates if candidate.exists()),
        cfg_candidates[0] if cfg_candidates else None,
    )
    if cfg_path is None:
        return False
    core_options_path = cfg_path.with_name("retroarch-core-options.cfg")
    lines = read_ini_lines(core_options_path)
    changed = False
    slot1_filename, slot2_filename = _preferred_psx_memory_card_filenames(payload)
    for key, value in {
        "swanstation_MemoryCard1Path": slot1_filename,
        "swanstation_MemoryCard2Path": slot2_filename,
    }.items():
        lines, key_changed = upsert_simple_cfg_key(lines, key, value)
        changed |= key_changed
    if changed or not core_options_path.exists():
        if core_options_path.exists():
            backup = backup_existing_file(core_options_path)
            if backup is not None:
                logger.info("managed memory-card backup created path=%s backup=%s", core_options_path, backup)
        write_ini_atomic(core_options_path, lines)
        logger.info(
            "managed memory-card config updated path=%s system=%s title_id=%s",
            core_options_path,
            payload.system,
            payload.title_id,
        )
    return changed


def should_sync_shortcut_saves(payload: ShortcutLaunchPayload, config: GamehubConfig) -> bool:
    if not config.save_sync.enabled:
        return False
    if not payload.title_id:
        return False
    if config.save_sync.systems and payload.system and payload.system.upper() not in config.save_sync.systems:
        return False
    return True


def run_shortcut_prelaunch_save_sync(
    *,
    payload: ShortcutLaunchPayload,
    config: GamehubConfig,
    state: Any,
    resolve_executable: Callable[[str], str],
    verbose: bool,
    audit: bool,
) -> tuple[ShortcutSaveContext, bool]:
    context = ShortcutSaveContext(save_snapshots={}, exact_binding_snapshots={}, tree_snapshots={})
    if not should_sync_shortcut_saves(payload, config):
        return context, False
    if not _shortcut_server_reachable_or_warn(config):
        state_changed = False
        if config.save_sync.mode == "bidirectional":
            state_changed = _mark_offline_shortcut_title(state, title_id=payload.title_id)
        if verbose or audit:
            print("shortcut-save\tprelaunch\tskip\tserver-unreachable")
        return context, state_changed

    index = _load_shortcut_index_or_warn(config, verbose=verbose)
    if index is None or payload.title_id is None:
        state_changed = False
        if index is None and config.save_sync.mode == "bidirectional":
            state_changed = _mark_offline_shortcut_title(state, title_id=payload.title_id)
        return context, state_changed

    save_bindings: SaveBindingCatalog | None = None
    if config.save_sync.mode == "bidirectional":
        save_bindings = _load_shortcut_save_bindings_or_warn(config, verbose=verbose)
    title_saves = _iter_title_saves(index, payload.title_id)
    needs_psx_exact_binding = any(save.system.upper() == "PSX" and save.kind == "memory_card" for save in title_saves)
    if save_bindings is None and needs_psx_exact_binding:
        save_bindings = _load_shortcut_save_bindings_or_warn(config, verbose=verbose)
    binding_by_id = {
        binding.binding_id: binding
        for binding in (() if save_bindings is None else save_bindings.bindings)
        if binding.title_id == payload.title_id
    }
    remote_save_ids = {save.save_id for save in title_saves}
    if save_bindings is not None and config.save_sync.mode == "bidirectional":
        for binding in save_bindings.bindings:
            if binding.title_id != payload.title_id:
                continue
            if binding.strategy == "learned_tree":
                context.tree_snapshots[binding.binding_id] = ShortcutTreeSnapshot(
                    binding=binding,
                    before=snapshot_binding_tree(binding, resolve_executable=resolve_executable),
                )
                continue
            exact_snapshot = _snapshot_exact_binding(
                binding,
                remote_save_ids=remote_save_ids,
                resolve_executable=resolve_executable,
            )
            if exact_snapshot is not None:
                context.exact_binding_snapshots[binding.binding_id] = exact_snapshot

    state_changed = False
    offline_title_pending = config.save_sync.mode == "bidirectional" and payload.title_id in _offline_shortcut_titles(
        state
    )
    needs_offline_title = False
    for save in title_saves:
        destination = resolve_local_save_destination(
            save,
            binding_roots=state.save_binding_roots,
            binding=binding_by_id.get(save_binding_id_for_save(save)),
            resolve_executable=resolve_executable,
        )
        local_sha = local_file_sha256(destination) if destination is not None else None
        allow_postexit_upload = True
        if destination is None:
            reason = "save-path-unavailable"
            context.save_snapshots[save.save_id] = ShortcutSaveSnapshot(
                destination=None,
                local_sha256=None,
                remote_sha256=save.sha256,
                allow_postexit_upload=False,
                pending_postexit_upload=False,
            )
            if verbose or audit:
                print(f"shortcut-save\tprelaunch\tskip\t{save.save_id}\t{reason}")
            continue

        lineage = state.save_lineage.get(save.save_id, {})
        lineage_local_sha = lineage.get("local_sha256")
        lineage_remote_sha = lineage.get("remote_sha256")
        local_updated_at = local_file_updated_at(destination)
        unresolved_reason = state.unresolved_save_conflicts.get(save.save_id)
        if (
            offline_title_pending
            and unresolved_reason is None
            and local_sha is not None
            and local_sha != save.sha256
            and lineage_local_sha is None
            and lineage_remote_sha is None
        ):
            timestamp_decision = resolve_missed_upload_timestamp_decision(
                mode=config.save_sync.mode,
                unresolved_reason=MISSED_POSTEXIT_UPLOAD_REASON,
                local_updated_at=local_updated_at,
                remote_updated_at=save.updated_at,
            )
            if timestamp_decision is not None:
                state.unresolved_save_conflicts[save.save_id] = MISSED_POSTEXIT_UPLOAD_REASON
                unresolved_reason = MISSED_POSTEXIT_UPLOAD_REASON
                state_changed = True
            else:
                needs_offline_title = True
        decision, reason = resolve_save_action(
            save_sha256=save.sha256,
            local_sha256=local_sha,
            mode=config.save_sync.mode,
            conflict_policy=config.save_sync.conflict_policy,
            lineage_local_sha=lineage_local_sha,
            lineage_remote_sha=lineage_remote_sha,
            unresolved_reason=unresolved_reason,
            local_updated_at=local_updated_at,
            remote_updated_at=save.updated_at,
        )
        if decision == "conflict":
            state.unresolved_save_conflicts[save.save_id] = reason
            allow_postexit_upload = False
            state_changed = True
        elif decision == "download":
            try:
                stream_to_destination_atomic(
                    server_url=config.server_url,
                    url=f"/v1/saves/{save.save_id}",
                    destination=destination,
                    expected_sha256=save.sha256,
                    timeout_seconds=config.index_timeout_seconds if config.index_timeout_seconds is not None else 30.0,
                )
                local_sha = local_file_sha256(destination)
                if local_sha is not None:
                    _record_shortcut_save_sync(state, save, destination, local_sha256=local_sha)
                    state_changed = True
            except Exception as exc:  # noqa: BLE001
                warn_shortcut_runtime(f"pre-launch save sync failed for {save.save_id} ({exc})")
        if verbose or audit:
            action_label = "keep-local" if decision == "upload_existing" else decision
            print(f"shortcut-save\tprelaunch\t{action_label}\t{save.save_id}\t{reason}")
        context.save_snapshots[save.save_id] = ShortcutSaveSnapshot(
            destination=destination,
            local_sha256=local_sha,
            remote_sha256=save.sha256,
            allow_postexit_upload=allow_postexit_upload,
            pending_postexit_upload=decision == "upload_existing",
        )
    if offline_title_pending and not needs_offline_title:
        state_changed = _clear_offline_shortcut_title(state, title_id=payload.title_id) or state_changed
    return context, state_changed


def run_shortcut_postexit_save_sync(
    *,
    payload: ShortcutLaunchPayload,
    config: GamehubConfig,
    state: Any,
    context: ShortcutSaveContext,
    resolve_executable: Callable[[str], str],
    verbose: bool,
    audit: bool,
) -> bool:
    if config.save_sync.mode != "bidirectional" or (
        not context.save_snapshots and not context.exact_binding_snapshots and not context.tree_snapshots
    ):
        return False
    if not should_sync_shortcut_saves(payload, config):
        return False
    if not _shortcut_server_reachable_or_warn(config):
        missed_upload_changed = _mark_missed_postexit_uploads_from_snapshots(
            state=state,
            context=context,
            verbose=verbose,
            audit=audit,
        )
        if verbose or audit:
            print("shortcut-save\tpostexit\tskip\tserver-unreachable")
        return missed_upload_changed

    if payload.title_id is None:
        return False
    index = _load_shortcut_index_or_warn(config, verbose=verbose)
    if index is None:
        return _mark_missed_postexit_uploads_from_snapshots(
            state=state,
            context=context,
            verbose=verbose,
            audit=audit,
        )

    current_saves = {save.save_id: save for save in _iter_title_saves(index, payload.title_id)}
    state_changed = False
    for save_id, snapshot in context.save_snapshots.items():
        if snapshot.destination is None or not snapshot.allow_postexit_upload:
            continue
        local_sha = local_file_sha256(snapshot.destination)
        if local_sha is None:
            continue
        if not _should_attempt_postexit_upload(snapshot, local_sha=local_sha):
            continue
        save = current_saves.get(save_id)
        if save is None or save.sha256 != snapshot.remote_sha256:
            state.unresolved_save_conflicts[save_id] = "remote-changed-during-session"
            state_changed = True
            if verbose or audit:
                print(f"shortcut-save\tpostexit\tconflict\t{save_id}\tremote-changed-during-session")
            continue
        try:
            updated_save = _upload_save_from_path(
                server_url=config.server_url,
                save=save,
                source=snapshot.destination,
                timeout_seconds=config.index_timeout_seconds if config.index_timeout_seconds is not None else 30.0,
            )
            record_uploaded_save(
                state=state,
                save_id=save_id,
                destination=snapshot.destination,
                save=updated_save,
            )
            state_changed = True
            if verbose or audit:
                print(f"shortcut-save\tpostexit\tupload\t{save_id}\tauto-upload")
        except SaveUploadConflictError as exc:
            if (
                reconcile_upload_conflict(
                    state=state,
                    save_id=save_id,
                    destination=snapshot.destination,
                    exc=exc,
                )
                is not None
            ):
                state_changed = True
                if verbose or audit:
                    print(f"shortcut-save\tpostexit\tskip\t{save_id}\talready-synced")
                continue
            state.unresolved_save_conflicts[save_id] = str(exc)
            state_changed = True
            if verbose or audit:
                print(f"shortcut-save\tpostexit\tconflict\t{save_id}\t{exc}")
        except Exception as exc:  # noqa: BLE001
            if local_sha is not None and not _shortcut_server_reachable_or_warn(config):
                state_changed = (
                    _record_missed_postexit_upload(
                        state,
                        save_id=save_id,
                        destination=snapshot.destination,
                        local_sha256=local_sha,
                    )
                    or state_changed
                )
                if verbose or audit:
                    print(f"shortcut-save\tpostexit\tdefer\t{save_id}\t{MISSED_POSTEXIT_UPLOAD_REASON}")
            warn_shortcut_runtime(f"post-exit save upload failed for {save_id} ({exc})")

    exact_binding_changed = _run_shortcut_postexit_exact_binding_sync(
        state=state,
        current_saves=current_saves,
        exact_snapshots=context.exact_binding_snapshots,
        resolve_executable=resolve_executable,
        server_url=config.server_url,
        timeout_seconds=config.index_timeout_seconds if config.index_timeout_seconds is not None else 30.0,
        verbose=verbose,
        audit=audit,
    )
    state_changed = state_changed or exact_binding_changed

    for binding_id, tree_snapshot in context.tree_snapshots.items():
        binding = tree_snapshot.binding
        after = snapshot_binding_tree(binding, resolve_executable=resolve_executable)
        changed_paths = _changed_tree_paths(tree_snapshot.before, after)
        learned_paths = changed_paths if changed_paths else tuple(sorted(after))
        if not learned_paths:
            continue
        learned_root = learn_binding_root(binding, learned_paths)
        if learned_root is None:
            previous_reason = state.unresolved_save_conflicts.get(binding_id)
            state.unresolved_save_conflicts[binding_id] = "save-binding-root-ambiguous"
            state_changed = state_changed or previous_reason != "save-binding-root-ambiguous"
            if verbose or audit:
                print(f"shortcut-save\tpostexit\tconflict\t{binding_id}\tsave-binding-root-ambiguous")
            continue
        canonical_root, materialized_root = learned_root
        next_root = {"canonical_root": canonical_root, "materialized_root": materialized_root}
        if state.save_binding_roots.get(binding.binding_id) != next_root:
            _record_binding_root(
                state,
                binding_id=binding.binding_id,
                canonical_root=canonical_root,
                materialized_root=materialized_root,
            )
            state_changed = True
        if state.unresolved_save_conflicts.pop(binding_id, None) is not None:
            state_changed = True
        root = resolve_binding_local_root(binding, resolve_executable=resolve_executable)
        if root is None:
            continue
        candidate_paths = tuple(
            rel_path
            for rel_path in sorted(after)
            if canonical_suffix_for_learned_path(
                binding,
                rel_path,
                materialized_root=materialized_root,
            )
            is not None
        )
        for rel_path in candidate_paths:
            canonical_suffix = canonical_suffix_for_learned_path(
                binding,
                rel_path,
                materialized_root=materialized_root,
            )
            if canonical_suffix is None:
                continue
            save_id = make_save_id(f"{binding.server_rel_dir}/{canonical_suffix}")
            if save_id in current_saves:
                continue
            source = root / Path(*PurePosixPath(rel_path).parts)
            local_sha = local_file_sha256(source)
            if local_sha is None:
                continue
            try:
                created_save = _upload_new_save_from_path(
                    server_url=config.server_url,
                    save_id=save_id,
                    binding=binding,
                    canonical_suffix=canonical_suffix,
                    source=source,
                    timeout_seconds=config.index_timeout_seconds if config.index_timeout_seconds is not None else 30.0,
                )
                record_uploaded_save(
                    state=state,
                    save_id=save_id,
                    destination=source,
                    save=created_save,
                )
                state_changed = True
                if verbose or audit:
                    action = "auto-create" if rel_path in changed_paths else "auto-create-existing-local"
                    print(f"shortcut-save\tpostexit\tupload\t{save_id}\t{action}")
            except SaveUploadConflictError as exc:
                if (
                    reconcile_upload_conflict(
                        state=state,
                        save_id=save_id,
                        destination=source,
                        exc=exc,
                    )
                    is not None
                ):
                    state_changed = True
                    if verbose or audit:
                        print(f"shortcut-save\tpostexit\tskip\t{save_id}\talready-synced")
                    continue
                state.unresolved_save_conflicts[save_id] = "create-race-or-upload-failed"
                state_changed = True
                warn_shortcut_runtime(f"post-exit save upload failed for {save_id} ({exc})")
            except Exception as exc:  # noqa: BLE001
                state.unresolved_save_conflicts[save_id] = "create-race-or-upload-failed"
                state_changed = True
                warn_shortcut_runtime(f"post-exit save upload failed for {save_id} ({exc})")
    return state_changed
