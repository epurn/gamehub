from __future__ import annotations

import json
from pathlib import Path

import pytest

from gamehub_cli.common.config import ControllersConfig, GamehubConfig
from gamehub_cli.sync.server_status import ServerCompatibilityError, require_server_compatibility, run_server_doctor
from gamehub_common.models import ServerIndexStatus, ServerSaveUploadStatus, ServerStatus
from gamehub_common.version import __version__


def _config() -> GamehubConfig:
    return GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("library"),
        firmware_dir=Path("firmware"),
        state_path=Path("state.json"),
        steam_userdata_dir=None,
        steam_id=None,
        steam_exe=None,
        sgdb_api_key=None,
        sgdb_cache_dir=Path("artwork_cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        controllers=ControllersConfig(launch_autoconfig=False),
    )


def _status(*, status: str = "ok", server_version: str = __version__) -> ServerStatus:
    return ServerStatus(
        server_version=server_version,
        status=status,
        index=ServerIndexStatus(
            systems=1,
            titles=1,
            saves=0,
            poll_seconds=1.0,
            stable_seconds=2.0,
            refresh_seconds=0.0,
            refresh_pending=False,
        ),
        save_upload=ServerSaveUploadStatus(max_upload_bytes=128 * 1024 * 1024, backup_keep_limit=3),
    )


def _index_payload() -> dict[str, object]:
    return {
        "index_version": 1,
        "systems": [],
        "titles": [
            {
                "title_id": "title_nes_mario",
                "system": "NES",
                "title_name": "SuperMarioBros",
                "title_rel_dir": "NES/SuperMarioBros",
                "emulator": "retroarch",
                "launch_template": "retroarch",
                "rom": {
                    "file_id": "file_demo",
                    "rel_path": "roms/NES/SuperMarioBros.nes",
                    "sha256": "a" * 64,
                    "size_bytes": 9,
                    "extension": ".nes",
                },
                "assets": [],
            }
        ],
        "saves": [],
    }


def test_require_server_compatibility_accepts_exact_match(monkeypatch) -> None:
    expected = _status()
    monkeypatch.setattr("gamehub_cli.sync.server_status.fetch_server_status", lambda **kwargs: expected)

    assert require_server_compatibility(_config(), verbose=False) == expected


def test_require_server_compatibility_rejects_version_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(
        "gamehub_cli.sync.server_status.fetch_server_status",
        lambda **kwargs: _status(server_version="1.6.1"),
    )

    with pytest.raises(ServerCompatibilityError, match="Server version mismatch"):
        require_server_compatibility(_config(), verbose=False)


def test_run_server_doctor_json_succeeds(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "gamehub_cli.sync.server_status.sync_index.fetch_health_with_retries", lambda **kwargs: {"status": "ok"}
    )
    monkeypatch.setattr("gamehub_cli.sync.server_status.fetch_server_status", lambda **kwargs: _status())
    monkeypatch.setattr(
        "gamehub_cli.sync.server_status.sync_index.fetch_index_with_retries",
        lambda **kwargs: _index_payload(),
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.server_status.sync_index.fetch_save_bindings_with_retries",
        lambda **kwargs: {"bindings": []},
    )
    monkeypatch.setattr("gamehub_cli.sync.server_status.fetch_sample_file_bytes", lambda **kwargs: b"rom-bytes")

    exit_code = run_server_doctor(_config(), json_output=True)

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["status"]["server_version"] == __version__
    assert payload["sample_file"] == {"checked": True, "file_id": "file_demo"}


def test_run_server_doctor_json_suppresses_retry_chatter(monkeypatch, capsys) -> None:
    def _health_with_retry_chatter(**kwargs) -> dict[str, object]:
        reporter = kwargs.get("reporter")
        if reporter is not None:
            reporter("Warning: health fetch attempt 1/3 failed (ConnectError). Retrying in 1.5s...")
        return {"status": "ok"}

    def _status_with_retry_chatter(**kwargs) -> ServerStatus:
        reporter = kwargs.get("reporter")
        if reporter is not None:
            reporter("Warning: server status fetch attempt 1/3 failed (ConnectError). Retrying in 1.5s...")
        return _status()

    def _index_with_retry_chatter(**kwargs) -> dict[str, object]:
        reporter = kwargs.get("reporter")
        if reporter is not None:
            reporter("Warning: index fetch attempt 1/3 failed (ConnectError). Retrying in 1.5s...")
        return _index_payload()

    def _bindings_with_retry_chatter(**kwargs) -> dict[str, object]:
        reporter = kwargs.get("reporter")
        if reporter is not None:
            reporter("Warning: save bindings fetch attempt 1/3 failed (ConnectError). Retrying in 1.5s...")
        return {"bindings": []}

    monkeypatch.setattr(
        "gamehub_cli.sync.server_status.sync_index.fetch_health_with_retries", _health_with_retry_chatter
    )
    monkeypatch.setattr("gamehub_cli.sync.server_status.fetch_server_status", _status_with_retry_chatter)
    monkeypatch.setattr("gamehub_cli.sync.server_status.sync_index.fetch_index_with_retries", _index_with_retry_chatter)
    monkeypatch.setattr(
        "gamehub_cli.sync.server_status.sync_index.fetch_save_bindings_with_retries",
        _bindings_with_retry_chatter,
    )
    monkeypatch.setattr("gamehub_cli.sync.server_status.fetch_sample_file_bytes", lambda **kwargs: b"rom-bytes")

    exit_code = run_server_doctor(_config(), json_output=True)

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert "Warning:" not in output
    assert payload["ok"] is True
    assert payload["status"]["server_version"] == __version__


def test_run_server_doctor_reports_version_mismatch(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "gamehub_cli.sync.server_status.sync_index.fetch_health_with_retries", lambda **kwargs: {"status": "ok"}
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.server_status.fetch_server_status",
        lambda **kwargs: _status(server_version="1.6.1"),
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.server_status.sync_index.fetch_index_with_retries",
        lambda **kwargs: _index_payload(),
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.server_status.sync_index.fetch_save_bindings_with_retries",
        lambda **kwargs: {"bindings": []},
    )
    monkeypatch.setattr("gamehub_cli.sync.server_status.fetch_sample_file_bytes", lambda **kwargs: b"rom-bytes")

    exit_code = run_server_doctor(_config(), json_output=False)

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Server version mismatch" in output
