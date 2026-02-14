from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import shutil
from uuid import uuid4

from gamehub_cli.config import load_config
from gamehub_cli.state import SyncState, load_state, save_state_atomic


@contextmanager
def _workspace_tempdir(prefix: str):
    root = Path(__file__).resolve().parents[1] / ".pytest_tmp_local"
    root.mkdir(parents=True, exist_ok=True)
    temp_dir = root / f"{prefix}{uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=False)
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_load_config_uses_defaults_when_file_is_missing(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-cli-config-") as temp_root:
        monkeypatch.delenv("GAMEHUB_SGDB_API_KEY", raising=False)
        config_home = temp_root / "cfg-home"
        state_home = temp_root / "state-home"
        monkeypatch.setattr("gamehub_cli.config.user_config_dir", lambda appname: str(config_home / appname))
        monkeypatch.setattr("gamehub_cli.config.user_state_dir", lambda appname: str(state_home / appname))

        loaded = load_config(temp_root / "missing.toml")

        expected_state_root = state_home / "gamehub"
        assert loaded.server_url == "http://127.0.0.1:8000"
        assert loaded.library_dir == expected_state_root / "library"
        assert loaded.firmware_dir == expected_state_root / "firmware"
        assert loaded.state_path == expected_state_root / "state.json"
        assert loaded.steam_userdata_dir is None
        assert loaded.steam_exe is None
        assert loaded.sgdb_api_key is None
        assert loaded.sgdb_cache_dir == expected_state_root / "artwork_cache" / "sgdb"
        assert loaded.sgdb_enabled_kinds == ("grid", "hero", "logo", "icon")


def test_load_config_toml_overrides_defaults(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-cli-config-") as temp_root:
        monkeypatch.delenv("GAMEHUB_SGDB_API_KEY", raising=False)
        config_path = temp_root / "config.toml"
        config_path.write_text(
            "\n".join(
                [
                    '[server]',
                    'url = "http://example.invalid:9000"',
                    "",
                    "[paths]",
                    'library_dir = "C:/library"',
                    'firmware_dir = "C:/firmware"',
                    'state_path = "C:/state/state.json"',
                    "",
                    "[steam]",
                    'userdata_dir = "C:/Steam/userdata"',
                    'steam_exe = "C:/Steam/steam.exe"',
                    "",
                    "[sgdb]",
                    'api_key = "from-config-key"',
                    'cache_dir = "C:/cache/sgdb"',
                    'enabled_kinds = ["grid", "icon"]',
                ]
            ),
            encoding="utf-8",
        )

        loaded = load_config(config_path)

        assert loaded.server_url == "http://example.invalid:9000"
        assert loaded.library_dir == Path("C:/library")
        assert loaded.firmware_dir == Path("C:/firmware")
        assert loaded.state_path == Path("C:/state/state.json")
        assert loaded.steam_userdata_dir == Path("C:/Steam/userdata")
        assert loaded.steam_exe == Path("C:/Steam/steam.exe")
        assert loaded.sgdb_api_key == "from-config-key"
        assert loaded.sgdb_cache_dir == Path("C:/cache/sgdb")
        assert loaded.sgdb_enabled_kinds == ("grid", "icon")


def test_load_config_prefers_sgdb_api_key_from_env(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-cli-config-") as temp_root:
        config_path = temp_root / "config.toml"
        config_path.write_text(
            "\n".join(
                [
                    "[sgdb]",
                    'api_key = "from-config-key"',
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("GAMEHUB_SGDB_API_KEY", "from-env-key")

        loaded = load_config(config_path)

        assert loaded.sgdb_api_key == "from-env-key"


def test_load_config_normalizes_quoted_sgdb_api_key(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-cli-config-") as temp_root:
        config_path = temp_root / "config.toml"
        config_path.write_text(
            "\n".join(
                [
                    "[sgdb]",
                    'api_key = "  \\"quoted-config-key\\"  "',
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.delenv("GAMEHUB_SGDB_API_KEY", raising=False)

        loaded = load_config(config_path)

        assert loaded.sgdb_api_key == "quoted-config-key"


def test_state_round_trip_with_atomic_save() -> None:
    with _workspace_tempdir("gamehub-cli-state-") as temp_root:
        state_path = temp_root / "state.json"
        state = SyncState(
            downloaded_checksums={"file_1": "a" * 64},
            firmware_checksums={"PSX/scph5501.bin": "b" * 64},
            tombstones=["title_old"],
            last_sync="2026-02-14T18:00:00+00:00",
        )

        save_state_atomic(state_path, state)
        loaded = load_state(state_path)

        assert loaded.to_dict() == state.to_dict()
