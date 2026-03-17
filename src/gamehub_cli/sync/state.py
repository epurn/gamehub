from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from logging import getLogger
from pathlib import Path
from typing import cast

from ..common.fsops import DEFAULT_BACKUP_KEEP_LIMIT, backup_existing_file, replace_file
from ..common.save_sync import SaveBindingRootRecord, SaveLineageRecord

BOOTSTRAP_VERSION = 1
MISSED_POSTEXIT_UPLOAD_REASON = "postexit-upload-missed-server-unreachable"
logger = getLogger(__name__)


@dataclass
class SyncState:
    downloaded_checksums: dict[str, str] = field(default_factory=dict)
    firmware_checksums: dict[str, str] = field(default_factory=dict)
    save_checksums: dict[str, str] = field(default_factory=dict)
    save_lineage: dict[str, SaveLineageRecord] = field(default_factory=dict)
    save_binding_roots: dict[str, SaveBindingRootRecord] = field(default_factory=dict)
    offline_shortcut_titles: dict[str, str] = field(default_factory=dict)
    unresolved_save_conflicts: dict[str, str] = field(default_factory=dict)
    last_sync: str | None = None
    bootstrap_version: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "SyncState":
        return cls(
            downloaded_checksums=dict(data.get("downloaded_checksums", {})),
            firmware_checksums=dict(data.get("firmware_checksums", {})),
            save_checksums=dict(data.get("save_checksums", {})),
            save_lineage={
                save_id: cast(SaveLineageRecord, dict(lineage))
                for save_id, lineage in dict(data.get("save_lineage", {})).items()
                if isinstance(save_id, str) and isinstance(lineage, dict)
            },
            save_binding_roots={
                binding_id: cast(SaveBindingRootRecord, dict(root))
                for binding_id, root in dict(data.get("save_binding_roots", {})).items()
                if isinstance(binding_id, str) and isinstance(root, dict)
            },
            offline_shortcut_titles=dict(data.get("offline_shortcut_titles", {})),
            unresolved_save_conflicts=dict(data.get("unresolved_save_conflicts", {})),
            last_sync=data.get("last_sync"),
            bootstrap_version=data.get("bootstrap_version"),
        )

    def to_dict(self) -> dict:
        return {
            "downloaded_checksums": self.downloaded_checksums,
            "firmware_checksums": self.firmware_checksums,
            "save_checksums": self.save_checksums,
            "save_lineage": self.save_lineage,
            "save_binding_roots": self.save_binding_roots,
            "offline_shortcut_titles": self.offline_shortcut_titles,
            "unresolved_save_conflicts": self.unresolved_save_conflicts,
            "last_sync": self.last_sync,
            "bootstrap_version": self.bootstrap_version,
        }


def load_state(path: Path) -> SyncState:
    if not path.exists():
        return SyncState()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return SyncState.from_dict(raw)


def save_state_atomic(path: Path, state: SyncState, *, keep_limit: int = DEFAULT_BACKUP_KEEP_LIMIT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_result = backup_existing_file(path, keep_limit=keep_limit)
    if backup_result.created_path is not None:
        logger.info("sync state backup created path=%s backup=%s", path, backup_result.created_path)
    for pruned_path in backup_result.pruned_paths:
        logger.info("sync state backup pruned path=%s pruned_backup=%s", path, pruned_path)

    tmp = path.with_suffix(f"{path.suffix}.tmp")
    payload = json.dumps(state.to_dict(), indent=2, sort_keys=True)
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    replace_file(tmp, path)
    logger.info("sync state saved path=%s", path)


def mark_synced(state: SyncState) -> None:
    state.last_sync = datetime.now(timezone.utc).isoformat()


def mark_bootstrapped(state: SyncState) -> None:
    state.bootstrap_version = BOOTSTRAP_VERSION


def has_bootstrap_marker(state: SyncState) -> bool:
    return isinstance(state.bootstrap_version, int) and state.bootstrap_version >= BOOTSTRAP_VERSION
