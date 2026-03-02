from __future__ import annotations

from dataclasses import dataclass

from gamehub_common.models import SaveSpec

from ..common.save_sync import (
    build_save_lineage_record,
    local_file_sha256,
    local_file_updated_at,
    timestamp_now_utc,
)
from .planner import SavePlanAction, SyncPlan
from .state import SyncState
from .transfer import stream_to_destination_atomic, upload_file_to_server


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
    state.save_checksums[action.save_id] = local_sha256
    state.save_lineage[action.save_id] = build_save_lineage_record(
        local_sha256=local_sha256,
        remote_sha256=remote_sha256,
        local_updated_at=local_updated_at,
        remote_updated_at=remote_updated_at,
        synced_at=timestamp_now_utc(),
    )
    state.unresolved_save_conflicts.pop(action.save_id, None)


def _print_save_action(action: SavePlanAction) -> None:
    destination = action.destination if action.destination is not None else "<save-path-unavailable>"
    print(f"save\t{action.decision}\t{action.system}\t{action.title_id}\t{action.kind}\t{action.reason}\t{destination}")


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
        if action.decision == "upload":
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
                    timeout_seconds=timeout_seconds,
                )
                save = SaveSpec.model_validate(payload)
                local_sha = local_file_sha256(action.destination)
                if local_sha is None:
                    raise ValueError("Uploaded save missing after local upload")
                _record_converged_save(
                    state,
                    action,
                    local_sha256=local_sha,
                    remote_sha256=save.sha256,
                    local_updated_at=local_file_updated_at(action.destination),
                    remote_updated_at=save.updated_at.isoformat(),
                )
                uploaded += 1
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
