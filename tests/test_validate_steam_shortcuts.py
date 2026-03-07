from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _load_script_module() -> object:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "validate_steam_shortcuts.py"
    spec = importlib.util.spec_from_file_location("validate_steam_shortcuts_script", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_validate_steam_shortcuts_main_returns_nonzero_when_context_missing(monkeypatch, capsys) -> None:
    monkeypatch.setattr("gamehub_cli.common.config.load_config", lambda _path=None: SimpleNamespace())
    monkeypatch.setattr("gamehub_cli.sync.steam_stage.resolve_steam_context", lambda _config: None)

    module = _load_script_module()
    monkeypatch.setattr(module, "_parse_args", lambda: SimpleNamespace(config=None))

    exit_code = module.main()

    assert exit_code == 1
    assert "Steam context could not be resolved" in capsys.readouterr().err
