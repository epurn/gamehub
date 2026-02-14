from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class SyncState:
    downloaded_checksums: dict[str, str] = field(default_factory=dict)
    firmware_checksums: dict[str, str] = field(default_factory=dict)
    tombstones: list[str] = field(default_factory=list)
    last_sync: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "SyncState":
        return cls(
            downloaded_checksums=dict(data.get("downloaded_checksums", {})),
            firmware_checksums=dict(data.get("firmware_checksums", {})),
            tombstones=list(data.get("tombstones", [])),
            last_sync=data.get("last_sync"),
        )

    def to_dict(self) -> dict:
        return {
            "downloaded_checksums": self.downloaded_checksums,
            "firmware_checksums": self.firmware_checksums,
            "tombstones": self.tombstones,
            "last_sync": self.last_sync,
        }


def load_state(path: Path) -> SyncState:
    if not path.exists():
        return SyncState()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return SyncState.from_dict(raw)


def save_state_atomic(path: Path, state: SyncState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.tmp")
    tmp.write_text(json.dumps(state.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def mark_synced(state: SyncState) -> None:
    state.last_sync = datetime.now(timezone.utc).isoformat()
