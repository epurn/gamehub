from __future__ import annotations

import os
import shutil
from pathlib import Path


def replace_file(source: Path, destination: Path) -> None:
    try:
        source.replace(destination)
        return
    except PermissionError:
        # Some restricted filesystems deny rename/replace operations.
        with source.open("rb") as src, destination.open("wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        try:
            source.unlink(missing_ok=True)
        except PermissionError:
            # Best effort cleanup only; destination content has been safely written.
            with source.open("wb") as handle:
                handle.truncate(0)
                handle.flush()
                os.fsync(handle.fileno())
