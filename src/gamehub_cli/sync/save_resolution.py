from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin

from gamehub_common.models import LibraryIndex, SaveBindingCatalog, SaveBindingSpec, SaveSpec

from ..common.config import GamehubConfig
from ..common.save_sync import (
    canonical_suffix_for_save,
    local_file_sha256,
    local_file_updated_at,
    save_binding_id_for_save,
)
from ..emulators.save_resolution import resolve_local_save_destination
from . import index as sync_index
from .planner import SavePlanAction, SyncPlan, create_sync_plan
from .save_stage import _record_converged_save, reconcile_upload_conflict, record_uploaded_save
from .state import SyncState, load_state, save_state_atomic
from .transfer import SaveUploadConflictError, stream_to_destination_atomic, upload_file_to_server

SaveResolutionChoice = Literal["keep-local", "keep-server"]

_BENIGN_SAVE_SKIP_REASONS = frozenset({"already-synced", "save-sync-disabled", "system-filtered"})


@dataclass(frozen=True)
class SaveResolutionContext:
    state: SyncState
    index: LibraryIndex
    save_bindings: SaveBindingCatalog
    plan: SyncPlan
    save: SaveSpec | None
    action: SavePlanAction | None
    destination: Path | None
    persisted_reason: str | None


def _transfer_timeout_seconds(verbose: bool) -> float:
    return 60.0 if verbose else 30.0


def _load_validated_index(config: GamehubConfig, *, timeout_seconds: float, verbose: bool) -> LibraryIndex:
    index_url = urljoin(config.server_url.rstrip("/") + "/", "v1/index")
    raw_index = sync_index.fetch_index_with_retries(
        index_url=index_url,
        timeout_seconds=timeout_seconds,
        attempts=config.index_fetch_attempts,
        retry_backoff_seconds=config.index_retry_backoff_seconds,
        verbose=verbose,
        http_client_module=sync_index.httpx,
        sleep_func=time.sleep,
        reporter=print,
    )
    return LibraryIndex.model_validate(raw_index)


def _load_validated_save_bindings(
    config: GamehubConfig, *, timeout_seconds: float, verbose: bool
) -> SaveBindingCatalog:
    bindings_url = urljoin(config.server_url.rstrip("/") + "/", "v1/save-bindings")
    raw_bindings = sync_index.fetch_save_bindings_with_retries(
        bindings_url=bindings_url,
        timeout_seconds=timeout_seconds,
        attempts=config.index_fetch_attempts,
        retry_backoff_seconds=config.index_retry_backoff_seconds,
        verbose=verbose,
        http_client_module=sync_index.httpx,
        sleep_func=time.sleep,
        reporter=print,
    )
    return SaveBindingCatalog.model_validate(raw_bindings)


def _resolve_action(
    *,
    plan: SyncPlan,
    index: LibraryIndex,
    state: SyncState,
    save_bindings: SaveBindingCatalog,
    save_id: str,
) -> tuple[SaveSpec | None, SavePlanAction | None, Path | None]:
    action = next((item for item in plan.save_actions if item.save_id == save_id), None)
    save = next((item for item in index.saves if item.save_id == save_id), None)

    if action is not None:
        return save, action, action.destination
    if save is None:
        return None, None, None

    binding_map = {binding.binding_id: binding for binding in save_bindings.bindings}
    binding: SaveBindingSpec | None = binding_map.get(save_binding_id_for_save(save))
    destination = resolve_local_save_destination(
        save,
        binding_roots=state.save_binding_roots,
        binding=binding,
    )
    return save, None, destination


def _is_action_interesting(action: SavePlanAction | None, persisted_reason: str | None) -> bool:
    if persisted_reason is not None:
        return True
    if action is None:
        return False
    return action.decision != "skip" or action.reason not in _BENIGN_SAVE_SKIP_REASONS


def _load_resolution_context(
    config: GamehubConfig,
    *,
    save_id: str,
    verify: bool,
    verbose: bool,
) -> SaveResolutionContext:
    state = load_state(config.state_path)
    timeout_seconds = (
        config.index_timeout_seconds if config.index_timeout_seconds is not None else _transfer_timeout_seconds(verbose)
    )
    index = _load_validated_index(config, timeout_seconds=timeout_seconds, verbose=verbose)
    save_bindings = _load_validated_save_bindings(config, timeout_seconds=timeout_seconds, verbose=verbose)
    plan = create_sync_plan(index=index, config=config, state=state, verify=verify, save_bindings=save_bindings)
    persisted_reason = state.unresolved_save_conflicts.get(save_id)
    save, action, destination = _resolve_action(
        plan=plan,
        index=index,
        state=state,
        save_bindings=save_bindings,
        save_id=save_id,
    )
    return SaveResolutionContext(
        state=state,
        index=index,
        save_bindings=save_bindings,
        plan=plan,
        save=save,
        action=action,
        destination=destination,
        persisted_reason=persisted_reason,
    )


def _describe_current_state(save_id: str, context: SaveResolutionContext, *, choice: SaveResolutionChoice) -> None:
    action = context.action
    destination = "<save-path-unavailable>" if context.destination is None else context.destination
    print(
        "save-resolve\t"
        f"choice={choice}\t"
        f"id={save_id}\t"
        f"persisted_reason={context.persisted_reason or '-'}\t"
        f"current_decision={(action.decision if action is not None else '-')}\t"
        f"current_reason={(action.reason if action is not None else '-')}\t"
        f"target={destination}"
    )


def _expected_remote_sha256(action: SavePlanAction | None, save: SaveSpec | None) -> str | None:
    if action is not None and action.decision == "upload_new":
        return None
    if save is None:
        return None
    return save.sha256


def _resolve_keep_server(
    *,
    config: GamehubConfig,
    context: SaveResolutionContext,
    save_id: str,
    dry_run: bool,
    verbose: bool,
) -> int:
    if context.save is None:
        raise ValueError(f"Save not found in current index: {save_id}")
    if context.destination is None:
        raise ValueError(f"Local path is unavailable for save: {save_id}")
    if context.action is not None and context.action.decision == "upload_new":
        raise ValueError(f"Server copy is unavailable for local-only save: {save_id}")

    destination = context.destination
    remote_updated_at = (
        context.action.remote_updated_at if context.action is not None else context.save.updated_at.isoformat()
    )
    if dry_run:
        print(f"save-resolve\tpreview\tchoice=keep-server\tid={save_id}\ttarget={destination}")
        return 0

    try:
        stream_to_destination_atomic(
            server_url=config.server_url,
            url=f"/v1/saves/{save_id}",
            destination=destination,
            expected_sha256=context.save.sha256,
            timeout_seconds=config.index_timeout_seconds
            if config.index_timeout_seconds is not None
            else _transfer_timeout_seconds(verbose),
            backup_keep_limit=config.backups.keep_limit,
        )
        _record_converged_save(
            context.state,
            context.action
            if context.action is not None
            else SavePlanAction(
                save_id=save_id,
                binding_id=save_binding_id_for_save(context.save),
                title_id=context.save.title_id,
                system=context.save.system,
                kind=context.save.kind,
                decision="download",
                reason="manual-keep-server",
                url=f"/v1/saves/{save_id}",
                destination=destination,
                canonical_suffix=canonical_suffix_for_save(context.save),
                expected_sha256=context.save.sha256,
                size_bytes=context.save.size_bytes,
                remote_updated_at=remote_updated_at,
            ),
            local_sha256=context.save.sha256,
            remote_sha256=context.save.sha256,
            local_updated_at=local_file_updated_at(destination),
            remote_updated_at=remote_updated_at,
        )
        save_state_atomic(config.state_path, context.state, keep_limit=config.backups.keep_limit)
    except Exception as exc:  # noqa: BLE001
        print(f"save-resolve\terror\tchoice=keep-server\tid={save_id}\treason={exc}")
        return 1

    print(f"save-resolve\tapplied\tchoice=keep-server\tid={save_id}\ttarget={destination}")
    return 0


def _resolve_keep_local(
    *,
    config: GamehubConfig,
    context: SaveResolutionContext,
    save_id: str,
    dry_run: bool,
    verbose: bool,
) -> int:
    destination = context.destination
    if destination is None:
        raise ValueError(f"Local path is unavailable for save: {save_id}")
    if local_file_sha256(destination) is None:
        raise ValueError(f"Local save is missing or unreadable: {destination}")

    binding_id = (
        context.action.binding_id
        if context.action is not None
        else (save_binding_id_for_save(context.save) if context.save is not None else None)
    )
    canonical_suffix = (
        context.action.canonical_suffix
        if context.action is not None
        else (canonical_suffix_for_save(context.save) if context.save is not None else None)
    )
    if binding_id is None or canonical_suffix is None:
        raise ValueError(f"Save binding metadata is unavailable for save: {save_id}")

    if dry_run:
        print(f"save-resolve\tpreview\tchoice=keep-local\tid={save_id}\ttarget={destination}")
        return 0

    try:
        payload = upload_file_to_server(
            server_url=config.server_url,
            url=f"/v1/saves/{save_id}",
            source=destination,
            binding_id=binding_id,
            canonical_suffix=canonical_suffix,
            timeout_seconds=config.index_timeout_seconds
            if config.index_timeout_seconds is not None
            else _transfer_timeout_seconds(verbose),
            expected_remote_sha256=_expected_remote_sha256(context.action, context.save),
        )
        uploaded = SaveSpec.model_validate(payload)
        record_uploaded_save(state=context.state, save_id=save_id, destination=destination, save=uploaded)
        save_state_atomic(config.state_path, context.state, keep_limit=config.backups.keep_limit)
    except SaveUploadConflictError as exc:
        if (
            reconcile_upload_conflict(
                state=context.state,
                save_id=save_id,
                destination=destination,
                exc=exc,
            )
            is not None
        ):
            save_state_atomic(config.state_path, context.state, keep_limit=config.backups.keep_limit)
            print(f"save-resolve\tapplied\tchoice=keep-local\tid={save_id}\tresult=already-synced")
            return 0
        context.state.unresolved_save_conflicts[save_id] = str(exc)
        save_state_atomic(config.state_path, context.state, keep_limit=config.backups.keep_limit)
        print(f"save-resolve\tconflict\tchoice=keep-local\tid={save_id}\treason={exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"save-resolve\terror\tchoice=keep-local\tid={save_id}\treason={exc}")
        return 1

    print(f"save-resolve\tapplied\tchoice=keep-local\tid={save_id}\ttarget={destination}")
    return 0


def run_save_resolution(
    config: GamehubConfig,
    *,
    save_id: str,
    choice: SaveResolutionChoice,
    dry_run: bool,
    verbose: bool,
    verify: bool,
) -> int:
    context = _load_resolution_context(config, save_id=save_id, verify=verify, verbose=verbose)
    _describe_current_state(save_id, context, choice=choice)
    if context.save is None and context.action is None:
        raise ValueError(f"Save not found in current plan or index: {save_id}")
    if not _is_action_interesting(context.action, context.persisted_reason):
        raise ValueError(f"Save does not currently require operator resolution: {save_id}")
    if choice == "keep-server":
        return _resolve_keep_server(
            config=config,
            context=context,
            save_id=save_id,
            dry_run=dry_run,
            verbose=verbose,
        )
    return _resolve_keep_local(
        config=config,
        context=context,
        save_id=save_id,
        dry_run=dry_run,
        verbose=verbose,
    )
