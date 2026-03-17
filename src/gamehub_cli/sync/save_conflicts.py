from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..common.save_sync import local_file_updated_at, record_converged_save_state
from .planner import SavePlanAction, SyncPlan
from .state import MISSED_POSTEXIT_UPLOAD_REASON, SyncState

PersistedConflictScope = Literal["save", "binding"]

_TRANSIENT_ORPHAN_SAVE_CONFLICT_REASONS = frozenset(
    {
        MISSED_POSTEXIT_UPLOAD_REASON,
        "remote-changed-during-session",
    }
)


@dataclass(frozen=True)
class PersistedConflictRecord:
    conflict_id: str
    reason: str
    scope: PersistedConflictScope


@dataclass(frozen=True)
class PersistedConflictCleanupCandidate(PersistedConflictRecord):
    action: SavePlanAction | None = None


@dataclass(frozen=True)
class PersistedConflictClassification:
    actionable_save_conflicts: tuple[PersistedConflictRecord, ...]
    actionable_binding_conflicts: tuple[PersistedConflictRecord, ...]
    cleanup_candidates: tuple[PersistedConflictCleanupCandidate, ...]

    @property
    def actionable_conflicts(self) -> tuple[PersistedConflictRecord, ...]:
        return self.actionable_save_conflicts + self.actionable_binding_conflicts


def _conflict_scope(conflict_id: str, reason: str) -> PersistedConflictScope:
    if reason == "save-binding-root-ambiguous" or conflict_id.startswith("savebind_"):
        return "binding"
    return "save"


def _is_transient_orphan_save_reason(reason: str) -> bool:
    return reason.startswith("create-race-") or reason in _TRANSIENT_ORPHAN_SAVE_CONFLICT_REASONS


def classify_persisted_save_conflicts(
    *,
    state: SyncState,
    plan: SyncPlan,
) -> PersistedConflictClassification:
    actionable_save_conflicts: list[PersistedConflictRecord] = []
    actionable_binding_conflicts: list[PersistedConflictRecord] = []
    cleanup_candidates: list[PersistedConflictCleanupCandidate] = []
    actions_by_save_id = {action.save_id: action for action in plan.save_actions}
    actions_by_binding_id: dict[str, list[SavePlanAction]] = {}
    for action in plan.save_actions:
        actions_by_binding_id.setdefault(action.binding_id, []).append(action)

    for conflict_id, reason in sorted(state.unresolved_save_conflicts.items()):
        scope = _conflict_scope(conflict_id, reason)
        if scope == "binding":
            binding_actions = actions_by_binding_id.get(conflict_id, [])
            if not binding_actions or all(
                action.decision == "skip" and action.reason == "already-synced" for action in binding_actions
            ):
                cleanup_candidates.append(
                    PersistedConflictCleanupCandidate(conflict_id=conflict_id, reason=reason, scope=scope)
                )
                continue
            actionable_binding_conflicts.append(
                PersistedConflictRecord(conflict_id=conflict_id, reason=reason, scope=scope)
            )
            continue

        save_action = actions_by_save_id.get(conflict_id)
        if save_action is None:
            if _is_transient_orphan_save_reason(reason):
                cleanup_candidates.append(
                    PersistedConflictCleanupCandidate(conflict_id=conflict_id, reason=reason, scope=scope)
                )
                continue
            actionable_save_conflicts.append(
                PersistedConflictRecord(conflict_id=conflict_id, reason=reason, scope=scope)
            )
            continue
        if save_action.decision == "skip" and save_action.reason == "already-synced":
            cleanup_candidates.append(
                PersistedConflictCleanupCandidate(
                    conflict_id=conflict_id,
                    reason=reason,
                    scope=scope,
                    action=save_action,
                )
            )
            continue
        actionable_save_conflicts.append(PersistedConflictRecord(conflict_id=conflict_id, reason=reason, scope=scope))

    return PersistedConflictClassification(
        actionable_save_conflicts=tuple(actionable_save_conflicts),
        actionable_binding_conflicts=tuple(actionable_binding_conflicts),
        cleanup_candidates=tuple(cleanup_candidates),
    )


def prune_persisted_save_conflicts(
    *,
    state: SyncState,
    plan: SyncPlan,
) -> PersistedConflictClassification:
    classification = classify_persisted_save_conflicts(state=state, plan=plan)
    for candidate in classification.cleanup_candidates:
        action = candidate.action
        if action is not None and action.destination is not None:
            local_sha = action.local_sha256 or action.expected_sha256
            record_converged_save_state(
                save_id=candidate.conflict_id,
                save_checksums=state.save_checksums,
                save_lineage=state.save_lineage,
                unresolved_save_conflicts=state.unresolved_save_conflicts,
                local_sha256=local_sha,
                remote_sha256=action.expected_sha256,
                local_updated_at=local_file_updated_at(action.destination),
                remote_updated_at=action.remote_updated_at,
            )
            continue
        state.unresolved_save_conflicts.pop(candidate.conflict_id, None)
    return classification
