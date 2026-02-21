from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import subprocess
import shutil
import sys
from uuid import uuid4

from gamehub_cli.config import ControllersConfig, GamehubConfig
from gamehub_cli.controller_detection import XboxController
from gamehub_cli.controller_apply import apply_controller_profile, apply_named_controller_profile
from gamehub_cli.controller_profiles import seed_default_profiles


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
        controllers=ControllersConfig(),
    )


def test_apply_controller_profile_pcsx2_kbm_preserves_unmanaged_sections() -> None:
    with _workspace_tempdir("gamehub-controller-apply-") as temp_root:
        base = _config(temp_root)
        ini_path = temp_root / "pcsx2" / "PCSX2.ini"
        config = replace(base, linux=replace(base.linux, pcsx2_ini_path=ini_path))
        seed_default_profiles(config)
        ini_path.parent.mkdir(parents=True, exist_ok=True)
        ini_path.write_text("[Audio]\nLatency = 42\n", encoding="utf-8")

        profile = apply_controller_profile(config, emulator_name="pcsx2", controller_count=0)
        text = ini_path.read_text(encoding="utf-8")

        assert profile == "kbm"
        assert "[Audio]" in text
        assert "Latency = 42" in text
        assert "OpenPauseMenu = Keyboard/Escape" in text
        assert "Cross = Keyboard/K" in text


def test_apply_controller_profile_pcsx2_xbox_modes() -> None:
    with _workspace_tempdir("gamehub-controller-apply-") as temp_root:
        base = _config(temp_root)
        ini_path = temp_root / "pcsx2" / "PCSX2.ini"
        config = replace(base, linux=replace(base.linux, pcsx2_ini_path=ini_path))
        seed_default_profiles(config)

        profile_1 = apply_controller_profile(config, emulator_name="pcsx2", controller_count=1)
        text_1 = ini_path.read_text(encoding="utf-8")
        assert profile_1 == "xbox_1p"
        assert "Cross = SDL-0/A" in text_1
        assert "Cross = Keyboard/K" in text_1
        assert "Cross = Keyboard/Num0" not in text_1
        assert "OpenPauseMenu = SDL-0/Back & SDL-0/Start" in text_1
        assert "ConfirmShutdown = false" in text_1

        profile_2 = apply_controller_profile(config, emulator_name="pcsx2", controller_count=2)
        text_2 = ini_path.read_text(encoding="utf-8")
        assert profile_2 == "xbox_2p"
        assert "Cross = SDL-0/A" in text_2
        assert "Cross = SDL-1/A" in text_2
        assert "ConfirmShutdown = false" in text_2


def test_apply_controller_profile_pcsx2_writes_confirm_shutdown_false() -> None:
    with _workspace_tempdir("gamehub-controller-apply-") as temp_root:
        base = _config(temp_root)
        ini_path = temp_root / "pcsx2" / "PCSX2.ini"
        config = replace(base, linux=replace(base.linux, pcsx2_ini_path=ini_path))
        seed_default_profiles(config)
        ini_path.parent.mkdir(parents=True, exist_ok=True)
        ini_path.write_text("[UI]\nConfirmShutdown = true\n", encoding="utf-8")

        apply_controller_profile(config, emulator_name="pcsx2", controller_count=0)
        text = ini_path.read_text(encoding="utf-8")

        assert "ConfirmShutdown = false" in text


def test_apply_controller_profile_accepts_emulator_family_alias() -> None:
    with _workspace_tempdir("gamehub-controller-apply-") as temp_root:
        base = _config(temp_root)
        ini_path = temp_root / "pcsx2" / "PCSX2.ini"
        config = replace(base, linux=replace(base.linux, pcsx2_ini_path=ini_path))
        seed_default_profiles(config)

        profile = apply_controller_profile(config, emulator_name="PCSX2-nightly", controller_count=1)
        text = ini_path.read_text(encoding="utf-8")

        assert profile == "xbox_1p"
        assert "Cross = SDL-0/A" in text


def test_apply_controller_profile_dolphin_xbox_writes_managed_sections(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "GCPadNew.ini").write_text("[User]\nFoo = Bar\n", encoding="utf-8")

        monkeypatch.setattr("gamehub_cli.controller_apply.detect_xbox_controllers", lambda max_devices=2: [])
        monkeypatch.setattr("gamehub_cli.controller_apply.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root)
        monkeypatch.setattr("gamehub_cli.controller_apply.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root])

        profile = apply_controller_profile(config, emulator_name="dolphin", controller_count=2)

        gcpad_text = (config_dir / "GCPadNew.ini").read_text(encoding="utf-8")
        hotkeys_text = (config_dir / "Hotkeys.ini").read_text(encoding="utf-8")
        dolphin_text = (config_dir / "Dolphin.ini").read_text(encoding="utf-8")
        assert profile == "xbox_2p"
        assert "[User]" in gcpad_text
        assert "Foo = Bar" in gcpad_text
        assert "[Core]" in dolphin_text
        assert "SIDevice0 = 6" in dolphin_text
        assert "SIDevice1 = 6" in dolphin_text
        assert "[Controls]" in dolphin_text
        assert "WiimoteSource0 = 1" in dolphin_text
        assert "WiimoteSource1 = 1" in dolphin_text
        if sys.platform.startswith("linux"):
            assert "Device = SDL/0/Gamepad" in gcpad_text
            assert "Device = SDL/1/Gamepad" in gcpad_text
            assert "Device = All Devices" in hotkeys_text
        else:
            assert "Device = XInput/0/Gamepad" in gcpad_text
            assert "Device = XInput/1/Gamepad" in gcpad_text
        assert (
            "General/Stop = ((`BACK` | `Back` | `SELECT` | `Select` | `Button 6`) & "
            "(`START` | `Start` | `Button 7`))"
        ) in hotkeys_text
        assert (
            "General/Exit = ((`BACK` | `Back` | `SELECT` | `Select` | `Button 6`) & "
            "(`START` | `Start` | `Button 7`))"
        ) in hotkeys_text


def test_apply_controller_profile_dolphin_xbox_1p_uses_kbm_bindings_for_p2_gc(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.controller_apply.detect_xbox_controllers", lambda max_devices=2: [])
        monkeypatch.setattr("gamehub_cli.controller_apply.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root)
        monkeypatch.setattr("gamehub_cli.controller_apply.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root])

        apply_controller_profile(config, emulator_name="dolphin", controller_count=1)
        gcpad_text = (config_dir / "GCPadNew.ini").read_text(encoding="utf-8")

        assert "[GCPad1]" in gcpad_text
        assert "[GCPad2]" in gcpad_text
        assert "Buttons/A = SOUTH | `Button A`" in gcpad_text
        assert "Buttons/A = X" in gcpad_text


def test_apply_controller_profile_dolphin_xbox_1p_uses_kbm_bindings_for_p2_wii(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.controller_apply.detect_xbox_controllers", lambda max_devices=2: [])
        monkeypatch.setattr("gamehub_cli.controller_apply.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root)
        monkeypatch.setattr("gamehub_cli.controller_apply.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root])

        apply_controller_profile(config, emulator_name="dolphin", controller_count=1)
        wiimote_text = (config_dir / "WiimoteNew.ini").read_text(encoding="utf-8")

        assert "[Wiimote1]" in wiimote_text
        assert "[Wiimote2]" in wiimote_text
        assert "Buttons/A = SOUTH | `Button A`" in wiimote_text
        assert "Buttons/A = `Click 0`" in wiimote_text


def test_apply_controller_profile_dolphin_linux_prefers_evdev_from_detected_xbox(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.controller_apply.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controller_apply.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root)
        monkeypatch.setattr("gamehub_cli.controller_apply.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root])
        monkeypatch.setattr(
            "gamehub_cli.controller_apply.detect_xbox_controllers",
            lambda max_devices=2: [XboxController(slot=0, name="Xbox Wireless Controller", subtype=None)],
        )

        apply_controller_profile(config, emulator_name="dolphin", controller_count=1)
        gcpad_text = (config_dir / "GCPadNew.ini").read_text(encoding="utf-8")
        hotkeys_text = (config_dir / "Hotkeys.ini").read_text(encoding="utf-8")

        assert "Device = evdev/0/Xbox Wireless Controller" in gcpad_text
        assert "Device = All Devices" in hotkeys_text


def test_apply_controller_profile_dolphin_linux_kbm_uses_virtual_pointer_hotkeys(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.controller_apply.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controller_apply.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root)
        monkeypatch.setattr("gamehub_cli.controller_apply.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root])

        apply_controller_profile(config, emulator_name="dolphin", controller_count=0)
        gcpad_text = (config_dir / "GCPadNew.ini").read_text(encoding="utf-8")
        hotkeys_text = (config_dir / "Hotkeys.ini").read_text(encoding="utf-8")

        assert "Device = XInput2/0/Virtual core pointer" in gcpad_text
        assert "Device = None" in gcpad_text
        assert "Device = XInput2/0/Virtual core pointer" in hotkeys_text


def test_apply_controller_profile_azahar_kbm(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        qt_config = temp_root / "azahar" / "qt-config.ini"
        qt_config.parent.mkdir(parents=True, exist_ok=True)
        qt_config.write_text("custom_key=keep\n", encoding="utf-8")
        monkeypatch.setattr("gamehub_cli.controller_apply._azahar_target_config_paths", lambda: [qt_config])

        profile = apply_named_controller_profile(config, emulator_name="azahar", profile_name="kbm")
        text = qt_config.read_text(encoding="utf-8")

        assert profile == "kbm"
        assert "custom_key=keep" in text
        assert r'profiles\1\button_a="code:65,engine:keyboard"' in text


def test_apply_controller_profile_azahar_updates_all_known_target_paths(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        qt_a = temp_root / "azahar-a" / "qt-config.ini"
        qt_b = temp_root / "azahar-b" / "qt-config.ini"
        qt_a.parent.mkdir(parents=True, exist_ok=True)
        qt_b.parent.mkdir(parents=True, exist_ok=True)
        qt_a.write_text("custom_key=keep_a\n", encoding="utf-8")
        qt_b.write_text("custom_key=keep_b\n", encoding="utf-8")
        monkeypatch.setattr("gamehub_cli.controller_apply._azahar_target_config_paths", lambda: [qt_a, qt_b])

        apply_named_controller_profile(config, emulator_name="azahar", profile_name="kbm")

        assert "custom_key=keep_a" in qt_a.read_text(encoding="utf-8")
        assert "custom_key=keep_b" in qt_b.read_text(encoding="utf-8")
        assert r'profiles\1\button_a="code:65,engine:keyboard"' in qt_a.read_text(encoding="utf-8")
        assert r'profiles\1\button_a="code:65,engine:keyboard"' in qt_b.read_text(encoding="utf-8")


def test_apply_controller_profile_azahar_linux_preserves_existing_sdl_bindings_when_discovery_unavailable(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        qt_config = temp_root / "azahar" / "qt-config.ini"
        qt_config.parent.mkdir(parents=True, exist_ok=True)
        qt_config.write_text(
            "\n".join(
                [
                    "profile=0",
                    r'profiles\1\button_a="button:0,engine:sdl,guid:ABC123,port:1"',
                    r'profiles\1\button_select="button:4,engine:sdl,guid:ABC123,port:1"',
                    r'profiles\1\button_start="button:6,engine:sdl,guid:ABC123,port:1"',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("gamehub_cli.controller_apply.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controller_apply._azahar_target_config_paths", lambda: [qt_config])
        monkeypatch.setattr("gamehub_cli.controller_apply._is_azahar_flatpak_config_path", lambda path: True)
        monkeypatch.setattr("gamehub_cli.controller_apply._probe_azahar_flatpak_guid", lambda port=1: None)
        monkeypatch.setattr(
            "gamehub_cli.controller_apply._discover_linux_sdl_guid",
            lambda port=1: "040018dc5e040000130b000000006800",
        )

        apply_named_controller_profile(config, emulator_name="azahar", profile_name="xbox_1p")
        text = qt_config.read_text(encoding="utf-8")

        assert r'profiles\1\button_a="button:0,engine:sdl,guid:ABC123,port:1"' in text
        assert r'profiles\1\button_select="button:4,engine:sdl,guid:ABC123,port:1"' in text
        assert r'profiles\1\button_start="button:6,engine:sdl,guid:ABC123,port:1"' in text


def test_apply_controller_profile_azahar_linux_prefers_runtime_when_existing_matches_host(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        qt_config = temp_root / "azahar" / "qt-config.ini"
        qt_config.parent.mkdir(parents=True, exist_ok=True)
        qt_config.write_text(
            "\n".join(
                [
                    "profile=0",
                    r'profiles\1\button_a="button:0,engine:sdl,guid:11111111111111111111111111111111,port:0"',
                    r'profiles\1\button_select="button:4,engine:sdl,guid:11111111111111111111111111111111,port:0"',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("gamehub_cli.controller_apply.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controller_apply._azahar_target_config_paths", lambda: [qt_config])
        monkeypatch.setattr("gamehub_cli.controller_apply._is_azahar_flatpak_config_path", lambda path: True)
        monkeypatch.setattr(
            "gamehub_cli.controller_apply._probe_azahar_flatpak_guid",
            lambda port=0: "030018dc5e040000130b000000006800",
        )
        monkeypatch.setattr(
            "gamehub_cli.controller_apply._discover_linux_sdl_guid",
            lambda port=0: "11111111111111111111111111111111",
        )

        apply_named_controller_profile(config, emulator_name="azahar", profile_name="xbox_1p")
        text = qt_config.read_text(encoding="utf-8")

        assert r'profiles\1\button_a="button:0,engine:sdl,guid:030018dc5e040000130b000000006800,port:0"' in text
        assert r'profiles\1\button_select="button:4,engine:sdl,guid:030018dc5e040000130b000000006800,port:0"' in text


def test_apply_controller_profile_azahar_linux_injects_runtime_guid(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        qt_config = temp_root / "azahar" / "qt-config.ini"
        qt_config.parent.mkdir(parents=True, exist_ok=True)
        qt_config.write_text("profile=0\n", encoding="utf-8")

        monkeypatch.setattr("gamehub_cli.controller_apply.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controller_apply._azahar_target_config_paths", lambda: [qt_config])
        monkeypatch.setattr("gamehub_cli.controller_apply._is_azahar_flatpak_config_path", lambda path: True)
        monkeypatch.setattr(
            "gamehub_cli.controller_apply._probe_azahar_flatpak_guid",
            lambda port=0: "030018dc5e040000130b000000006800",
        )
        monkeypatch.setattr(
            "gamehub_cli.controller_apply._discover_linux_sdl_guid",
            lambda port=0: "040018dc5e040000130b000000006800",
        )

        apply_named_controller_profile(config, emulator_name="azahar", profile_name="xbox_1p")
        text = qt_config.read_text(encoding="utf-8")

        assert r'profiles\1\button_a="button:0,engine:sdl,guid:030018dc5e040000130b000000006800,port:0"' in text
        assert r"profiles\1\circle_pad=" in text
        assert "guid$0030018dc5e040000130b000000006800" in text
        zl_line = _line_for_key(text, "button_zl")
        zr_line = _line_for_key(text, "button_zr")
        assert zl_line is not None
        assert zr_line is not None
        assert "axis:4" in zl_line
        assert "axis:5" in zr_line
        assert "guid:030018dc5e040000130b000000006800" in zl_line
        assert "guid:030018dc5e040000130b000000006800" in zr_line


def test_apply_controller_profile_azahar_linux_flatpak_runtime_unavailable_keeps_port_only_when_no_existing_guid(
    monkeypatch,
) -> None:
    with _workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        qt_config = temp_root / "azahar" / "qt-config.ini"
        qt_config.parent.mkdir(parents=True, exist_ok=True)
        qt_config.write_text("profile=0\n", encoding="utf-8")

        monkeypatch.setattr("gamehub_cli.controller_apply.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controller_apply._azahar_target_config_paths", lambda: [qt_config])
        monkeypatch.setattr("gamehub_cli.controller_apply._is_azahar_flatpak_config_path", lambda path: True)
        monkeypatch.setattr("gamehub_cli.controller_apply._probe_azahar_flatpak_guid", lambda port=0: None)
        monkeypatch.setattr(
            "gamehub_cli.controller_apply._discover_linux_sdl_guid",
            lambda port=0: "040018dc5e040000130b000000006800",
        )

        apply_named_controller_profile(config, emulator_name="azahar", profile_name="xbox_1p")
        text = qt_config.read_text(encoding="utf-8")

        assert r'profiles\1\button_a="button:0,engine:sdl,port:0"' in text
        assert "guid:" not in text
        assert "guid$0" not in text


def test_apply_controller_profile_azahar_linux_non_flatpak_uses_host_guid_when_runtime_unavailable(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        qt_config = temp_root / "azahar" / "qt-config.ini"
        qt_config.parent.mkdir(parents=True, exist_ok=True)
        qt_config.write_text("profile=0\n", encoding="utf-8")

        monkeypatch.setattr("gamehub_cli.controller_apply.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controller_apply._azahar_target_config_paths", lambda: [qt_config])
        monkeypatch.setattr("gamehub_cli.controller_apply._is_azahar_flatpak_config_path", lambda path: False)
        monkeypatch.setattr("gamehub_cli.controller_apply._probe_azahar_flatpak_guid", lambda port=0: None)
        monkeypatch.setattr(
            "gamehub_cli.controller_apply._discover_linux_sdl_guid",
            lambda port=0: "040018dc5e040000130b000000006800",
        )

        apply_named_controller_profile(config, emulator_name="azahar", profile_name="xbox_1p")
        text = qt_config.read_text(encoding="utf-8")

        assert r'profiles\1\button_a="button:0,engine:sdl,guid:040018dc5e040000130b000000006800,port:0"' in text


def test_apply_controller_profile_azahar_linux_upgrades_existing_sdl_without_guid(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        qt_config = temp_root / "azahar" / "qt-config.ini"
        qt_config.parent.mkdir(parents=True, exist_ok=True)
        qt_config.write_text(
            "\n".join(
                [
                    "profile=0",
                    r'profiles\1\button_a="button:0,engine:sdl,guid:ABC123,port:0"',
                    r'profiles\1\button_b="button:1,engine:sdl,port:0"',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("gamehub_cli.controller_apply.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controller_apply._azahar_target_config_paths", lambda: [qt_config])
        monkeypatch.setattr("gamehub_cli.controller_apply._is_azahar_flatpak_config_path", lambda path: True)
        monkeypatch.setattr("gamehub_cli.controller_apply._probe_azahar_flatpak_guid", lambda port=0: None)
        monkeypatch.setattr("gamehub_cli.controller_apply._discover_linux_sdl_guid", lambda port=0: None)

        apply_named_controller_profile(config, emulator_name="azahar", profile_name="xbox_1p")
        text = qt_config.read_text(encoding="utf-8")

        assert r'profiles\1\button_a="button:0,engine:sdl,guid:ABC123,port:0"' in text
        assert r'profiles\1\button_b="button:1,engine:sdl,guid:ABC123,port:0"' in text


def test_apply_controller_profile_azahar_linux_dedupes_guid_tokens(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        qt_config = temp_root / "azahar" / "qt-config.ini"
        qt_config.parent.mkdir(parents=True, exist_ok=True)
        qt_config.write_text(
            "\n".join(
                [
                    "profile=0",
                    r'profiles\1\button_a="button:0,engine:sdl,guid:ABC123,guid:ABC123,port:0"',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("gamehub_cli.controller_apply.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controller_apply._azahar_target_config_paths", lambda: [qt_config])
        monkeypatch.setattr("gamehub_cli.controller_apply._is_azahar_flatpak_config_path", lambda path: True)
        monkeypatch.setattr("gamehub_cli.controller_apply._probe_azahar_flatpak_guid", lambda port=0: None)
        monkeypatch.setattr("gamehub_cli.controller_apply._discover_linux_sdl_guid", lambda port=0: None)

        apply_named_controller_profile(config, emulator_name="azahar", profile_name="xbox_1p")
        text = qt_config.read_text(encoding="utf-8")

        assert "guid:ABC123,guid:ABC123" not in text
        assert r'profiles\1\button_a="button:0,engine:sdl,guid:ABC123,port:0"' in text


def test_probe_azahar_flatpak_guid_uses_equals_command_flag(monkeypatch) -> None:
    import gamehub_cli.controller_apply as controller_apply_mod

    captured: dict[str, list[str]] = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="030018dc5e040000130b000000006800\n", stderr="")

    monkeypatch.setattr(controller_apply_mod.sys, "platform", "linux")
    monkeypatch.setattr(controller_apply_mod.shutil, "which", lambda name: "/usr/bin/flatpak")
    monkeypatch.setattr(controller_apply_mod.subprocess, "run", _fake_run)

    guid = controller_apply_mod._probe_azahar_flatpak_guid(port=0)

    assert guid == "030018dc5e040000130b000000006800"
    assert "--command=python3" in captured["cmd"]
    assert "--command" not in captured["cmd"]


@contextmanager
def _workspace_tempdir(prefix: str):
    temp_root = Path(".pytest_tmp_local") / f"{prefix}{uuid4().hex}"
    temp_root.mkdir(parents=True, exist_ok=False)
    try:
        yield temp_root
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def _line_for_key(text: str, key: str) -> str | None:
    prefix = f"profiles\\1\\{key}="
    for line in text.splitlines():
        if line.startswith(prefix):
            return line
    return None
