from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from ..common.fsops import replace_file

MANAGED_METADATA_FILENAME = ".gamehub-managed.json"
MANAGED_METADATA_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ManagedMetadataEntry:
    source_profile: str
    source_template: str
    timestamp_utc: str
    fingerprint_sha256: str
    ownership: str

    @classmethod
    def from_mapping(cls, raw: dict[str, object]) -> "ManagedMetadataEntry | None":
        source_profile_raw = raw.get("source_profile")
        source_template_raw = raw.get("source_template")
        timestamp_utc_raw = raw.get("timestamp_utc")
        fingerprint_sha256_raw = raw.get("fingerprint_sha256")
        ownership_raw = raw.get("ownership")
        if not isinstance(source_profile_raw, str) or not source_profile_raw.strip():
            return None
        if not isinstance(source_template_raw, str) or not source_template_raw.strip():
            return None
        if not isinstance(timestamp_utc_raw, str) or not timestamp_utc_raw.strip():
            return None
        if not isinstance(fingerprint_sha256_raw, str) or len(fingerprint_sha256_raw) != 64:
            return None
        if not isinstance(ownership_raw, str) or not ownership_raw.strip():
            return None
        return cls(
            source_profile=source_profile_raw.strip(),
            source_template=source_template_raw.strip(),
            timestamp_utc=timestamp_utc_raw.strip(),
            fingerprint_sha256=fingerprint_sha256_raw.strip().casefold(),
            ownership=ownership_raw.strip().casefold(),
        )

    def to_mapping(self) -> dict[str, str]:
        return {
            "source_profile": self.source_profile,
            "source_template": self.source_template,
            "timestamp_utc": self.timestamp_utc,
            "fingerprint_sha256": self.fingerprint_sha256,
            "ownership": self.ownership,
        }


def sha256_text(payload: str) -> str:
    return sha256(payload.encode("utf-8")).hexdigest()


def managed_metadata_path(target: Path) -> Path:
    return target.parent / MANAGED_METADATA_FILENAME


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp") as tmp:
        tmp.write(payload)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = path.parent / os.path.basename(tmp.name)
    replace_file(tmp_path, path)


def _base_payload() -> dict[str, object]:
    return {
        "schema_version": MANAGED_METADATA_SCHEMA_VERSION,
        "updated_at": utc_now_iso(),
        "entries": {},
    }


def _load_payload(path: Path) -> tuple[dict[str, object], str | None]:
    if not path.exists():
        return _base_payload(), None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _base_payload(), f"invalid metadata JSON: {exc}"
    if not isinstance(raw, dict):
        return _base_payload(), "invalid metadata JSON: expected object root"
    schema_version = raw.get("schema_version")
    updated_at = raw.get("updated_at")
    entries_raw = raw.get("entries")
    entries: dict[str, object] = entries_raw if isinstance(entries_raw, dict) else {}
    payload: dict[str, object] = {
        "schema_version": schema_version if isinstance(schema_version, int) else MANAGED_METADATA_SCHEMA_VERSION,
        "updated_at": updated_at if isinstance(updated_at, str) and updated_at.strip() else utc_now_iso(),
        "entries": entries,
    }
    return payload, None


def read_managed_metadata_entry(target: Path) -> tuple[ManagedMetadataEntry | None, str | None]:
    payload, error = _load_payload(managed_metadata_path(target))
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        return None, error
    raw_entry = entries.get(target.name)
    if not isinstance(raw_entry, dict):
        return None, error
    entry = ManagedMetadataEntry.from_mapping(raw_entry)
    if entry is None:
        return None, "invalid metadata entry schema"
    return entry, error


def write_managed_metadata_entry(target: Path, entry: ManagedMetadataEntry) -> bool:
    path = managed_metadata_path(target)
    payload, _ = _load_payload(path)
    existing_text: str | None = None
    if path.exists():
        try:
            existing_text = path.read_text(encoding="utf-8")
        except OSError:
            existing_text = None
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        entries = {}
        payload["entries"] = entries
    current = entries.get(target.name)
    next_entry = entry.to_mapping()
    if isinstance(current, dict):
        normalized = {str(key): value for key, value in current.items()}
        if normalized == next_entry:
            current_payload = json.dumps(payload, indent=2, sort_keys=True) + "\n"
            if existing_text == current_payload:
                return False
    entries[target.name] = next_entry
    payload["schema_version"] = MANAGED_METADATA_SCHEMA_VERSION
    payload["updated_at"] = utc_now_iso()
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if existing_text == rendered:
        return False
    _atomic_write_text(path, rendered)
    return True
