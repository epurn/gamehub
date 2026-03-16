from __future__ import annotations

import gc
import os
import shutil
import sys
import time
from contextlib import contextmanager
from errno import EACCES, EPERM
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TMP_ROOT = ROOT / ".pytest_tmp_local"
TMP_PREFIXES = ("gamehub-",)


def _remove_readonly_and_retry(func, path, _exc_info) -> None:
    os.chmod(path, 0o700)
    func(path)


@contextmanager
def _workspace_tempdir(prefix: str):
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    temp_dir = TMP_ROOT / f"{prefix}{uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=False)
    try:
        yield temp_dir
    finally:
        for _ in range(10):
            try:
                shutil.rmtree(temp_dir, onexc=_remove_readonly_and_retry)
                break
            except FileNotFoundError:
                break
            except OSError:
                gc.collect()
                time.sleep(0.05)


@pytest.fixture
def workspace_tempdir():
    return _workspace_tempdir


def _make_symlink(path: Path, target: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.symlink_to(target, target_is_directory=target.is_dir())
    except (NotImplementedError, OSError) as exc:
        if getattr(exc, "errno", None) in {EACCES, EPERM}:
            pytest.skip("symlink creation is not permitted on this host")
        raise


@pytest.fixture
def make_symlink():
    return _make_symlink


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
