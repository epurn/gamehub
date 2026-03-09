from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import vdf


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


def test_validate_steam_shortcuts_accepts_payload_ref_shortcuts(workspace_tempdir, monkeypatch, capsys) -> None:
    with workspace_tempdir("gamehub-validate-shortcuts-") as temp_root:
        shortcuts_path = temp_root / "shortcuts.vdf"
        shortcuts_path.write_bytes(
            vdf.binary_dumps(
                {
                    "shortcuts": {
                        "0": {
                            "AppName": "Wind Waker",
                            "Exe": '"/Users/tester/gamehub"',
                            "LaunchOptions": (
                                "shortcut-launch --payload-ref title_gc_zelda "
                                f'--payload-registry "{temp_root / "shortcut_payloads.json"}"'
                            ),
                            "tags": {"0": "GAMEHUB"},
                        }
                    }
                }
            )
        )
        module = _load_script_module()
        monkeypatch.setattr(module, "_parse_args", lambda: SimpleNamespace(config=None))
        monkeypatch.setattr(
            module,
            "load_config",
            lambda _path=None: SimpleNamespace(state_path=temp_root / "state.json"),
        )
        monkeypatch.setattr(
            module,
            "resolve_steam_context",
            lambda _config: SimpleNamespace(shortcuts_path=shortcuts_path),
        )

        exit_code = module.main()

        assert exit_code == 0
        captured = capsys.readouterr().out
        assert "BAD_WRAPPERS: 0" in captured
        assert "BAD_PAYLOAD_REGISTRY: 0" in captured


def test_validate_steam_shortcuts_accepts_macos_launcher_shortcuts(workspace_tempdir, monkeypatch, capsys) -> None:
    with workspace_tempdir("gamehub-validate-shortcuts-macos-launcher-") as temp_root:
        shortcuts_path = temp_root / "shortcuts.vdf"
        state_path = temp_root / "Gamehub" / "state.json"
        launcher_path = state_path.with_name("steam-shortcut-launch.sh")
        shortcuts_path.write_bytes(
            vdf.binary_dumps(
                {
                    "shortcuts": {
                        "0": {
                            "AppName": "Wind Waker",
                            "Exe": str(launcher_path),
                            "LaunchOptions": "title_gc_zelda",
                            "tags": {"0": "GAMEHUB"},
                        }
                    }
                }
            )
        )
        module = _load_script_module()
        monkeypatch.setattr(module, "_parse_args", lambda: SimpleNamespace(config=None))
        monkeypatch.setattr(
            module,
            "load_config",
            lambda _path=None: SimpleNamespace(state_path=state_path),
        )
        monkeypatch.setattr(
            module,
            "resolve_steam_context",
            lambda _config: SimpleNamespace(shortcuts_path=shortcuts_path),
        )

        exit_code = module.main()

        assert exit_code == 0
        captured = capsys.readouterr().out
        assert "BAD_WRAPPERS: 0" in captured
