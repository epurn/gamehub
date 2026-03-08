from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gamehub_common.models import SaveSpec

from ..common.save_sync import (
    local_file_sha256,
    local_file_updated_at,
    record_converged_save_state,
)
from .planner import SavePlanAction, SyncPlan
from .state import SyncState
from .transfer import SaveUploadConflictError, stream_to_destination_atomic, upload_file_to_server


@dataclass(frozen=True)
class SaveStageResult:
    planned: int
    downloaded: int
    uploaded: int
    conflicts: int
    skipped: int


class SaveStageError(RuntimeError):
    """Raised when one or more save transfers fail."""


def _record_converged_save(
    state: SyncState,
    action: SavePlanAction,
    *,
    local_sha256: str,
    remote_sha256: str,
    local_updated_at: str | None,
    remote_updated_at: str,
) -> None:
    record_converged_save_state(
        save_id=action.save_id,
        save_checksums=state.save_checksums,
        save_lineage=state.save_lineage,
        unresolved_save_conflicts=state.unresolved_save_conflicts,
        local_sha256=local_sha256,
        remote_sha256=remote_sha256,
        local_updated_at=local_updated_at,
        remote_updated_at=remote_updated_at,
    )


def _print_save_action(action: SavePlanAction) -> None:
    destination = action.destination if action.destination is not None else "<save-path-unavailable>"
    print(f"save\t{action.decision}\t{action.system}\t{action.title_id}\t{action.kind}\t{action.reason}\t{destination}")


def record_uploaded_save(
    *,
    state: Any,
    save_id: str,
    destination: Path,
    save: SaveSpec,
) -> str:
    local_sha = local_file_sha256(destination)
    if local_sha is None:
        raise ValueError("Uploaded save missing after local upload")
    record_converged_save_state(
        save_id=save_id,
        save_checksums=state.save_checksums,
        save_lineage=state.save_lineage,
        unresolved_save_conflicts=state.unresolved_save_conflicts,
        local_sha256=local_sha,
        remote_sha256=save.sha256,
        local_updated_at=local_file_updated_at(destination),
        remote_updated_at=save.updated_at.isoformat(),
    )
    return local_sha


def reconcile_upload_conflict(
    *,
    state: Any,
    save_id: str,
    destination: Path,
    exc: SaveUploadConflictError,
) -> SaveSpec | None:
    current_payload = exc.payload.get("current")
    current = SaveSpec.model_validate(current_payload) if isinstance(current_payload, dict) else None
    local_sha = local_file_sha256(destination)
    if current is None or local_sha is None or current.sha256 != local_sha:
        return None
    record_converged_save_state(
        save_id=save_id,
        save_checksums=state.save_checksums,
        save_lineage=state.save_lineage,
        unresolved_save_conflicts=state.unresolved_save_conflicts,
        local_sha256=local_sha,
        remote_sha256=current.sha256,
        local_updated_at=local_file_updated_at(destination),
        remote_updated_at=current.updated_at.isoformat(),
    )
    return current


def apply_save_stage(
    *,
    server_url: str,
    plan: SyncPlan,
    state: SyncState,
    timeout_seconds: float,
    dry_run: bool,
    verbose: bool = False,
) -> SaveStageResult:
    downloaded = 0
    uploaded = 0
    conflicts = 0
    skipped = 0
    failures: list[tuple[str, str]] = []

    for action in plan.save_actions:
        if verbose or dry_run:
            _print_save_action(action)

        if action.decision == "skip":
            skipped += 1
            continue
        if action.decision in {"upload_existing", "upload_new"}:
            if dry_run:
                uploaded += 1
                continue
            if action.destination is None:
                failures.append((action.save_id, "save-path-unavailable"))
                continue
            try:
                payload = upload_file_to_server(
                    server_url=server_url,
                    url=action.url,
                    source=action.destination,
                    binding_id=action.binding_id,
                    canonical_suffix=action.canonical_suffix,
                    timeout_seconds=timeout_seconds,
                    expected_remote_sha256=action.expected_sha256 if action.decision == "upload_existing" else None,
                )
                save = SaveSpec.model_validate(payload)
                record_uploaded_save(state=state, save_id=action.save_id, destination=action.destination, save=save)
                uploaded += 1
            except SaveUploadConflictError as exc:
                if (
                    reconcile_upload_conflict(
                        state=state,
                        save_id=action.save_id,
                        destination=action.destination,
                        exc=exc,
                    )
                    is not None
                ):
                    uploaded += 1
                    continue
                state.unresolved_save_conflicts[action.save_id] = str(exc)
                conflicts += 1
            except Exception as exc:  # noqa: BLE001
                failures.append((action.save_id, str(exc)))
            continue
        if action.decision == "conflict":
            state.unresolved_save_conflicts[action.save_id] = action.reason
            conflicts += 1
            continue
        if action.decision != "download":
            skipped += 1
            continue

        if dry_run:
            downloaded += 1
            continue
        if action.destination is None:
            failures.append((action.save_id, "save-path-unavailable"))
            continue

        try:
            stream_to_destination_atomic(
                server_url=server_url,
                url=action.url,
                destination=action.destination,
                expected_sha256=action.expected_sha256,
                timeout_seconds=timeout_seconds,
            )
            _record_converged_save(
                state,
                action,
                local_sha256=action.expected_sha256,
                remote_sha256=action.expected_sha256,
                local_updated_at=local_file_updated_at(action.destination),
                remote_updated_at=action.remote_updated_at,
            )
            downloaded += 1
        except Exception as exc:  # noqa: BLE001
            failures.append((action.save_id, str(exc)))

    print(
        "Save sync summary:"
        f" planned={len(plan.save_actions)}"
        f" downloaded={downloaded}"
        f" uploaded={uploaded}"
        f" conflicts={conflicts}"
        f" skipped={skipped}"
    )

    if failures:
        details = "; ".join(f"{save_id}: {message}" for save_id, message in failures)
        raise SaveStageError(f"Save sync failed for {len(failures)} item(s): {details}")

    return SaveStageResult(
        planned=len(plan.save_actions),
        downloaded=downloaded,
        uploaded=uploaded,
        conflicts=conflicts,
        skipped=skipped,
    )
