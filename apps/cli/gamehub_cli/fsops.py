from __future__ import annotations

import errno
import os
import shutil
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
