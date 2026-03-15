from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


def _load_script_module() -> object:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "cleanup_backups.py"
    spec = importlib.util.spec_from_file_location("cleanup_backups_script", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_cleanup_backups_script_dry_run_uses_config_keep_limit(workspace_tempdir, monkeypatch, capsys) -> None:
    with workspace_tempdir("gamehub-cleanup-script-") as temp_root:
        config_root = temp_root / "gamehub"
        config_path = temp_root / "config.toml"
        config_path.write_text(
            "\n".join(
                [
                    "[paths]",
                    f"gamehub_dir = {json.dumps(str(config_root))}",
                    "",
                    "[backups]",
                    "keep_limit = 1",
                ]
            ),
            encoding="utf-8",
        )
        scan_root = temp_root / "manual-root"
        scan_root.mkdir(parents=True, exist_ok=True)
        newest = scan_root / "state.json.20260309120000.bak"
        older = scan_root / "state.json.20260309115959.bak"
        newest.write_text("newest\n", encoding="utf-8")
        older.write_text("older\n", encoding="utf-8")
        (scan_root / "notes.bak").write_text("manual\n", encoding="utf-8")

        module = _load_script_module()
        monkeypatch.setattr(
            module,
            "_parse_args",
            lambda: SimpleNamespace(
                config=config_path,
                root=[scan_root],
                server_data_root=None,
                keep=None,
                apply=False,
            ),
        )

        exit_code = module.main()

        assert exit_code == 0
        assert newest.exists()
        assert older.exists()
        captured = capsys.readouterr().out
        assert "mode=dry-run" in captured
        assert "keep=1" in captured
        assert "would-delete" in captured
        assert "notes.bak" not in captured


def test_cleanup_backups_script_apply_prunes_mixed_roots(workspace_tempdir, monkeypatch, capsys) -> None:
    with workspace_tempdir("gamehub-cleanup-script-") as temp_root:
        config_root = temp_root / "gamehub"
        config_path = temp_root / "config.toml"
        config_path.write_text(
            "\n".join(
                [
                    "[paths]",
                    f"gamehub_dir = {json.dumps(str(config_root))}",
                ]
            ),
            encoding="utf-8",
        )
        manual_root = temp_root / "manual-root"
        manual_root.mkdir(parents=True, exist_ok=True)
        stale_backup = manual_root / "shortcut_payloads.json.20260309115958.bak"
        newest_backup = manual_root / "shortcut_payloads.json.20260309115959.bak"
        stale_backup.write_text("stale\n", encoding="utf-8")
        newest_backup.write_text("newest\n", encoding="utf-8")
        (manual_root / "notes.bak").write_text("manual\n", encoding="utf-8")

        server_data_root = temp_root / "server-data"
        saves_root = server_data_root / "saves" / "NES"
        saves_root.mkdir(parents=True, exist_ok=True)
        server_stale = saves_root / "slot1.sav.20260309115958.bak"
        server_newest = saves_root / "slot1.sav.20260309115959.bak"
        server_stale.write_bytes(b"stale")
        server_newest.write_bytes(b"newest")

        module = _load_script_module()
        monkeypatch.setattr(
            module,
            "_parse_args",
            lambda: SimpleNamespace(
                config=config_path,
                root=[manual_root],
                server_data_root=server_data_root,
                keep=1,
                apply=True,
            ),
        )

        exit_code = module.main()

        assert exit_code == 0
        assert not stale_backup.exists()
        assert newest_backup.exists()
        assert not server_stale.exists()
        assert server_newest.exists()
        assert (manual_root / "notes.bak").exists()
        captured = capsys.readouterr().out
        assert "mode=apply" in captured
        assert "delete" in captured
