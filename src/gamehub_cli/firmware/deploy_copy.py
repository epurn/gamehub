from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from gamehub_common.ids import sha256_file

from ..common.fsops import replace_file


def sha256(path: Path) -> str:
    return sha256_file(path)


def copy_or_link(source: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and sha256(destination) == sha256(source):
        return "up_to_date"

    tmp = destination.with_name(f"{destination.name}.{uuid4().hex}.tmp")
    shutil.copy2(source, tmp)
    mode = "copied"
    replace_file(tmp, destination)
    return mode
