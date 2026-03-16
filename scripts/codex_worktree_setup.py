#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_BRIDGE_FILENAME = "gamehub_codex_shared_deps.pth"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _venv_python(repo_root: Path) -> Path:
    if sys.platform == "win32":
        return repo_root / "venv" / "Scripts" / "python.exe"
    return repo_root / "venv" / "bin" / "python"


def _format_command(command: list[str]) -> str:
    return " ".join(command)


def _venv_site_packages(venv_python: Path) -> Path:
    venv_root = venv_python.parent.parent
    if sys.platform == "win32":
        return venv_root / "Lib" / "site-packages"
    return venv_root / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"


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
        [
            str(venv_python),
            "-m",
            "pip",
            "--disable-pip-version-check",
            "install",
            "--no-build-isolation",
            "-e",
            ".[dev]",
        ],
        cwd=repo_root,
        check_only=check_only,
        description="Installing editable project and dev dependencies",
    )


def _git_worktree_paths(repo_root: Path) -> tuple[Path, ...]:
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ()
    paths: list[Path] = []
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            paths.append(Path(line.removeprefix("worktree ").strip()).resolve())
    return tuple(paths)


def _find_shared_venv_python(repo_root: Path) -> Path | None:
    current_root = repo_root.resolve()
    for worktree_root in _git_worktree_paths(repo_root):
        if worktree_root == current_root:
            continue
        candidate = _venv_python(worktree_root)
        if candidate.is_file():
            return candidate
    return None


def _write_shared_venv_bridge(
    repo_root: Path,
    *,
    venv_python: Path,
    shared_venv_python: Path,
    check_only: bool,
) -> None:
    shared_site_packages = _venv_site_packages(shared_venv_python)
    if not shared_site_packages.is_dir():
        raise SystemExit(f"Shared dependency site-packages not found: {shared_site_packages}")
    bridge_path = _venv_site_packages(venv_python) / _BRIDGE_FILENAME
    bridge_payload = f"{shared_site_packages}\n{repo_root / 'src'}\n"
    print(f"[codex-setup] Bridging dependencies from {shared_site_packages}")
    print(f"[codex-setup] Writing shared dependency bridge: {bridge_path}")
    if check_only:
        return
    bridge_path.parent.mkdir(parents=True, exist_ok=True)
    bridge_path.write_text(bridge_payload, encoding="utf-8")


def _install_or_bridge_dev_dependencies(repo_root: Path, *, venv_python: Path, check_only: bool) -> str:
    try:
        _install_dev_dependencies(repo_root, venv_python=venv_python, check_only=check_only)
    except subprocess.CalledProcessError as exc:
        shared_venv_python = _find_shared_venv_python(repo_root)
        if shared_venv_python is None:
            raise SystemExit(
                "[codex-setup] Dev dependency install failed and no sibling GameHub worktree venv was found. "
                "Connect to the network or provision another checkout venv first."
            ) from exc
        print(f"[codex-setup] Editable install failed; falling back to shared worktree venv at {shared_venv_python}")
        _write_shared_venv_bridge(
            repo_root,
            venv_python=venv_python,
            shared_venv_python=shared_venv_python,
            check_only=check_only,
        )
        return "bridged"
    return "installed"


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
    install_mode = _install_or_bridge_dev_dependencies(repo_root, venv_python=venv_python, check_only=args.check)

    if args.check:
        print("[codex-setup] Check complete.")
    elif install_mode == "bridged":
        print("[codex-setup] Setup complete via shared dependency bridge.")
    else:
        print("[codex-setup] Setup complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
