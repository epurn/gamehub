#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _venv_python(repo_root: Path) -> Path:
    if sys.platform == "win32":
        return repo_root / "venv" / "Scripts" / "python.exe"
    return repo_root / "venv" / "bin" / "python"


def _format_command(command: list[str]) -> str:
    return " ".join(command)


def _run(command: list[str], *, cwd: Path, check_only: bool, description: str) -> None:
    print(f"[codex-setup] {description}: {_format_command(command)}")
    if check_only:
        return
    subprocess.run(command, cwd=cwd, check=True, env={**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1"})


def _ensure_repo_root(repo_root: Path) -> None:
    pyproject_path = repo_root / "pyproject.toml"
    if not pyproject_path.is_file():
        raise SystemExit(f"Expected {pyproject_path} to exist.")


def _ensure_venv(repo_root: Path, *, check_only: bool) -> Path:
    venv_python = _venv_python(repo_root)
    if venv_python.is_file():
        print(f"[codex-setup] Reusing existing virtual environment at {venv_python.parent.parent}")
        return venv_python

    _run(
        [sys.executable, "-m", "venv", "venv"],
        cwd=repo_root,
        check_only=check_only,
        description="Creating repo-local virtual environment",
    )
    return venv_python


def _install_dev_dependencies(repo_root: Path, *, venv_python: Path, check_only: bool) -> None:
    _run(
        [str(venv_python), "-m", "pip", "--disable-pip-version-check", "install", "-e", ".[dev]"],
        cwd=repo_root,
        check_only=check_only,
        description="Installing editable project and dev dependencies",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap a GameHub Codex worktree with a repo-local virtual environment."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Print the bootstrap actions without creating the venv or installing dependencies.",
    )
    args = parser.parse_args()

    repo_root = _repo_root()
    _ensure_repo_root(repo_root)

    print(f"[codex-setup] Repo root: {repo_root}")
    print(f"[codex-setup] Host interpreter: {sys.executable}")

    venv_python = _ensure_venv(repo_root, check_only=args.check)
    _install_dev_dependencies(repo_root, venv_python=venv_python, check_only=args.check)

    if args.check:
        print("[codex-setup] Check complete.")
    else:
        print("[codex-setup] Setup complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
