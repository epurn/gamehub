from __future__ import annotations

from pathlib import Path

from gamehub_cli.config import ControllersConfig, GamehubConfig
from gamehub_cli.controller_detection import XboxController
from gamehub_cli.controller_launch import (
    encode_controller_payload,
    parse_controller_payload,
    run_controller_launch,
)


def _config() -> GamehubConfig:
    return GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("D:/GameHub"),
        firmware_dir=Path("D:/GameHub/firmware"),
        state_path=Path("D:/GameHub/state.json"),
        steam_userdata_dir=None,
        steam_id=None,
        steam_exe=None,
        sgdb_api_key=None,
        sgdb_cache_dir=Path("D:/GameHub/cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        controllers=ControllersConfig(launch_autoconfig=True),
    )


def test_parse_controller_payload_round_trip() -> None:
    token = encode_controller_payload(
        {
            "v": 1,
            "emulator": "pcsx2",
            "target_exe": "flatpak",
            "target_args": ["run", "--file-forwarding", "net.pcsx2.PCSX2"],
            "start_dir": "",
            "config_path": "D:/GameHub/config.toml",
        }
    )

    payload = parse_controller_payload(token)

    assert payload.version == 1
    assert payload.emulator == "pcsx2"
    assert payload.target_exe == "flatpak"
    assert payload.target_args == ("run", "--file-forwarding", "net.pcsx2.PCSX2")
    assert payload.config_path == "D:/GameHub/config.toml"


def test_run_controller_launch_fail_open_uses_kbm_fallback(monkeypatch) -> None:
    token = encode_controller_payload(
        {
            "v": 1,
            "emulator": "dolphin",
            "target_exe": "dolphin",
            "target_args": ["-b", "-e", "rom.iso"],
        }
    )
    config = _config()
    fallback_calls: list[str] = []

    monkeypatch.setattr("gamehub_cli.controller_launch.load_config", lambda path=None: config)
    monkeypatch.setattr("gamehub_cli.controller_launch.seed_default_profiles", lambda config: [])
    monkeypatch.setattr(
        "gamehub_cli.controller_launch.detect_xbox_controllers",
        lambda max_devices=2: [XboxController(slot=0, name="XInput/0", subtype=0)],
    )
    monkeypatch.setattr(
        "gamehub_cli.controller_launch.apply_controller_profile",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        "gamehub_cli.controller_launch.apply_named_controller_profile",
        lambda config, emulator_name, profile_name: fallback_calls.append(f"{emulator_name}:{profile_name}"),
    )
    monkeypatch.setattr("gamehub_cli.controller_launch._run_target", lambda payload: 7)

    exit_code = run_controller_launch(payload_token=token)

    assert exit_code == 7
    assert fallback_calls == ["dolphin:kbm"]


def test_run_controller_launch_detection_failure_falls_back_to_kbm_profile_selection(monkeypatch) -> None:
    token = encode_controller_payload(
        {
            "v": 1,
            "emulator": "pcsx2",
            "target_exe": "pcsx2-qt.exe",
            "target_args": ["--nogui", "game.iso"],
        }
    )
    config = _config()
    applied_counts: list[int] = []

    monkeypatch.setattr("gamehub_cli.controller_launch.load_config", lambda path=None: config)
    monkeypatch.setattr("gamehub_cli.controller_launch.seed_default_profiles", lambda config: [])
    monkeypatch.setattr(
        "gamehub_cli.controller_launch.detect_xbox_controllers",
        lambda max_devices=2: (_ for _ in ()).throw(RuntimeError("detect failed")),
    )
    monkeypatch.setattr(
        "gamehub_cli.controller_launch.apply_controller_profile",
        lambda cfg, emulator_name, controller_count: applied_counts.append(controller_count),
    )
    monkeypatch.setattr("gamehub_cli.controller_launch._run_target", lambda payload: 3)

    exit_code = run_controller_launch(payload_token=token)

    assert exit_code == 3
    assert applied_counts == [0]
