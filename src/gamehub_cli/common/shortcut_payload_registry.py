from __future__ import annotations

import json
import os
from collections.abc import Mapping
from logging import getLogger
from pathlib import Path

from .fsops import DEFAULT_BACKUP_KEEP_LIMIT, backup_existing_file, replace_file

SHORTCUT_PAYLOAD_REGISTRY_FILENAME = "shortcut_payloads.json"
SHORTCUT_PAYLOAD_REGISTRY_VERSION = 1

logger = getLogger(__name__)


def shortcut_payload_registry_path(state_path: Path) -> Path:
    return state_path.with_name(SHORTCUT_PAYLOAD_REGISTRY_FILENAME)


def load_shortcut_payload_registry(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Shortcut payload registry must decode to a JSON object")
    version = raw.get("schema_version", SHORTCUT_PAYLOAD_REGISTRY_VERSION)
    if version != SHORTCUT_PAYLOAD_REGISTRY_VERSION:
        raise ValueError(f"Unsupported shortcut payload registry version: {version}")
    payloads = raw.get("payloads", {})
    if not isinstance(payloads, dict):
        raise ValueError("Shortcut payload registry missing payloads object")
    normalized: dict[str, str] = {}
    for key, value in payloads.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        payload_ref = key.strip()
        payload_token = value.strip()
        if payload_ref and payload_token:
            normalized[payload_ref] = payload_token
    return normalized


def load_shortcut_payload_token(path: Path, payload_ref: str) -> str:
    normalized_ref = payload_ref.strip()
    if not normalized_ref:
        raise ValueError("Shortcut payload reference missing")
    registry = load_shortcut_payload_registry(path)
    token = registry.get(normalized_ref)
    if not token:
        raise ValueError(f"Shortcut payload reference not found: {normalized_ref}")
    return token


def save_shortcut_payload_registry_atomic(
    path: Path,
    payload_tokens_by_ref: Mapping[str, str],
    *,
    keep_limit: int = DEFAULT_BACKUP_KEEP_LIMIT,
) -> None:
    normalized: dict[str, str] = {}
    for key, value in payload_tokens_by_ref.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        payload_ref = key.strip()
        payload_token = value.strip()
        if payload_ref and payload_token:
            normalized[payload_ref] = payload_token

    rendered = json.dumps(
        {
            "schema_version": SHORTCUT_PAYLOAD_REGISTRY_VERSION,
            "payloads": dict(sorted(normalized.items())),
        },
        indent=2,
        sort_keys=True,
    )
    rendered = f"{rendered}\n"

    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing == rendered:
            return

    path.parent.mkdir(parents=True, exist_ok=True)
    backup_result = backup_existing_file(path, keep_limit=keep_limit)
    if backup_result.created_path is not None:
        logger.info("shortcut payload registry backup created path=%s backup=%s", path, backup_result.created_path)
    for pruned_path in backup_result.pruned_paths:
        logger.info("shortcut payload registry backup pruned path=%s pruned_backup=%s", path, pruned_path)

    tmp = path.with_suffix(f"{path.suffix}.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(rendered)
        handle.flush()
        os.fsync(handle.fileno())
    replace_file(tmp, path)
    logger.info("shortcut payload registry saved path=%s entries=%s", path, len(normalized))
