from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from ..common.fsops import replace_file
from ..common.save_sync import SaveLineageRecord

BOOTSTRAP_VERSION = 1


@dataclass
class SyncState:
    downloaded_checksums: dict[str, str] = field(default_factory=dict)
    firmware_checksums: dict[str, str] = field(default_factory=dict)
    save_checksums: dict[str, str] = field(default_factory=dict)
    save_lineage: dict[str, SaveLineageRecord] = field(default_factory=dict)
    unresolved_save_conflicts: dict[str, str] = field(default_factory=dict)
    tombstones: list[str] = field(default_factory=list)
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
            unresolved_save_conflicts=dict(data.get("unresolved_save_conflicts", {})),
            tombstones=list(data.get("tombstones", [])),
            last_sync=data.get("last_sync"),
            bootstrap_version=data.get("bootstrap_version"),
        )

    def to_dict(self) -> dict:
        return {
            "downloaded_checksums": self.downloaded_checksums,
            "firmware_checksums": self.firmware_checksums,
            "save_checksums": self.save_checksums,
            "save_lineage": self.save_lineage,
            "unresolved_save_conflicts": self.unresolved_save_conflicts,
            "tombstones": self.tombstones,
            "last_sync": self.last_sync,
            "bootstrap_version": self.bootstrap_version,
        }


def load_state(path: Path) -> SyncState:
    if not path.exists():
        return SyncState()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return SyncState.from_dict(raw)


def save_state_atomic(path: Path, state: SyncState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.tmp")
    payload = json.dumps(state.to_dict(), indent=2, sort_keys=True)
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    replace_file(tmp, path)


def mark_synced(state: SyncState) -> None:
    state.last_sync = datetime.now(timezone.utc).isoformat()


def mark_bootstrapped(state: SyncState) -> None:
    state.bootstrap_version = BOOTSTRAP_VERSION


def has_bootstrap_marker(state: SyncState) -> bool:
    return isinstance(state.bootstrap_version, int) and state.bootstrap_version >= BOOTSTRAP_VERSION


def has_legacy_sync_evidence(state: SyncState) -> bool:
    if state.last_sync:
        return True
    if state.downloaded_checksums:
        return True
    if state.firmware_checksums:
        return True
    if state.save_checksums:
        return True
    return False
