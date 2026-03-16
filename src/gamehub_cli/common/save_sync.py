from __future__ import annotations

from collections.abc import MutableMapping
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import TypedDict

from gamehub_common.ids import make_save_binding_id, sha256_file
from gamehub_common.models import SaveSpec


class SaveLineageRecord(TypedDict, total=False):
    local_sha256: str
    remote_sha256: str
    local_updated_at: str
    remote_updated_at: str
    synced_at: str


class SaveBindingRootRecord(TypedDict):
    canonical_root: str
    materialized_root: str


def timestamp_now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_utc_timestamp(value: object) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def local_file_sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    return sha256_file(path)


def local_file_updated_at(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _resolve_conflict_policy_outcome(
    conflict_policy: str,
    *,
    prefer_server: tuple[str, str],
    prefer_local: tuple[str, str],
    manual: tuple[str, str],
) -> tuple[str, str]:
    if conflict_policy == "prefer_server":
        return prefer_server
    if conflict_policy == "prefer_local":
        return prefer_local
    return manual


def classify_save_action(
    *,
    save_sha256: str,
    local_sha256: str | None,
    mode: str,
    conflict_policy: str,
    lineage_local_sha: str | None,
    lineage_remote_sha: str | None,
) -> tuple[str, str]:
    if local_sha256 is None:
        return "download", "local-missing"
    if local_sha256 == save_sha256:
        return "skip", "already-synced"
    if mode == "download":
        return "skip", "download-mode-local-drift"

    lineage_present = lineage_local_sha is not None or lineage_remote_sha is not None
    if not lineage_present:
        return _resolve_conflict_policy_outcome(
            conflict_policy,
            prefer_server=("download", "lineage-missing-prefer-server"),
            prefer_local=("upload_existing", "lineage-missing-prefer-local"),
            manual=("conflict", "lineage-missing-manual"),
        )

    local_changed = lineage_local_sha is not None and local_sha256 != lineage_local_sha
    remote_changed = lineage_remote_sha is not None and save_sha256 != lineage_remote_sha

    if local_changed and not remote_changed:
        return "upload_existing", "local-changed-remote-unchanged"
    if remote_changed and not local_changed:
        return "download", "remote-changed-local-unchanged"
    if local_changed and remote_changed:
        return _resolve_conflict_policy_outcome(
            conflict_policy,
            prefer_server=("download", "both-changed-prefer-server"),
            prefer_local=("upload_existing", "both-changed-prefer-local"),
            manual=("conflict", "both-changed-manual"),
        )

    return _resolve_conflict_policy_outcome(
        conflict_policy,
        prefer_server=("download", "lineage-ambiguous-prefer-server"),
        prefer_local=("upload_existing", "lineage-ambiguous-prefer-local"),
        manual=("conflict", "lineage-ambiguous-manual"),
    )


def build_save_lineage_record(
    *,
    local_sha256: str,
    remote_sha256: str,
    local_updated_at: str | None,
    remote_updated_at: str,
    synced_at: str | None = None,
) -> SaveLineageRecord:
    synced = synced_at or timestamp_now_utc()
    return {
        "local_sha256": local_sha256,
        "remote_sha256": remote_sha256,
        "local_updated_at": local_updated_at or synced,
        "remote_updated_at": remote_updated_at,
        "synced_at": synced,
    }


def record_converged_save_state(
    *,
    save_id: str,
    save_checksums: MutableMapping[str, str],
    save_lineage: MutableMapping[str, SaveLineageRecord],
    unresolved_save_conflicts: MutableMapping[str, str],
    local_sha256: str,
    remote_sha256: str,
    local_updated_at: str | None,
    remote_updated_at: str,
) -> None:
    save_checksums[save_id] = local_sha256
    save_lineage[save_id] = build_save_lineage_record(
        local_sha256=local_sha256,
        remote_sha256=remote_sha256,
        local_updated_at=local_updated_at,
        remote_updated_at=remote_updated_at,
    )
    unresolved_save_conflicts.pop(save_id, None)


def save_binding_id_for_save(save: SaveSpec) -> str:
    return make_save_binding_id(save.title_id, save.kind)


def canonical_suffix_from_rel_path(rel_path: str) -> str:
    parts = tuple(part for part in PurePosixPath(rel_path).parts if part not in {"", "."})
    if len(parts) < 5:
        if not parts:
            raise ValueError(f"Save rel_path is missing canonical suffix: {rel_path}")
        return parts[-1]
    return PurePosixPath(*parts[4:]).as_posix()


def canonical_suffix_for_save(save: SaveSpec) -> str:
    return canonical_suffix_from_rel_path(save.rel_path)
