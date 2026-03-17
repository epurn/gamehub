from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from gamehub_cli.common.config import ControllersConfig, GamehubConfig, SaveSyncConfig
from gamehub_cli.sync.save_resolution import run_save_resolution
from gamehub_cli.sync.server_status import ServerCompatibilityError
from gamehub_cli.sync.state import SyncState, save_state_atomic
from gamehub_common.ids import make_save_binding_id, sha256_file


def _config(root: Path) -> GamehubConfig:
    return GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=root / "library",
        firmware_dir=root / "firmware",
        state_path=root / "state.json",
        steam_userdata_dir=None,
        steam_id=None,
        steam_exe=None,
        sgdb_api_key=None,
        sgdb_cache_dir=root / "cache",
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        controllers=ControllersConfig(launch_autoconfig=False),
        save_sync=SaveSyncConfig(enabled=True, mode="bidirectional", conflict_policy="manual"),
    )


def _index_payload(*, remote_sha: str, updated_at: str) -> dict[str, object]:
    return {
        "index_version": 1,
        "systems": [],
        "titles": [],
        "saves": [
            {
                "save_id": "save_ps2_ffx_1",
                "title_id": "title_ps2_ffx",
                "system": "PS2",
                "kind": "memory_card",
                "rel_path": "saves/PS2/Final Fantasy X/memory_card/ffx_1.ps2",
                "sha256": remote_sha,
                "size_bytes": 12,
                "updated_at": updated_at,
                "portable": True,
            }
        ],
    }


def _bindings_payload() -> dict[str, object]:
    binding_id = make_save_binding_id("title_ps2_ffx", "memory_card")
    return {
        "bindings": [
            {
                "binding_id": binding_id,
                "title_id": "title_ps2_ffx",
                "system": "PS2",
                "kind": "memory_card",
                "server_rel_dir": "saves/PS2/Final Fantasy X/memory_card",
                "local_root": "pcsx2_memcards",
                "strategy": "exact_files",
                "candidate_filenames": ["ffx_1.ps2"],
                "learn_rule": None,
                "portable": True,
            }
        ]
    }


@pytest.fixture(autouse=True)
def _default_server_compatibility(monkeypatch) -> None:
    monkeypatch.setattr("gamehub_cli.sync.save_resolution.require_server_compatibility", lambda *args, **kwargs: None)


def test_run_save_resolution_keep_server_dry_run_does_not_mutate_state(monkeypatch, workspace_tempdir, capsys) -> None:
    with workspace_tempdir("gamehub-save-resolution-") as temp_root:
        config = _config(temp_root)
        save_path = temp_root / "memcards" / "ffx_1.ps2"
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(b"local-drift")
        state = SyncState(unresolved_save_conflicts={"save_ps2_ffx_1": "both-changed-manual"})
        save_state_atomic(config.state_path, state)

        monkeypatch.setattr(
            "gamehub_cli.sync.save_resolution.sync_index.fetch_index_with_retries",
            lambda **kwargs: _index_payload(remote_sha="a" * 64, updated_at="2026-03-16T00:00:00+00:00"),
        )
        monkeypatch.setattr(
            "gamehub_cli.sync.save_resolution.sync_index.fetch_save_bindings_with_retries",
            lambda **kwargs: _bindings_payload(),
        )
        monkeypatch.setattr(
            "gamehub_cli.sync.save_resolution.resolve_local_save_destination",
            lambda *_args, **_kwargs: save_path,
        )
        monkeypatch.setattr(
            "gamehub_cli.sync.planner.resolve_local_save_destination",
            lambda *_args, **_kwargs: save_path,
        )
        monkeypatch.setattr(
            "gamehub_cli.sync.save_resolution.stream_to_destination_atomic",
            lambda **kwargs: (_ for _ in ()).throw(AssertionError("unexpected download")),
        )

        exit_code = run_save_resolution(
            config,
            save_id="save_ps2_ffx_1",
            choice="keep-server",
            dry_run=True,
            verbose=False,
            verify=False,
        )

        assert exit_code == 0
        assert save_path.read_bytes() == b"local-drift"
        persisted = SyncState.from_dict(json.loads(config.state_path.read_text(encoding="utf-8")))
        assert persisted.unresolved_save_conflicts == {"save_ps2_ffx_1": "both-changed-manual"}
        output = capsys.readouterr().out
        assert "save-resolve\tpreview\tchoice=keep-server\tid=save_ps2_ffx_1" in output


def test_run_save_resolution_keep_server_downloads_remote_and_clears_conflict(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-save-resolution-") as temp_root:
        config = _config(temp_root)
        save_path = temp_root / "memcards" / "ffx_1.ps2"
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(b"local-drift")
        state = SyncState(unresolved_save_conflicts={"save_ps2_ffx_1": "both-changed-manual"})
        save_state_atomic(config.state_path, state)
        remote_sha = "a" * 64
        remote_updated_at = "2026-03-16T00:00:00+00:00"

        monkeypatch.setattr(
            "gamehub_cli.sync.save_resolution.sync_index.fetch_index_with_retries",
            lambda **kwargs: _index_payload(remote_sha=remote_sha, updated_at=remote_updated_at),
        )
        monkeypatch.setattr(
            "gamehub_cli.sync.save_resolution.sync_index.fetch_save_bindings_with_retries",
            lambda **kwargs: _bindings_payload(),
        )
        monkeypatch.setattr(
            "gamehub_cli.sync.save_resolution.resolve_local_save_destination",
            lambda *_args, **_kwargs: save_path,
        )
        monkeypatch.setattr(
            "gamehub_cli.sync.planner.resolve_local_save_destination",
            lambda *_args, **_kwargs: save_path,
        )

        def _fake_download(**kwargs) -> None:
            kwargs["destination"].write_bytes(b"remote-copy")

        monkeypatch.setattr("gamehub_cli.sync.save_resolution.stream_to_destination_atomic", _fake_download)
        monkeypatch.setattr("gamehub_cli.sync.save_resolution.local_file_updated_at", lambda _path: remote_updated_at)

        exit_code = run_save_resolution(
            config,
            save_id="save_ps2_ffx_1",
            choice="keep-server",
            dry_run=False,
            verbose=False,
            verify=False,
        )

        saved = SyncState.from_dict(json.loads(config.state_path.read_text(encoding="utf-8")))
        assert exit_code == 0
        assert save_path.read_bytes() == b"remote-copy"
        assert "save_ps2_ffx_1" not in saved.unresolved_save_conflicts
        assert saved.save_lineage["save_ps2_ffx_1"]["remote_sha256"] == remote_sha


def test_run_save_resolution_keep_local_uploads_and_clears_conflict(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-save-resolution-") as temp_root:
        config = _config(temp_root)
        save_path = temp_root / "memcards" / "ffx_1.ps2"
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(b"local-copy")
        state = SyncState(unresolved_save_conflicts={"save_ps2_ffx_1": "both-changed-manual"})
        save_state_atomic(config.state_path, state)
        updated_at = "2026-03-16T00:00:00+00:00"

        monkeypatch.setattr(
            "gamehub_cli.sync.save_resolution.sync_index.fetch_index_with_retries",
            lambda **kwargs: _index_payload(remote_sha="b" * 64, updated_at=updated_at),
        )
        monkeypatch.setattr(
            "gamehub_cli.sync.save_resolution.sync_index.fetch_save_bindings_with_retries",
            lambda **kwargs: _bindings_payload(),
        )
        monkeypatch.setattr(
            "gamehub_cli.sync.save_resolution.resolve_local_save_destination",
            lambda *_args, **_kwargs: save_path,
        )
        monkeypatch.setattr(
            "gamehub_cli.sync.planner.resolve_local_save_destination",
            lambda *_args, **_kwargs: save_path,
        )

        def _fake_upload(**kwargs) -> dict[str, object]:
            assert kwargs["binding_id"] == make_save_binding_id("title_ps2_ffx", "memory_card")
            assert kwargs["canonical_suffix"] == "ffx_1.ps2"
            assert kwargs["expected_remote_sha256"] == "b" * 64
            return {
                "save_id": "save_ps2_ffx_1",
                "title_id": "title_ps2_ffx",
                "system": "PS2",
                "kind": "memory_card",
                "rel_path": "saves/PS2/Final Fantasy X/memory_card/ffx_1.ps2",
                "sha256": "c" * 64,
                "size_bytes": len(b"local-copy"),
                "updated_at": updated_at,
                "portable": True,
            }

        monkeypatch.setattr("gamehub_cli.sync.save_resolution.upload_file_to_server", _fake_upload)
        monkeypatch.setattr(
            "gamehub_cli.sync.save_resolution.local_file_updated_at",
            lambda _path: datetime(2026, 3, 16, 0, 0, tzinfo=timezone.utc).isoformat(),
        )

        exit_code = run_save_resolution(
            config,
            save_id="save_ps2_ffx_1",
            choice="keep-local",
            dry_run=False,
            verbose=False,
            verify=False,
        )

        saved = SyncState.from_dict(json.loads(config.state_path.read_text(encoding="utf-8")))
        assert exit_code == 0
        assert "save_ps2_ffx_1" not in saved.unresolved_save_conflicts
        assert saved.save_lineage["save_ps2_ffx_1"]["remote_sha256"] == "c" * 64


def test_run_save_resolution_rejects_non_actionable_save(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-save-resolution-") as temp_root:
        config = _config(temp_root)
        save_path = temp_root / "memcards" / "ffx_1.ps2"
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(b"already-synced")
        save_sha = sha256_file(save_path)
        state = SyncState()
        save_state_atomic(config.state_path, state)

        monkeypatch.setattr(
            "gamehub_cli.sync.save_resolution.sync_index.fetch_index_with_retries",
            lambda **kwargs: _index_payload(remote_sha=save_sha, updated_at="2026-03-16T00:00:00+00:00"),
        )
        monkeypatch.setattr(
            "gamehub_cli.sync.save_resolution.sync_index.fetch_save_bindings_with_retries",
            lambda **kwargs: _bindings_payload(),
        )
        monkeypatch.setattr(
            "gamehub_cli.sync.save_resolution.resolve_local_save_destination",
            lambda *_args, **_kwargs: save_path,
        )
        monkeypatch.setattr(
            "gamehub_cli.sync.planner.resolve_local_save_destination",
            lambda *_args, **_kwargs: save_path,
        )

        try:
            run_save_resolution(
                config,
                save_id="save_ps2_ffx_1",
                choice="keep-local",
                dry_run=False,
                verbose=False,
                verify=False,
            )
        except ValueError as exc:
            assert "does not currently require operator resolution" in str(exc)
        else:
            raise AssertionError("expected ValueError")


def test_run_save_resolution_fails_fast_on_server_version_mismatch(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-save-resolution-") as temp_root:
        config = _config(temp_root)
        monkeypatch.setattr(
            "gamehub_cli.sync.save_resolution.require_server_compatibility",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                ServerCompatibilityError("Server version mismatch: client=1.6.0 server=1.6.1")
            ),
        )
        monkeypatch.setattr(
            "gamehub_cli.sync.save_resolution.sync_index.fetch_index_with_retries",
            lambda **kwargs: (_ for _ in ()).throw(AssertionError("index fetch should not run")),
        )

        with pytest.raises(ServerCompatibilityError, match="Server version mismatch"):
            run_save_resolution(
                config,
                save_id="save_ps2_ffx_1",
                choice="keep-server",
                dry_run=True,
                verbose=False,
                verify=False,
            )
