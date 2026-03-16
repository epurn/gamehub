from __future__ import annotations

import tomllib
from pathlib import Path


def test_codex_environment_setup_has_non_empty_default_script() -> None:
    environment_path = Path(__file__).resolve().parent.parent / ".codex" / "environments" / "environment.toml"
    payload = tomllib.loads(environment_path.read_text(encoding="utf-8"))

    assert payload["setup"]["script"] == "python3 scripts/codex_worktree_setup.py"
    assert payload["setup"]["darwin"]["script"] == "python3 scripts/codex_worktree_setup.py"
    assert payload["setup"]["linux"]["script"] == "python3 scripts/codex_worktree_setup.py"
    assert payload["setup"]["win32"]["script"] == "py -3 scripts\\codex_worktree_setup.py"
