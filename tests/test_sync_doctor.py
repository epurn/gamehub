from __future__ import annotations

from pathlib import Path

import pytest

from gamehub_cli.common.config import ControllersConfig, GamehubConfig, SaveSyncConfig
from gamehub_cli.main import _run_doctor_all_command
from gamehub_cli.sync.diagnostics import SyncDiagnosticsSnapshot, run_firmware_doctor, run_roms_doctor, run_save_doctor
from gamehub_cli.sync.orchestrator import run_init, run_sync
from gamehub_cli.sync.planner import PlanAction, SavePlanAction, SyncPlan
from gamehub_cli.sync.server_status import ServerCompatibilityError
from gamehub_cli.sync.state import SyncState, load_state
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
        save_sync=SaveSyncConfig(enabled=True, mode="bidirectional", conflict_policy="manual"),
    )


def _empty_index() -> LibraryIndex:
    return LibraryIndex(index_version=1, systems=(), titles=())


@pytest.fixture(autouse=True)
def _default_server_compatibility(monkeypatch) -> None:
    monkeypatch.setattr("gamehub_cli.sync.orchestrator.require_server_compatibility", lambda *args, **kwargs: None)
    monkeypatch.setattr("gamehub_cli.sync.diagnostics.require_server_compatibility", lambda *args, **kwargs: None)


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


def test_run_sync_requires_bootstrap_version_even_with_existing_last_sync(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-sync-bootstrap-required-") as temp_root:
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

        saved = load_state(config.state_path)
        assert exit_code == 1
        assert saved.bootstrap_version is None
        assert saved.last_sync == "2026-02-14T18:00:00+00:00"


def test_run_save_doctor_fails_fast_on_server_version_mismatch(monkeypatch) -> None:
    config = _config(Path("gamehub"))
    monkeypatch.setattr(
        "gamehub_cli.sync.diagnostics.require_server_compatibility",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ServerCompatibilityError("Server version mismatch: client=1.6.0 server=1.6.1")
        ),
    )
    monkeypatch.setattr(
        "gamehub_cli.sync.diagnostics.sync_index.fetch_index_with_retries",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("index fetch should not run")),
    )

    with pytest.raises(ServerCompatibilityError, match="Server version mismatch"):
        run_save_doctor(config, verify=False, verbose=False)


def test_run_roms_doctor_reports_content_actions_and_skipped_titles(capsys) -> None:
    config = _config(Path("gamehub"))
    snapshot = SyncDiagnosticsSnapshot(
        state=SyncState(),
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
        state=SyncState(),
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


def test_run_save_doctor_reports_persisted_conflicts_and_interesting_actions(capsys) -> None:
    config = _config(Path("gamehub"))
    snapshot = SyncDiagnosticsSnapshot(
        state=SyncState(
            unresolved_save_conflicts={
                "save_ps2_ffx_1": "both-changed-manual",
                "savebind_deadbeefcafefeed": "save-binding-root-ambiguous",
            }
        ),
        index=_empty_index(),
        plan=SyncPlan(
            save_actions=[
                SavePlanAction(
                    save_id="save_ps2_ffx_1",
                    binding_id="savebind_deadbeefcafefeed",
                    title_id="title_ps2_ffx",
                    system="PS2",
                    kind="memory_card",
                    decision="conflict",
                    reason="both-changed-manual",
                    url="/v1/saves/save_ps2_ffx_1",
                    destination=Path("saves/PS2/FFX.ps2"),
                    canonical_suffix="FFX.ps2",
                    expected_sha256="a" * 64,
                    size_bytes=1024,
                    remote_updated_at="2026-03-16T00:00:00+00:00",
                ),
                SavePlanAction(
                    save_id="save_gbc_links_1",
                    binding_id="savebind_1111111111111111",
                    title_id="title_gbc_links",
                    system="GBC",
                    kind="battery",
                    decision="skip",
                    reason="download-mode-local-drift",
                    url="/v1/saves/save_gbc_links_1",
                    destination=Path("saves/GBC/Links.srm"),
                    canonical_suffix="Links.srm",
                    expected_sha256="b" * 64,
                    size_bytes=2048,
                    remote_updated_at="2026-03-16T00:00:00+00:00",
                    local_sha256="c" * 64,
                ),
                SavePlanAction(
                    save_id="save_nes_mario_1",
                    binding_id="savebind_2222222222222222",
                    title_id="title_nes_mario",
                    system="NES",
                    kind="battery",
                    decision="skip",
                    reason="already-synced",
                    url="/v1/saves/save_nes_mario_1",
                    destination=Path("saves/NES/Mario.srm"),
                    canonical_suffix="Mario.srm",
                    expected_sha256="d" * 64,
                    size_bytes=512,
                    remote_updated_at="2026-03-16T00:00:00+00:00",
                    local_sha256="d" * 64,
                ),
            ]
        ),
    )

    exit_code = run_save_doctor(config, verify=False, verbose=False, snapshot=snapshot)

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "save-doctor\tstate_path=gamehub/state.json\tpersisted_conflicts=2\tinteresting_actions=2" in output
    assert "save-doctor\tpersisted-conflict\tscope=save\tid=save_ps2_ffx_1\treason=both-changed-manual" in output
    assert (
        "save-doctor\tpersisted-conflict\tscope=binding\tid=savebind_deadbeefcafefeed\t"
        "reason=save-binding-root-ambiguous" in output
    )
    assert "save-doctor\tstatus=drift\tdecision=conflict\tsystem=PS2" in output
    assert "save-doctor\tstatus=drift\tdecision=skip\tsystem=GBC" in output
    assert "save_nes_mario_1" not in output
    assert "save-doctor\tsummary\tpersisted_conflicts=2\tinteresting_actions=2\ttotal_actions=3" in output


def test_run_doctor_all_aggregates_controller_and_sync_audits(monkeypatch) -> None:
    config = _config(Path("gamehub"))
    order: list[str] = []
    diagnostic_snapshot = SyncDiagnosticsSnapshot(state=SyncState(), index=_empty_index(), plan=SyncPlan())
    monkeypatch.setattr("gamehub_cli.main._load_existing_config", lambda config_path=None: config)
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
        "gamehub_cli.main.run_save_doctor",
        lambda loaded, verify, verbose, snapshot=None: order.append(f"saves:{snapshot is diagnostic_snapshot}") or 0,
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
    assert order == ["controllers", "snapshot", "saves:True", "firmware:True", "roms:True"]
