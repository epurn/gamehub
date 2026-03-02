from __future__ import annotations

from dataclasses import dataclass

from .planner import SavePlanAction, SyncPlan
from .state import SyncState
from .transfer import stream_to_destination_atomic


@dataclass(frozen=True)
class SaveStageResult:
    planned: int
    downloaded: int
    uploaded: int
    conflicts: int
    skipped: int


class SaveStageError(RuntimeError):
    """Raised when one or more save transfers fail."""


def _record_downloaded_save(state: SyncState, action: SavePlanAction) -> None:
    state.save_checksums[action.save_id] = action.expected_sha256
    state.save_lineage[action.save_id] = {
        "local_sha256": action.expected_sha256,
        "remote_sha256": action.expected_sha256,
        "remote_updated_at": action.remote_updated_at,
    }
    state.unresolved_save_conflicts.pop(action.save_id, None)


def _print_save_action(action: SavePlanAction) -> None:
    print(
        "save"
        f"\t{action.decision}"
        f"\t{action.system}"
        f"\t{action.title_id}"
        f"\t{action.kind}"
        f"\t{action.reason}"
        f"\t{action.destination}"
    )


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
            failures.append((action.save_id, "upload-not-implemented"))
            continue
        if action.decision == "conflict":
            conflicts += 1
            continue
        if action.decision != "download":
            skipped += 1
            continue

        if dry_run:
            continue

        try:
            stream_to_destination_atomic(
                server_url=server_url,
                url=action.url,
                destination=action.destination,
                expected_sha256=action.expected_sha256,
                timeout_seconds=timeout_seconds,
            )
            _record_downloaded_save(state, action)
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
