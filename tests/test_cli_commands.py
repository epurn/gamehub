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
    }


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
    ("command_path", "helper_name"),
    [
        (["doctor", "roms", "--config", "config.toml", "--verify"], "_run_doctor_roms_command"),
        (["doctor", "firmware", "--config", "config.toml"], "_run_doctor_firmware_command"),
        (["doctor", "all", "--config", "config.toml", "--verify"], "_run_doctor_all_command"),
    ],
)
def test_typer_doctor_target_dispatches(monkeypatch, command_path: list[str], helper_name: str) -> None:
    assert cli_main.app is not None
    captured: dict[str, object] = {}
    monkeypatch.setattr(f"gamehub_cli.main.{helper_name}", lambda **kwargs: captured.update(kwargs) or 0)

    result = _RUNNER.invoke(cli_main.app, command_path)

    assert result.exit_code == 0
    expected = {
        "config_path": Path("config.toml"),
        "verbose": False,
        "verify": "--verify" in command_path,
    }
    assert captured == expected


def test_typer_rejects_legacy_doctor_flag_syntax() -> None:
    assert cli_main.app is not None

    result = _RUNNER.invoke(cli_main.app, ["doctor", "--controllers"])

    assert result.exit_code != 0
    assert "No such option" in result.output


def test_argparse_fallback_routes_init(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(cli_main, "app", None)
    monkeypatch.setattr("gamehub_cli.main._run_init_command", lambda **kwargs: captured.update(kwargs) or 0)
    monkeypatch.setattr("sys.argv", ["gamehub", "init", "--config", "config.toml", "--dry-run"])

    with pytest.raises(SystemExit) as exc:
        cli_main.main()

    assert exc.value.code == 0
    assert captured == {
        "config_path": Path("config.toml"),
        "dry_run": True,
        "verbose": False,
        "reseed_profiles": False,
    }


def test_argparse_fallback_routes_sync(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(cli_main, "app", None)
    monkeypatch.setattr("gamehub_cli.main._run_sync_command", lambda **kwargs: captured.update(kwargs) or 0)
    monkeypatch.setattr(
        "sys.argv",
        [
            "gamehub",
            "sync",
            "--config",
            "config.toml",
            "--verify",
            "--skip-steam",
            "--skip-steam-relaunch",
            "--require-steam-closed",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli_main.main()

    assert exc.value.code == 0
    assert captured == {
        "config_path": Path("config.toml"),
        "dry_run": False,
        "verbose": False,
        "verify": True,
        "require_steam_closed": True,
        "skip_steam": True,
        "skip_steam_relaunch": True,
        "reseed_profiles": False,
    }


def test_argparse_fallback_routes_nested_doctor_command(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(cli_main, "app", None)
    monkeypatch.setattr("gamehub_cli.main._run_doctor_all_command", lambda **kwargs: captured.update(kwargs) or 0)
    monkeypatch.setattr("sys.argv", ["gamehub", "doctor", "all", "--config", "config.toml", "--verify"])

    with pytest.raises(SystemExit) as exc:
        cli_main.main()

    assert exc.value.code == 0
    assert captured == {
        "config_path": Path("config.toml"),
        "verbose": False,
        "verify": True,
    }


def test_argparse_fallback_rejects_legacy_doctor_flag_syntax(monkeypatch) -> None:
    monkeypatch.setattr(cli_main, "app", None)
    monkeypatch.setattr("sys.argv", ["gamehub", "doctor", "--controllers"])

    with pytest.raises(SystemExit) as exc:
        cli_main.main()

    assert exc.value.code == 2
