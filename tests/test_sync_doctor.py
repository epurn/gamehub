from __future__ import annotations

from pathlib import Path

from gamehub_cli.common.config import ControllersConfig, GamehubConfig
from gamehub_cli.main import _run_doctor_all_command
from gamehub_cli.sync.diagnostics import SyncDiagnosticsSnapshot, run_firmware_doctor, run_roms_doctor
from gamehub_cli.sync.orchestrator import run_init, run_sync
from gamehub_cli.sync.planner import PlanAction, SyncPlan
from gamehub_cli.sync.state import load_state
from gamehub_common.models import LibraryIndex


def _config(root: Path, *, launch_autoconfig: bool = False) -> GamehubConfig:
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
        controllers=ControllersConfig(launch_autoconfig=launch_autoconfig),
    )


def _empty_index() -> LibraryIndex:
    return LibraryIndex(index_version=1, systems=(), titles=())


def test_run_init_writes_bootstrap_version_without_last_sync(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-init-") as temp_root:
        config = _config(temp_root)
        monkeypatch.setattr(
            "gamehub_cli.sync.orchestrator._load_validated_index", lambda *args, **kwargs: _empty_index()
        )
        monkeypatch.setattr("gamehub_cli.sync.orchestrator._bootstrap_runtime", lambda *args, **kwargs: None)
        monkeypatch.setattr("gamehub_cli.sync.orchestrator.deploy_firmware_to_emulators", lambda *args, **kwargs: None)
        monkeypatch.setattr(
            "gamehub_cli.sync.orchestrator._converge_bootstrap_controller_state",
            lambda *args, **kwargs: None,
        )

        exit_code = run_init(
            config=config,
            dry_run=False,
            verbose=False,
            reseed_profiles=False,
        )

        saved = load_state(config.state_path)
        assert exit_code == 0
        assert saved.bootstrap_version == 1
        assert saved.last_sync is None


def test_run_sync_fails_fast_when_init_is_required(monkeypatch, workspace_tempdir, capsys) -> None:
    with workspace_tempdir("gamehub-sync-gate-") as temp_root:
        config = _config(temp_root)
        monkeypatch.setattr(
            "gamehub_cli.sync.orchestrator._load_validated_index",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("index fetch should not run")),
        )

        exit_code = run_sync(
            config=config,
            dry_run=True,
            verbose=False,
            verify=False,
            require_steam_closed=False,
            skip_steam=True,
        )

        assert exit_code == 1
        assert "Run 'gamehub init' before the first sync" in capsys.readouterr().out


def test_run_sync_allows_legacy_state_and_backfills_bootstrap_version(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-sync-legacy-") as temp_root:
        config = _config(temp_root)
        config.state_path.parent.mkdir(parents=True, exist_ok=True)
        config.state_path.write_text(
            (
                "{\n"
                '  "downloaded_checksums": {},\n'
                '  "firmware_checksums": {},\n'
                '  "tombstones": [],\n'
                '  "last_sync": "2026-02-14T18:00:00+00:00"\n'
                "}\n"
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "gamehub_cli.sync.orchestrator._load_validated_index", lambda *args, **kwargs: _empty_index()
        )
        monkeypatch.setattr("gamehub_cli.sync.orchestrator._bootstrap_runtime", lambda *args, **kwargs: None)
        monkeypatch.setattr("gamehub_cli.sync.orchestrator._apply_downloads", lambda *args, **kwargs: None)
        monkeypatch.setattr("gamehub_cli.sync.orchestrator.deploy_firmware_to_emulators", lambda *args, **kwargs: None)
        monkeypatch.setattr("gamehub_cli.sync.orchestrator._build_artwork_assignments", lambda *args, **kwargs: {})
        monkeypatch.setattr("gamehub_cli.sync.orchestrator._resolve_steam_context", lambda *args, **kwargs: None)
        monkeypatch.setattr(
            "gamehub_cli.sync.orchestrator._converge_bootstrap_controller_state",
            lambda *args, **kwargs: None,
        )

        exit_code = run_sync(
            config=config,
            dry_run=False,
            verbose=False,
            verify=False,
            require_steam_closed=False,
            skip_steam=True,
        )

        saved = load_state(config.state_path)
        assert exit_code == 0
        assert saved.bootstrap_version == 1
        assert saved.last_sync is not None


def test_run_roms_doctor_reports_content_actions_and_skipped_titles(capsys) -> None:
    config = _config(Path("gamehub"))
    snapshot = SyncDiagnosticsSnapshot(
        index=_empty_index(),
        plan=SyncPlan(
            content_actions=[
                PlanAction(
                    kind="rom",
                    system="NES",
                    label="Super Mario Bros ROM",
                    url="/v1/files/rom_nes_mario",
                    destination=Path("roms/NES/SuperMarioBros.nes"),
                    expected_sha256="a" * 64,
                    content_id="rom_nes_mario",
                )
            ],
            blocked_systems={"PSX": "Missing required firmware"},
            skipped_titles=2,
        ),
    )

    exit_code = run_roms_doctor(config, verify=False, verbose=False, snapshot=snapshot)

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "rom-doctor\tblocked-system\tsystem=PSX\treason=Missing required firmware" in output
    assert "rom-doctor\tstatus=drift\tkind=rom\tsystem=NES" in output
    assert "rom-doctor\tsummary\tcontent_actions=1\tskipped_titles=2\tblocked_systems=1" in output


def test_run_firmware_doctor_reports_blocked_systems(capsys) -> None:
    config = _config(Path("gamehub"))
    snapshot = SyncDiagnosticsSnapshot(
        index=_empty_index(),
        plan=SyncPlan(
            firmware_actions=[
                PlanAction(
                    kind="firmware",
                    system="PSX",
                    label="scph5501.bin",
                    url="/v1/firmware/PSX/scph5501.bin",
                    destination=Path("firmware/PSX/scph5501.bin"),
                    expected_sha256="b" * 64,
                    content_id="PSX/scph5501.bin",
                )
            ],
            blocked_systems={"PSX": "Missing required firmware"},
        ),
    )

    exit_code = run_firmware_doctor(config, verify=False, verbose=False, snapshot=snapshot)

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "firmware-doctor\tstatus=drift\tkind=firmware\tsystem=PSX" in output
    assert "firmware-doctor\tblocked-system\tsystem=PSX\treason=Missing required firmware" in output
    assert "firmware-doctor\tsummary\tfirmware_actions=1\tblocked_systems=1" in output


def test_run_doctor_all_aggregates_controller_and_sync_audits(monkeypatch) -> None:
    config = _config(Path("gamehub"))
    order: list[str] = []
    diagnostic_snapshot = SyncDiagnosticsSnapshot(index=_empty_index(), plan=SyncPlan())
    monkeypatch.setattr("gamehub_cli.main.load_config", lambda config_path=None: config)
    monkeypatch.setattr("gamehub_cli.main._discover_controller_doctor_steam_roots", lambda loaded: ((), None))
    monkeypatch.setattr(
        "gamehub_cli.main.run_controller_doctor",
        lambda *args, **kwargs: order.append("controllers") or 0,
    )
    monkeypatch.setattr(
        "gamehub_cli.main.build_sync_diagnostics_snapshot",
        lambda *args, **kwargs: order.append("snapshot") or diagnostic_snapshot,
    )
    monkeypatch.setattr(
        "gamehub_cli.main.run_firmware_doctor",
        lambda loaded, verify, verbose, snapshot=None: order.append(f"firmware:{snapshot is diagnostic_snapshot}") or 0,
    )
    monkeypatch.setattr(
        "gamehub_cli.main.run_roms_doctor",
        lambda loaded, verify, verbose, snapshot=None: order.append(f"roms:{snapshot is diagnostic_snapshot}") or 1,
    )

    exit_code = _run_doctor_all_command(config_path=None, verbose=False, verify=True)

    assert exit_code == 1
    assert order == ["controllers", "snapshot", "firmware:True", "roms:True"]
