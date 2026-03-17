from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import gamehub_cli.main as cli_main

_RUNNER = CliRunner()


def test_typer_init_command_dispatches(monkeypatch) -> None:
    assert cli_main.app is not None
    captured: dict[str, object] = {}
    monkeypatch.setattr("gamehub_cli.main._run_init_command", lambda **kwargs: captured.update(kwargs) or 0)

    result = _RUNNER.invoke(
        cli_main.app,
        ["init", "--config", "config.toml", "--dry-run", "--verbose", "--reseed-profiles"],
    )

    assert result.exit_code == 0
    assert captured == {
        "config_path": Path("config.toml"),
        "dry_run": True,
        "verbose": True,
        "reseed_profiles": True,
    }


def test_typer_sync_command_dispatches(monkeypatch) -> None:
    assert cli_main.app is not None
    captured: dict[str, object] = {}
    monkeypatch.setattr("gamehub_cli.main._run_sync_command", lambda **kwargs: captured.update(kwargs) or 0)

    result = _RUNNER.invoke(
        cli_main.app,
        [
            "sync",
            "--config",
            "config.toml",
            "--dry-run",
            "--verbose",
            "--verify",
            "--skip-steam",
            "--skip-steam-relaunch",
            "--require-steam-closed",
            "--reseed-profiles",
        ],
    )

    assert result.exit_code == 0
    assert captured == {
        "config_path": Path("config.toml"),
        "dry_run": True,
        "verbose": True,
        "verify": True,
        "require_steam_closed": True,
        "skip_steam": True,
        "skip_steam_relaunch": True,
        "reseed_profiles": True,
        "json_summary": False,
    }


def test_typer_sync_command_dispatches_json_summary(monkeypatch) -> None:
    assert cli_main.app is not None
    captured: dict[str, object] = {}
    monkeypatch.setattr("gamehub_cli.main._run_sync_command", lambda **kwargs: captured.update(kwargs) or 0)

    result = _RUNNER.invoke(
        cli_main.app,
        ["sync", "--config", "config.toml", "--json-summary"],
    )

    assert result.exit_code == 0
    assert captured == {
        "config_path": Path("config.toml"),
        "dry_run": False,
        "verbose": False,
        "verify": False,
        "require_steam_closed": False,
        "skip_steam": False,
        "skip_steam_relaunch": False,
        "reseed_profiles": False,
        "json_summary": True,
    }


def test_typer_shortcut_launch_dispatches(monkeypatch) -> None:
    assert cli_main.app is not None
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "gamehub_cli.main.run_shortcut_launch",
        lambda **kwargs: captured.update(kwargs) or 0,
    )

    result = _RUNNER.invoke(
        cli_main.app,
        [
            "shortcut-launch",
            "--payload",
            "encoded-payload",
            "--payload-ref",
            "title_ps2_gt4",
            "--payload-registry",
            "payloads.json",
            "--config",
            "config.toml",
        ],
    )

    assert result.exit_code == 0
    assert captured == {
        "payload_token": "encoded-payload",
        "payload_ref": "title_ps2_gt4",
        "payload_registry_path": Path("payloads.json"),
        "config_path": Path("config.toml"),
    }


def test_typer_shortcut_launch_rejects_removed_audit_flag() -> None:
    assert cli_main.app is not None

    result = _RUNNER.invoke(cli_main.app, ["shortcut-launch", "--payload", "encoded-payload", "--audit"])

    assert result.exit_code != 0
    assert "No such option" in result.output


def test_typer_config_init_dispatches(monkeypatch) -> None:
    assert cli_main.app is not None
    captured: dict[str, object] = {}
    monkeypatch.setattr("gamehub_cli.main._run_config_init_command", lambda **kwargs: captured.update(kwargs) or 0)

    result = _RUNNER.invoke(
        cli_main.app,
        [
            "config",
            "init",
            "--output",
            "config.toml",
            "--server-url",
            "http://srv:8000",
            "--gamehub-dir",
            "GameHub",
            "--steam-userdata",
            "userdata",
            "--steam-id",
            "76561198000000001",
            "--no-controller-autoconfig",
            "--save-sync",
            "--save-sync-mode",
            "bidirectional",
            "--conflict-policy",
            "prefer_server",
        ],
    )

    assert result.exit_code == 0
    assert captured == {
        "output_path": Path("config.toml"),
        "server_url": "http://srv:8000",
        "gamehub_dir": Path("GameHub"),
        "steam_userdata_dir": Path("userdata"),
        "steam_id": "76561198000000001",
        "controller_launch_autoconfig": False,
        "save_sync_enabled": True,
        "save_sync_mode": "bidirectional",
        "save_sync_conflict_policy": "prefer_server",
    }


def test_typer_config_verify_dispatches(monkeypatch) -> None:
    assert cli_main.app is not None
    captured: dict[str, object] = {}
    monkeypatch.setattr("gamehub_cli.main._run_config_verify_command", lambda **kwargs: captured.update(kwargs) or 0)

    result = _RUNNER.invoke(cli_main.app, ["config", "verify", "--config", "config.toml"])

    assert result.exit_code == 0
    assert captured == {"config_path": Path("config.toml")}


def test_typer_doctor_controllers_dispatches(monkeypatch) -> None:
    assert cli_main.app is not None
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "gamehub_cli.main._run_doctor_controllers_command",
        lambda **kwargs: captured.update(kwargs) or 0,
    )

    result = _RUNNER.invoke(
        cli_main.app,
        ["doctor", "controllers", "--config", "config.toml", "--apply", "--force"],
    )

    assert result.exit_code == 0
    assert captured == {
        "config_path": Path("config.toml"),
        "apply": True,
        "force": True,
    }


@pytest.mark.parametrize(
    ("command_path", "helper_name", "expected"),
    [
        (
            ["doctor", "roms", "--config", "config.toml", "--verify"],
            "_run_doctor_roms_command",
            {"config_path": Path("config.toml"), "verbose": False, "verify": True},
        ),
        (
            ["doctor", "firmware", "--config", "config.toml"],
            "_run_doctor_firmware_command",
            {"config_path": Path("config.toml"), "verbose": False, "verify": False},
        ),
        (
            ["doctor", "saves", "--config", "config.toml", "--verify"],
            "_run_doctor_saves_command",
            {
                "config_path": Path("config.toml"),
                "verbose": False,
                "verify": True,
                "dry_run": False,
                "keep_local_save_id": None,
                "keep_server_save_id": None,
            },
        ),
        (
            ["doctor", "all", "--config", "config.toml", "--verify"],
            "_run_doctor_all_command",
            {"config_path": Path("config.toml"), "verbose": False, "verify": True},
        ),
    ],
)
def test_typer_doctor_target_dispatches(
    monkeypatch, command_path: list[str], helper_name: str, expected: dict[str, object]
) -> None:
    assert cli_main.app is not None
    captured: dict[str, object] = {}
    monkeypatch.setattr(f"gamehub_cli.main.{helper_name}", lambda **kwargs: captured.update(kwargs) or 0)

    result = _RUNNER.invoke(cli_main.app, command_path)

    assert result.exit_code == 0
    assert captured == expected


def test_typer_doctor_saves_resolution_dispatches(monkeypatch) -> None:
    assert cli_main.app is not None
    captured: dict[str, object] = {}
    monkeypatch.setattr("gamehub_cli.main._run_doctor_saves_command", lambda **kwargs: captured.update(kwargs) or 0)

    result = _RUNNER.invoke(
        cli_main.app,
        ["doctor", "saves", "--config", "config.toml", "--keep-local", "save_ps2_ffx_1", "--dry-run"],
    )

    assert result.exit_code == 0
    assert captured == {
        "config_path": Path("config.toml"),
        "verbose": False,
        "verify": False,
        "dry_run": True,
        "keep_local_save_id": "save_ps2_ffx_1",
        "keep_server_save_id": None,
    }


def test_typer_doctor_server_dispatches(monkeypatch) -> None:
    assert cli_main.app is not None
    captured: dict[str, object] = {}
    monkeypatch.setattr("gamehub_cli.main._run_doctor_server_command", lambda **kwargs: captured.update(kwargs) or 0)

    result = _RUNNER.invoke(
        cli_main.app,
        ["doctor", "server", "--config", "config.toml", "--server-url", "http://srv:8000", "--json"],
    )

    assert result.exit_code == 0
    assert captured == {
        "config_path": Path("config.toml"),
        "server_url": "http://srv:8000",
        "json_output": True,
    }


def test_typer_rejects_legacy_doctor_flag_syntax() -> None:
    assert cli_main.app is not None

    result = _RUNNER.invoke(cli_main.app, ["doctor", "--controllers"])

    assert result.exit_code != 0
    assert "No such option" in result.output


@pytest.mark.parametrize(
    "command_path",
    [
        ["sync", "--dry-run"],
        ["doctor", "roms"],
    ],
)
def test_typer_requires_existing_config_for_user_facing_commands(command_path: list[str]) -> None:
    assert cli_main.app is not None
    missing_config = Path("missing-config.toml")

    result = _RUNNER.invoke(cli_main.app, [*command_path, "--config", str(missing_config)])

    assert result.exit_code != 0
    assert "Config file not found" in result.output
    assert str(missing_config) in result.output
    assert "docs/templates" in result.output
