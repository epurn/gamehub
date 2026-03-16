from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_setup_module():
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "codex_worktree_setup.py"
    spec = importlib.util.spec_from_file_location("codex_worktree_setup_test", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_find_shared_venv_python_prefers_other_worktree(workspace_tempdir, monkeypatch) -> None:
    module = _load_setup_module()
    with workspace_tempdir("gamehub-codex-setup-") as temp_root:
        repo_root = temp_root / "current"
        other_root = temp_root / "main"
        repo_root.mkdir()
        other_root.mkdir()
        other_venv_python = module._venv_python(other_root)
        other_venv_python.parent.mkdir(parents=True)
        other_venv_python.write_text("", encoding="utf-8")

        monkeypatch.setattr(
            module, "_git_worktree_paths", lambda _repo_root: (repo_root.resolve(), other_root.resolve())
        )

        assert module._find_shared_venv_python(repo_root) == other_venv_python


def test_write_shared_venv_bridge_writes_shared_site_packages_and_src(workspace_tempdir) -> None:
    module = _load_setup_module()
    with workspace_tempdir("gamehub-codex-setup-") as temp_root:
        repo_root = temp_root / "repo"
        repo_root.mkdir()
        (repo_root / "src").mkdir()
        venv_python = module._venv_python(repo_root)
        venv_python.parent.mkdir(parents=True)
        venv_python.write_text("", encoding="utf-8")
        shared_python = module._venv_python(temp_root / "shared")
        shared_python.parent.mkdir(parents=True)
        shared_python.write_text("", encoding="utf-8")
        shared_site_packages = module._venv_site_packages(shared_python)
        shared_site_packages.mkdir(parents=True)

        module._write_shared_venv_bridge(
            repo_root,
            venv_python=venv_python,
            shared_venv_python=shared_python,
            check_only=False,
        )

        bridge_path = module._venv_site_packages(venv_python) / "gamehub_codex_shared_deps.pth"
        assert bridge_path.read_text(encoding="utf-8") == f"{shared_site_packages}\n{repo_root / 'src'}\n"
