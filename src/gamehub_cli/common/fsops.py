from __future__ import annotations

import errno
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path


def _should_fallback_replace(exc: OSError) -> bool:
    if isinstance(exc, PermissionError):
        return True
    if exc.errno == errno.EXDEV:
        return True
    # Windows may surface cross-device rename failures as winerror 17.
    if getattr(exc, "winerror", None) == 17:
        return True
    return False


def replace_file(source: Path, destination: Path) -> None:
    try:
        source.replace(destination)
        return
    except OSError as exc:
        if not _should_fallback_replace(exc):
            raise
        # Some restricted filesystems deny rename/replace operations.
        with source.open("rb") as src, destination.open("wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        try:
            source.unlink(missing_ok=True)
        except OSError:
            # Best effort cleanup only; destination content has been safely written.
            with source.open("wb") as handle:
                handle.truncate(0)
                handle.flush()
                os.fsync(handle.fileno())


def backup_existing_file(path: Path) -> Path | None:
    if not path.exists() or not path.is_file():
        return None

    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    candidate = path.with_name(f"{path.name}.{stamp}.bak")
    suffix = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.{stamp}.{suffix}.bak")
        suffix += 1

    shutil.copy2(path, candidate)
    return candidate
