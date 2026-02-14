from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "server"))
sys.path.insert(0, str(ROOT / "apps" / "cli"))
sys.path.insert(0, str(ROOT / "shared" / "gamehub_common"))

TMP_ROOT = ROOT / ".pytest_tmp_local"
TMP_PREFIXES = ("gamehub-indexer-", "gamehub-api-")


def _remove_readonly_and_retry(func, path, _exc_info) -> None:
    os.chmod(path, 0o700)
    func(path)


def _purge_managed_tempdirs() -> None:
    if not TMP_ROOT.exists():
        return
    for child in TMP_ROOT.iterdir():
        if child.is_dir() and child.name.startswith(TMP_PREFIXES):
            try:
                shutil.rmtree(child, onexc=_remove_readonly_and_retry)
            except FileNotFoundError:
                pass
            except OSError:
                # Best-effort cleanup; keep tests resilient if an external process has a lock.
                pass
            continue
        if child.is_file() and child.name.startswith(TMP_PREFIXES):
            child.unlink(missing_ok=True)


@pytest.fixture(scope="session", autouse=True)
def cleanup_workspace_tempdirs() -> None:
    _purge_managed_tempdirs()
    yield
    _purge_managed_tempdirs()
    try:
        TMP_ROOT.rmdir()
    except OSError:
        pass
