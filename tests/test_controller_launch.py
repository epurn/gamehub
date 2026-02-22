from __future__ import annotations

import os
from pathlib import Path

from gamehub_cli.common.config import ControllersConfig, GamehubConfig
from gamehub_cli.controllers.detection import XboxController
from gamehub_cli.controllers.launch import (
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


def test_parse_controller_payload_strips_wrapping_quotes_from_args() -> None:
    token = encode_controller_payload(
        {
            "v": 1,
            "emulator": "dolphin",
            "target_exe": '"C:/Emu/Dolphin.exe"',
            "target_args": ['"-b"', '"C:/Games/Path With Spaces/game.iso"'],
            "start_dir": '"C:/Emu"',
        }
    )

    payload = parse_controller_payload(token)

    assert payload.target_exe == '"C:/Emu/Dolphin.exe"'
    assert payload.target_args == ("-b", "C:/Games/Path With Spaces/game.iso")


def test_run_controller_launch_sets_azahar_sdl_dir_env(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-azahar-sdl-") as temp_root:
        azahar_dir = temp_root / "Azahar"
        azahar_dir.mkdir(parents=True, exist_ok=True)
        azahar_exe = azahar_dir / "azahar.exe"
        azahar_exe.write_text("", encoding="utf-8")

        token = encode_controller_payload(
            {
                "v": 1,
                "emulator": "azahar",
                "target_exe": str(azahar_exe),
                "target_args": ["-f", "rom.3ds"],
            }
        )
        config = _config()
        observed: dict[str, str] = {}

        monkeypatch.setattr("gamehub_cli.controllers.launch.load_config", lambda path=None: config)
        monkeypatch.setattr("gamehub_cli.controllers.launch.seed_default_profiles", lambda config: [])
        monkeypatch.setattr("gamehub_cli.controllers.launch.detect_xbox_controllers", lambda max_devices=2: [])
        monkeypatch.setattr(
            "gamehub_cli.controllers.launch.apply_controller_profile",
            lambda *args, **kwargs: observed.setdefault("sdl_dir", os.environ.get("GAMEHUB_AZAHAR_SDL_DIR", "")),
        )
        monkeypatch.setattr("gamehub_cli.controllers.launch._run_target", lambda payload: 0)
        monkeypatch.delenv("GAMEHUB_AZAHAR_SDL_DIR", raising=False)

        run_controller_launch(payload_token=token)

        assert observed["sdl_dir"] == str(azahar_dir)


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

    monkeypatch.setattr("gamehub_cli.controllers.launch.load_config", lambda path=None: config)
    monkeypatch.setattr("gamehub_cli.controllers.launch.seed_default_profiles", lambda config: [])
    monkeypatch.setattr(
        "gamehub_cli.controllers.launch.detect_xbox_controllers",
        lambda max_devices=2: [XboxController(slot=0, name="XInput/0", subtype=0)],
    )
    monkeypatch.setattr(
        "gamehub_cli.controllers.launch.apply_controller_profile",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        "gamehub_cli.controllers.launch.apply_named_controller_profile",
        lambda config, emulator_name, profile_name: fallback_calls.append(f"{emulator_name}:{profile_name}"),
    )
    monkeypatch.setattr("gamehub_cli.controllers.launch._run_target", lambda payload: 7)

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

    monkeypatch.setattr("gamehub_cli.controllers.launch.load_config", lambda path=None: config)
    monkeypatch.setattr("gamehub_cli.controllers.launch.seed_default_profiles", lambda config: [])
    monkeypatch.setattr("gamehub_cli.controllers.launch.is_steam_deck_linux", lambda: False)
    monkeypatch.setattr(
        "gamehub_cli.controllers.launch.detect_xbox_controllers",
        lambda max_devices=2: (_ for _ in ()).throw(RuntimeError("detect failed")),
    )
    monkeypatch.setattr(
        "gamehub_cli.controllers.launch.apply_controller_profile",
        lambda cfg, emulator_name, controller_count: applied_counts.append(controller_count),
    )
    monkeypatch.setattr("gamehub_cli.controllers.launch._run_target", lambda payload: 3)

    exit_code = run_controller_launch(payload_token=token)

    assert exit_code == 3
    assert applied_counts == [0]


def test_run_controller_launch_uses_azahar_windows_exit_hook(monkeypatch) -> None:
    token = encode_controller_payload(
        {
            "v": 1,
            "emulator": "azahar",
            "target_exe": "C:/Emu/Azahar.exe",
            "target_args": ["-f", "rom.3ds"],
        }
    )
    config = _config()
    hook_calls: list[str] = []

    monkeypatch.setattr("gamehub_cli.controllers.launch.load_config", lambda path=None: config)
    monkeypatch.setattr("gamehub_cli.controllers.launch.seed_default_profiles", lambda config: [])
    monkeypatch.setattr("gamehub_cli.controllers.launch.detect_xbox_controllers", lambda max_devices=2: [])
    monkeypatch.setattr("gamehub_cli.controllers.launch.apply_controller_profile", lambda *args, **kwargs: None)
    monkeypatch.setattr("gamehub_cli.controllers.launch.sys.platform", "win32")
    monkeypatch.setenv("GAMEHUB_AZAHAR_WINDOWS_EXIT_HOOK", "true")
    monkeypatch.setattr(
        "gamehub_cli.controllers.launch._run_windows_azahar_target_with_exit_hook",
        lambda payload: hook_calls.append(payload.emulator) or 11,
    )
    monkeypatch.setattr(
        "gamehub_cli.controllers.launch._run_target",
        lambda payload: (_ for _ in ()).throw(AssertionError("direct launch should not be used")),
    )

    exit_code = run_controller_launch(payload_token=token)

    assert exit_code == 11
    assert hook_calls == ["azahar"]


def test_run_controller_launch_uses_dolphin_linux_exit_hook_for_flatpak(monkeypatch) -> None:
    token = encode_controller_payload(
        {
            "v": 1,
            "emulator": "dolphin",
            "target_exe": "flatpak",
            "target_args": ["run", "--device=all", "org.DolphinEmu.dolphin-emu", "-b", "-e", "game.iso"],
        }
    )
    config = _config()
    hook_calls: list[str] = []

    monkeypatch.setattr("gamehub_cli.controllers.launch.load_config", lambda path=None: config)
    monkeypatch.setattr("gamehub_cli.controllers.launch.seed_default_profiles", lambda config: [])
    monkeypatch.setattr("gamehub_cli.controllers.launch.detect_xbox_controllers", lambda max_devices=2: [])
    monkeypatch.setattr("gamehub_cli.controllers.launch.apply_controller_profile", lambda *args, **kwargs: None)
    monkeypatch.setattr("gamehub_cli.controllers.launch.sys.platform", "linux")
    monkeypatch.setattr(
        "gamehub_cli.controllers.launch._run_linux_dolphin_target_with_exit_hook",
        lambda payload: hook_calls.append(payload.emulator) or 9,
    )
    monkeypatch.setattr(
        "gamehub_cli.controllers.launch._run_target",
        lambda payload: (_ for _ in ()).throw(AssertionError("direct launch should not be used")),
    )

    exit_code = run_controller_launch(payload_token=token)

    assert exit_code == 9
    assert hook_calls == ["dolphin"]


def test_run_controller_launch_audit_enables_verbose_profile_logs(monkeypatch) -> None:
    token = encode_controller_payload(
        {
            "v": 1,
            "emulator": "dolphin",
            "target_exe": "dolphin",
            "target_args": ["-b", "-e", "rom.iso"],
        }
    )
    config = _config()
    observed: dict[str, object] = {}

    monkeypatch.setattr("gamehub_cli.controllers.launch.load_config", lambda path=None: config)
    monkeypatch.setattr("gamehub_cli.controllers.launch.seed_default_profiles", lambda config: [])
    monkeypatch.setattr("gamehub_cli.controllers.launch.detect_xbox_controllers", lambda max_devices=2: [])

    def _fake_apply(*args, **kwargs):
        observed["verbose"] = kwargs.get("verbose")
        return "kbm"

    monkeypatch.setattr("gamehub_cli.controllers.launch.apply_controller_profile", _fake_apply)
    monkeypatch.setattr("gamehub_cli.controllers.launch._run_target", lambda payload: 0)

    exit_code = run_controller_launch(payload_token=token, audit=True)

    assert exit_code == 0
    assert observed["verbose"] is True


def test_run_controller_launch_can_disable_dolphin_linux_exit_hook(monkeypatch) -> None:
    token = encode_controller_payload(
        {
            "v": 1,
            "emulator": "dolphin",
            "target_exe": "flatpak",
            "target_args": ["run", "--device=all", "org.DolphinEmu.dolphin-emu", "-b", "-e", "game.iso"],
        }
    )
    config = _config()

    monkeypatch.setattr("gamehub_cli.controllers.launch.load_config", lambda path=None: config)
    monkeypatch.setattr("gamehub_cli.controllers.launch.seed_default_profiles", lambda config: [])
    monkeypatch.setattr("gamehub_cli.controllers.launch.detect_xbox_controllers", lambda max_devices=2: [])
    monkeypatch.setattr("gamehub_cli.controllers.launch.apply_controller_profile", lambda *args, **kwargs: None)
    monkeypatch.setattr("gamehub_cli.controllers.launch.sys.platform", "linux")
    monkeypatch.setenv("GAMEHUB_DOLPHIN_LINUX_EXIT_HOOK", "false")
    monkeypatch.setattr(
        "gamehub_cli.controllers.launch._run_linux_dolphin_target_with_exit_hook",
        lambda payload: (_ for _ in ()).throw(AssertionError("hook should be disabled")),
    )
    monkeypatch.setattr("gamehub_cli.controllers.launch._run_target", lambda payload: 4)

    exit_code = run_controller_launch(payload_token=token)

    assert exit_code == 4


def test_run_controller_launch_deck_zero_detect_defaults_to_xbox_1p(monkeypatch, capsys) -> None:
    token = encode_controller_payload(
        {
            "v": 1,
            "emulator": "dolphin",
            "target_exe": "dolphin",
            "target_args": ["-b", "-e", "rom.iso"],
        }
    )
    config = _config()
    observed: dict[str, int] = {}

    monkeypatch.setattr("gamehub_cli.controllers.launch.load_config", lambda path=None: config)
    monkeypatch.setattr("gamehub_cli.controllers.launch.seed_default_profiles", lambda config: [])
    monkeypatch.setattr("gamehub_cli.controllers.launch.detect_xbox_controllers", lambda max_devices=2: [])
    monkeypatch.setattr("gamehub_cli.controllers.launch.sys.platform", "linux")
    monkeypatch.setattr("gamehub_cli.controllers.launch.is_steam_deck_linux", lambda: True)
    monkeypatch.delenv("GAMEHUB_DECK_ZERO_DETECT_POLICY", raising=False)

    def _apply(cfg, emulator_name, controller_count, verbose=False):
        observed["count"] = controller_count
        return "xbox_1p"

    monkeypatch.setattr(
        "gamehub_cli.controllers.launch.apply_controller_profile",
        _apply,
    )
    monkeypatch.setattr("gamehub_cli.controllers.launch._run_target", lambda payload: 0)

    exit_code = run_controller_launch(payload_token=token, audit=True)

    assert exit_code == 0
    assert observed["count"] == 1
    out = capsys.readouterr().out
    assert "zero_detect_policy=xbox_1p" in out
    assert "effective_controller_count=1" in out


def test_run_controller_launch_deck_zero_detect_kbm_policy_keeps_zero(monkeypatch, capsys) -> None:
    token = encode_controller_payload(
        {
            "v": 1,
            "emulator": "dolphin",
            "target_exe": "dolphin",
            "target_args": ["-b", "-e", "rom.iso"],
        }
    )
    config = _config()
    observed: dict[str, int] = {}

    monkeypatch.setattr("gamehub_cli.controllers.launch.load_config", lambda path=None: config)
    monkeypatch.setattr("gamehub_cli.controllers.launch.seed_default_profiles", lambda config: [])
    monkeypatch.setattr("gamehub_cli.controllers.launch.detect_xbox_controllers", lambda max_devices=2: [])
    monkeypatch.setattr("gamehub_cli.controllers.launch.sys.platform", "linux")
    monkeypatch.setattr("gamehub_cli.controllers.launch.is_steam_deck_linux", lambda: True)
    monkeypatch.setenv("GAMEHUB_DECK_ZERO_DETECT_POLICY", "kbm")

    def _apply(cfg, emulator_name, controller_count, verbose=False):
        observed["count"] = controller_count
        return "kbm"

    monkeypatch.setattr(
        "gamehub_cli.controllers.launch.apply_controller_profile",
        _apply,
    )
    monkeypatch.setattr("gamehub_cli.controllers.launch._run_target", lambda payload: 0)

    exit_code = run_controller_launch(payload_token=token, audit=True)

    assert exit_code == 0
    assert observed["count"] == 0
    out = capsys.readouterr().out
    assert "zero_detect_policy=kbm" in out
    assert "effective_controller_count=0" in out


def test_run_controller_launch_deck_zero_detect_abort_policy_stops_launch(monkeypatch) -> None:
    token = encode_controller_payload(
        {
            "v": 1,
            "emulator": "dolphin",
            "target_exe": "dolphin",
            "target_args": ["-b", "-e", "rom.iso"],
        }
    )
    config = _config()

    monkeypatch.setattr("gamehub_cli.controllers.launch.load_config", lambda path=None: config)
    monkeypatch.setattr("gamehub_cli.controllers.launch.seed_default_profiles", lambda config: [])
    monkeypatch.setattr("gamehub_cli.controllers.launch.detect_xbox_controllers", lambda max_devices=2: [])
    monkeypatch.setattr("gamehub_cli.controllers.launch.sys.platform", "linux")
    monkeypatch.setattr("gamehub_cli.controllers.launch.is_steam_deck_linux", lambda: True)
    monkeypatch.setenv("GAMEHUB_DECK_ZERO_DETECT_POLICY", "abort")
    monkeypatch.setattr(
        "gamehub_cli.controllers.launch.apply_controller_profile",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("profile apply should not run")),
    )
    monkeypatch.setattr(
        "gamehub_cli.controllers.launch._run_target",
        lambda payload: (_ for _ in ()).throw(AssertionError("target launch should not run")),
    )

    exit_code = run_controller_launch(payload_token=token, audit=True)

    assert exit_code == 2


def test_run_controller_launch_non_deck_zero_detect_behavior_unchanged(monkeypatch) -> None:
    token = encode_controller_payload(
        {
            "v": 1,
            "emulator": "dolphin",
            "target_exe": "dolphin",
            "target_args": ["-b", "-e", "rom.iso"],
        }
    )
    config = _config()
    observed: dict[str, int] = {}

    monkeypatch.setattr("gamehub_cli.controllers.launch.load_config", lambda path=None: config)
    monkeypatch.setattr("gamehub_cli.controllers.launch.seed_default_profiles", lambda config: [])
    monkeypatch.setattr("gamehub_cli.controllers.launch.detect_xbox_controllers", lambda max_devices=2: [])
    monkeypatch.setattr("gamehub_cli.controllers.launch.sys.platform", "linux")
    monkeypatch.setattr("gamehub_cli.controllers.launch.is_steam_deck_linux", lambda: False)
    monkeypatch.delenv("GAMEHUB_DECK_ZERO_DETECT_POLICY", raising=False)

    def _apply(cfg, emulator_name, controller_count, verbose=False):
        observed["count"] = controller_count
        return "kbm"

    monkeypatch.setattr(
        "gamehub_cli.controllers.launch.apply_controller_profile",
        _apply,
    )
    monkeypatch.setattr("gamehub_cli.controllers.launch._run_target", lambda payload: 0)

    exit_code = run_controller_launch(payload_token=token)

    assert exit_code == 0
    assert observed["count"] == 0
