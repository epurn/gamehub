from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_id(prefix: str, payload: str) -> str:
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:16]}"


def make_title_id(system: str, title_rel_dir: str) -> str:
    return _stable_id("title", f"{system}:{title_rel_dir}")


def make_file_id(server_relative_path: str, sha256: str) -> str:
    return _stable_id("file", f"{server_relative_path}:{sha256}")


def make_asset_id(server_relative_path: str, sha256: str) -> str:
    return _stable_id("asset", f"{server_relative_path}:{sha256}")
