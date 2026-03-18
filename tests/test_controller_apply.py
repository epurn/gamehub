from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import gamehub_cli.controllers.profiles as controller_profiles
from gamehub_cli.common.config import ControllersConfig, GamehubConfig
from gamehub_cli.controllers import sdl_guid as controller_sdl_guid
from gamehub_cli.controllers.apply import apply_controller_profile, apply_named_controller_profile
from gamehub_cli.controllers.detection import XboxController
from gamehub_cli.controllers.profiles import seed_default_profiles


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


def test_apply_controller_profile_pcsx2_kbm_preserves_unmanaged_sections(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        base = _config(temp_root)
        ini_path = temp_root / "pcsx2" / "PCSX2.ini"
        config = replace(base, linux=replace(base.linux, pcsx2_ini_path=ini_path))
        monkeypatch.setattr("gamehub_cli.firmware.targets._SYS_PLATFORM", "linux")
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


def test_apply_controller_profile_pcsx2_xbox_modes(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        base = _config(temp_root)
        ini_path = temp_root / "pcsx2" / "PCSX2.ini"
        config = replace(base, linux=replace(base.linux, pcsx2_ini_path=ini_path))
        monkeypatch.setattr("gamehub_cli.firmware.targets._SYS_PLATFORM", "linux")
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


def test_apply_controller_profile_pcsx2_writes_confirm_shutdown_false(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        base = _config(temp_root)
        ini_path = temp_root / "pcsx2" / "PCSX2.ini"
        config = replace(base, linux=replace(base.linux, pcsx2_ini_path=ini_path))
        monkeypatch.setattr("gamehub_cli.firmware.targets._SYS_PLATFORM", "linux")
        seed_default_profiles(config)
        ini_path.parent.mkdir(parents=True, exist_ok=True)
        ini_path.write_text("[UI]\nConfirmShutdown = true\n", encoding="utf-8")

        apply_controller_profile(config, emulator_name="pcsx2", controller_count=0)
        text = ini_path.read_text(encoding="utf-8")

        assert "ConfirmShutdown = false" in text


def test_apply_controller_profile_accepts_emulator_family_alias(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        base = _config(temp_root)
        ini_path = temp_root / "pcsx2" / "PCSX2.ini"
        config = replace(base, linux=replace(base.linux, pcsx2_ini_path=ini_path))
        monkeypatch.setattr("gamehub_cli.firmware.targets._SYS_PLATFORM", "linux")
        seed_default_profiles(config)

        profile = apply_controller_profile(config, emulator_name="PCSX2-nightly", controller_count=1)
        text = ini_path.read_text(encoding="utf-8")

        assert profile == "xbox_1p"
        assert "Cross = SDL-0/A" in text


def test_apply_controller_profile_dolphin_xbox_writes_managed_sections(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "GCPadNew.ini").write_text("[User]\nFoo = Bar\n", encoding="utf-8")

        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.detect_xbox_controllers", lambda max_devices=2: [])
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root]
        )

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
        elif sys.platform == "darwin":
            assert "Device = SDL/0/Gamepad" in gcpad_text
            assert "Device = SDL/1/Gamepad" in gcpad_text
            assert "Device = SDL/0/Gamepad" in hotkeys_text
            assert "Device = SDL/1/Gamepad" in hotkeys_text
        else:
            assert "Device = XInput/0/Gamepad" in gcpad_text
            assert "Device = XInput/1/Gamepad" in gcpad_text
        if sys.platform == "darwin":
            assert "General/Stop = `Back` & `Start`" in hotkeys_text
            assert "General/Exit = `Back` & `Start`" in hotkeys_text
        else:
            assert (
                "General/Stop = ((`BACK` | `Back` | `SELECT` | `Select` | `Button 6`) & (`START` | `Start` | `Button 7`))"
            ) in hotkeys_text
            assert (
                "General/Exit = ((`BACK` | `Back` | `SELECT` | `Select` | `Button 6`) & (`START` | `Start` | `Button 7`))"
            ) in hotkeys_text


def test_apply_controller_profile_dolphin_xbox_1p_uses_kbm_bindings_for_p2_gc(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.detect_xbox_controllers", lambda max_devices=2: [])
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root]
        )

        apply_controller_profile(config, emulator_name="dolphin", controller_count=1)
        gcpad_text = (config_dir / "GCPadNew.ini").read_text(encoding="utf-8")

        assert "[GCPad1]" in gcpad_text
        assert "[GCPad2]" in gcpad_text
        assert "Buttons/A = SOUTH | `Button A`" in gcpad_text
        assert "Buttons/A = X" in gcpad_text


def test_apply_controller_profile_dolphin_xbox_1p_uses_kbm_bindings_for_p2_wii(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.detect_xbox_controllers", lambda max_devices=2: [])
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root]
        )

        apply_controller_profile(config, emulator_name="dolphin", controller_count=1)
        wiimote_text = (config_dir / "WiimoteNew.ini").read_text(encoding="utf-8")

        assert "[Wiimote1]" in wiimote_text
        assert "[Wiimote2]" in wiimote_text
        assert "Buttons/A = SOUTH | `Button A`" in wiimote_text
        assert "Buttons/A = `Click 0`" in wiimote_text


def test_apply_controller_profile_dolphin_linux_prefers_evdev_from_detected_xbox(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.is_steam_deck_linux", lambda: False)
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root]
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.detect_xbox_controllers",
            lambda max_devices=2: [XboxController(slot=0, name="Xbox Wireless Controller", subtype=None)],
        )

        apply_controller_profile(config, emulator_name="dolphin", controller_count=1)
        gcpad_text = (config_dir / "GCPadNew.ini").read_text(encoding="utf-8")
        hotkeys_text = (config_dir / "Hotkeys.ini").read_text(encoding="utf-8")

        assert "Device = evdev/0/Xbox Wireless Controller" in gcpad_text
        assert "Device = All Devices" in hotkeys_text


def test_apply_controller_profile_dolphin_linux_steam_deck_names_use_evdev_fallback(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.is_steam_deck_linux", lambda: True)
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root]
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.detect_xbox_controllers",
            lambda max_devices=2: [
                XboxController(slot=0, name="Steam Deck Controller", subtype=None),
                XboxController(slot=1, name="Steam Virtual Gamepad", subtype=None),
            ],
        )

        apply_controller_profile(config, emulator_name="dolphin", controller_count=1)
        gcpad_text = (config_dir / "GCPadNew.ini").read_text(encoding="utf-8")

        assert "Device = evdev/0/Microsoft X-Box 360 pad 0" in gcpad_text
        assert "Device = None" in gcpad_text


def test_apply_controller_profile_dolphin_linux_steam_deck_with_xbox_alias_uses_evdev_device(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.is_steam_deck_linux", lambda: True)
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root]
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.detect_xbox_controllers",
            lambda max_devices=2: [XboxController(slot=0, name="Microsoft X-Box 360 pad 0", subtype=None)],
        )

        apply_controller_profile(config, emulator_name="dolphin", controller_count=1)
        gcpad_text = (config_dir / "GCPadNew.ini").read_text(encoding="utf-8")

        assert "Device = evdev/0/Microsoft X-Box 360 pad 0" in gcpad_text


def test_apply_controller_profile_dolphin_linux_steam_deck_no_detection_uses_evdev_fallback(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.is_steam_deck_linux", lambda: True)
        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.detect_xbox_controllers", lambda max_devices=2: [])
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root]
        )

        apply_controller_profile(config, emulator_name="dolphin", controller_count=1)
        gcpad_text = (config_dir / "GCPadNew.ini").read_text(encoding="utf-8")

        assert "Device = evdev/0/Microsoft X-Box 360 pad 0" in gcpad_text
        assert "Device = None" in gcpad_text


def test_apply_controller_profile_dolphin_linux_steam_deck_bindings_are_ab_first(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        monkeypatch.setattr(controller_profiles.sys, "platform", "linux")
        monkeypatch.setattr(controller_profiles, "DEFAULT_PROFILE_TEXTS", controller_profiles._default_profile_texts())
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.is_steam_deck_linux", lambda: True)
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.detect_xbox_controllers",
            lambda max_devices=2: [XboxController(slot=0, name="Microsoft X-Box 360 pad 0", subtype=None)],
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root]
        )

        apply_controller_profile(config, emulator_name="dolphin", controller_count=1)
        gcpad_text = (config_dir / "GCPadNew.ini").read_text(encoding="utf-8")
        wiimote_text = (config_dir / "WiimoteNew.ini").read_text(encoding="utf-8")

        assert "Buttons/A = SOUTH | `Button A`" in gcpad_text
        assert "Buttons/B = EAST | `Button B`" in gcpad_text
        assert "Buttons/Z = `Shoulder R` | `Button 5`" in gcpad_text
        assert "Triggers/R = `Trigger R` | `Axis 5+`" in gcpad_text
        assert "Buttons/A = SOUTH | `Button A` | `Shoulder R` | `Button 5`" in wiimote_text
        assert "Buttons/B = EAST | `Button B` | `Trigger R` | `Axis 5+`" in wiimote_text


def test_apply_controller_profile_dolphin_linux_kbm_uses_virtual_pointer_hotkeys(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.sys.platform", "linux")
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root]
        )

        apply_controller_profile(config, emulator_name="dolphin", controller_count=0)
        gcpad_text = (config_dir / "GCPadNew.ini").read_text(encoding="utf-8")
        hotkeys_text = (config_dir / "Hotkeys.ini").read_text(encoding="utf-8")

        assert "Device = XInput2/0/Virtual core pointer" in gcpad_text
        assert "Device = None" in gcpad_text
        assert "Device = XInput2/0/Virtual core pointer" in hotkeys_text


def test_apply_controller_profile_azahar_kbm(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        qt_config = temp_root / "azahar" / "qt-config.ini"
        qt_config.parent.mkdir(parents=True, exist_ok=True)
        qt_config.write_text("custom_key=keep\n", encoding="utf-8")
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._azahar_target_config_paths", lambda: [qt_config])

        profile = apply_named_controller_profile(config, emulator_name="azahar", profile_name="kbm")
        text = qt_config.read_text(encoding="utf-8")

        assert profile == "kbm"
        assert "custom_key=keep" in text
        assert r'profiles\1\button_a="code:65,engine:keyboard"' in text


def test_apply_controller_profile_azahar_overwrite_creates_backup_and_logs(
    monkeypatch, workspace_tempdir, caplog
) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        qt_config = temp_root / "azahar" / "qt-config.ini"
        qt_config.parent.mkdir(parents=True, exist_ok=True)
        original_text = "custom_key=keep\nprofile=9\n"
        qt_config.write_text(original_text, encoding="utf-8")
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._azahar_target_config_paths", lambda: [qt_config])

        with caplog.at_level(logging.INFO):
            apply_named_controller_profile(config, emulator_name="azahar", profile_name="kbm")

        backups = sorted(qt_config.parent.glob("qt-config.ini.*.bak"))
        assert backups
        assert backups[-1].read_text(encoding="utf-8") == original_text
        updated_text = qt_config.read_text(encoding="utf-8")
        assert "custom_key=keep" in updated_text
        assert r'profiles\1\button_a="code:65,engine:keyboard"' in updated_text
        assert f"controller config backup created path={qt_config}" in caplog.text
        assert f"controller config saved path={qt_config}" in caplog.text


def test_apply_controller_profile_azahar_updates_all_known_target_paths(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        qt_a = temp_root / "azahar-a" / "qt-config.ini"
        qt_b = temp_root / "azahar-b" / "qt-config.ini"
        qt_a.parent.mkdir(parents=True, exist_ok=True)
        qt_b.parent.mkdir(parents=True, exist_ok=True)
        qt_a.write_text("custom_key=keep_a\n", encoding="utf-8")
        qt_b.write_text("custom_key=keep_b\n", encoding="utf-8")
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._azahar_target_config_paths", lambda: [qt_a, qt_b])

        apply_named_controller_profile(config, emulator_name="azahar", profile_name="kbm")

        assert "custom_key=keep_a" in qt_a.read_text(encoding="utf-8")
        assert "custom_key=keep_b" in qt_b.read_text(encoding="utf-8")
        assert r'profiles\1\button_a="code:65,engine:keyboard"' in qt_a.read_text(encoding="utf-8")
        assert r'profiles\1\button_a="code:65,engine:keyboard"' in qt_b.read_text(encoding="utf-8")


def test_apply_controller_profile_azahar_linux_preserves_existing_sdl_bindings_when_discovery_unavailable(
    monkeypatch,
    workspace_tempdir,
) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
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
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._azahar_target_config_paths", lambda: [qt_config])
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._is_azahar_flatpak_config_path", lambda path: True)
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._probe_azahar_flatpak_guid", lambda port=1: None)
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_azahar._discover_host_sdl_guid",
            lambda port=1: "040018dc5e040000130b000000006800",
        )

        apply_named_controller_profile(config, emulator_name="azahar", profile_name="xbox_1p")
        text = qt_config.read_text(encoding="utf-8")

        assert r'profiles\1\button_a="button:0,engine:sdl,guid:ABC123,port:1"' in text
        assert r'profiles\1\button_select="button:4,engine:sdl,guid:ABC123,port:1"' in text
        assert r'profiles\1\button_start="button:6,engine:sdl,guid:ABC123,port:1"' in text


def test_apply_controller_profile_azahar_linux_prefers_runtime_when_existing_matches_host(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
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
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._azahar_target_config_paths", lambda: [qt_config])
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._is_azahar_flatpak_config_path", lambda path: True)
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_azahar._probe_azahar_flatpak_guid",
            lambda port=0: "030018dc5e040000130b000000006800",
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_azahar._discover_host_sdl_guid",
            lambda port=0: "11111111111111111111111111111111",
        )

        apply_named_controller_profile(config, emulator_name="azahar", profile_name="xbox_1p")
        text = qt_config.read_text(encoding="utf-8")

        assert r'profiles\1\button_a="button:0,engine:sdl,guid:030018dc5e040000130b000000006800,port:0"' in text
        assert r'profiles\1\button_select="button:4,engine:sdl,guid:030018dc5e040000130b000000006800,port:0"' in text


def test_apply_controller_profile_azahar_linux_injects_runtime_guid(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        qt_config = temp_root / "azahar" / "qt-config.ini"
        qt_config.parent.mkdir(parents=True, exist_ok=True)
        qt_config.write_text("profile=0\n", encoding="utf-8")

        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._azahar_target_config_paths", lambda: [qt_config])
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._is_azahar_flatpak_config_path", lambda path: True)
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_azahar._probe_azahar_flatpak_guid",
            lambda port=0: "030018dc5e040000130b000000006800",
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_azahar._discover_host_sdl_guid",
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
    workspace_tempdir,
) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        qt_config = temp_root / "azahar" / "qt-config.ini"
        qt_config.parent.mkdir(parents=True, exist_ok=True)
        qt_config.write_text("profile=0\n", encoding="utf-8")

        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._azahar_target_config_paths", lambda: [qt_config])
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._is_azahar_flatpak_config_path", lambda path: True)
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._probe_azahar_flatpak_guid", lambda port=0: None)
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_azahar._discover_host_sdl_guid",
            lambda port=0: "040018dc5e040000130b000000006800",
        )

        apply_named_controller_profile(config, emulator_name="azahar", profile_name="xbox_1p")
        text = qt_config.read_text(encoding="utf-8")

        assert r'profiles\1\button_a="button:0,engine:sdl,port:0"' in text
        assert "guid:" not in text
        assert "guid$0" not in text


def test_apply_controller_profile_azahar_linux_non_flatpak_uses_host_guid_when_runtime_unavailable(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        qt_config = temp_root / "azahar" / "qt-config.ini"
        qt_config.parent.mkdir(parents=True, exist_ok=True)
        qt_config.write_text("profile=0\n", encoding="utf-8")

        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._azahar_target_config_paths", lambda: [qt_config])
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._is_azahar_flatpak_config_path", lambda path: False)
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._probe_azahar_flatpak_guid", lambda port=0: None)
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_azahar._discover_host_sdl_guid",
            lambda port=0: "040018dc5e040000130b000000006800",
        )

        apply_named_controller_profile(config, emulator_name="azahar", profile_name="xbox_1p")
        text = qt_config.read_text(encoding="utf-8")

        assert r'profiles\1\button_a="button:0,engine:sdl,guid:040018dc5e040000130b000000006800,port:0"' in text


def test_apply_dolphin_profile_macos_uses_sdl_device_names(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.sys.platform", "darwin")
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.macos_dolphin_root_candidates", lambda: [dolphin_root]
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root]
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.detect_xbox_controllers",
            lambda max_devices=2: [
                XboxController(
                    slot=0,
                    name="Xbox Wireless Controller",
                    subtype=None,
                    guid="030000005e040000200b000011050000",
                    vendor_id=0x045E,
                    product_id=0x0B13,
                ),
                XboxController(
                    slot=1,
                    name="Xbox Elite Wireless Controller",
                    subtype=None,
                    guid="030000005e040000050b000003090000",
                    vendor_id=0x045E,
                    product_id=0x0B05,
                ),
            ],
        )
        apply_named_controller_profile(config, emulator_name="dolphin", profile_name="xbox_2p")
        gcpad_text = (config_dir / "GCPadNew.ini").read_text(encoding="utf-8")
        wiimote_text = (config_dir / "WiimoteNew.ini").read_text(encoding="utf-8")
        hotkeys_text = (config_dir / "Hotkeys.ini").read_text(encoding="utf-8")

        assert "Device = SDL/0/Xbox Wireless Controller" in gcpad_text
        assert "Device = SDL/1/Xbox Elite Wireless Controller" in gcpad_text
        assert "Buttons/A = `Button S`" in gcpad_text
        assert "Buttons/B = `Button E`" in gcpad_text
        assert "Buttons/X = `Button W`" in gcpad_text
        assert "Buttons/Y = `Button N`" in gcpad_text
        assert "Triggers/L-Analog = `Trigger L`" in gcpad_text
        assert "Triggers/R-Analog = `Trigger R`" in gcpad_text
        assert "IR/Up = `Right Y+`" in wiimote_text
        assert "IR/Down = `Right Y-`" in wiimote_text
        assert "Device = SDL/0/Xbox Wireless Controller" in hotkeys_text
        assert "Device = SDL/1/Xbox Elite Wireless Controller" in hotkeys_text
        assert "General/Exit = `Back` & `Start`" in hotkeys_text
        assert "Keys/Exit = `Back` & `Start`" in hotkeys_text


def test_apply_dolphin_profile_macos_kbm_uses_quartz_device(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.sys.platform", "darwin")
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.macos_dolphin_root_candidates", lambda: [dolphin_root]
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root]
        )

        apply_named_controller_profile(config, emulator_name="dolphin", profile_name="kbm")
        gcpad_text = (config_dir / "GCPadNew.ini").read_text(encoding="utf-8")
        wiimote_text = (config_dir / "WiimoteNew.ini").read_text(encoding="utf-8")
        hotkeys_text = (config_dir / "Hotkeys.ini").read_text(encoding="utf-8")

        assert "Device = Quartz/0/Keyboard & Mouse" in gcpad_text
        assert "Device = Quartz/0/Keyboard & Mouse" in wiimote_text
        assert "Device = Quartz/0/Keyboard & Mouse" in hotkeys_text
        assert "Buttons/Start = `Return`" in gcpad_text
        assert "Main Stick/Up = `Up Arrow`" in gcpad_text
        assert "C-Stick/Modifier = `Left Control`" in gcpad_text
        assert "Buttons/Home = Return" in wiimote_text
        assert "Nunchuk/Buttons/C = `Left Control`" in wiimote_text
        assert "General/Stop = Escape" in hotkeys_text
        assert "General/Exit = Escape" in hotkeys_text
        assert "Keys/Stop = Escape" in hotkeys_text
        assert "General/Toggle Fullscreen = @(Alt+Return)" in hotkeys_text


def test_apply_dolphin_profile_macos_preserves_specific_sdl_device_when_probe_falls_back(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "GCPadNew.ini").write_text(
            "[GCPad1]\nDevice = SDL/3/Xbox Wireless Controller\n",
            encoding="utf-8",
        )

        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.sys.platform", "darwin")
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.macos_dolphin_root_candidates", lambda: [dolphin_root]
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root]
        )
        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.detect_xbox_controllers", lambda max_devices=2: [])

        apply_named_controller_profile(config, emulator_name="dolphin", profile_name="xbox_1p")
        gcpad_text = (config_dir / "GCPadNew.ini").read_text(encoding="utf-8")

        assert "Device = SDL/3/Xbox Wireless Controller" in gcpad_text


def test_apply_dolphin_profile_macos_guidless_detection_rebinds_stale_specific_device(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "GCPadNew.ini").write_text(
            "[GCPad1]\nDevice = SDL/3/Xbox Wireless Controller\n",
            encoding="utf-8",
        )

        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.sys.platform", "darwin")
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.macos_dolphin_root_candidates", lambda: [dolphin_root]
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root]
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.detect_xbox_controllers",
            lambda max_devices=2: [
                XboxController(
                    slot=0,
                    name="Xbox Wireless Controller",
                    subtype=None,
                    guid=None,
                    vendor_id=0x045E,
                    product_id=0x0B13,
                )
            ],
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin._lookup_macos_embedded_sdl_mapping_for_identity",
            lambda *, name, vendor_id=None, product_id=None: None,
        )

        apply_named_controller_profile(config, emulator_name="dolphin", profile_name="xbox_1p")
        gcpad_text = (config_dir / "GCPadNew.ini").read_text(encoding="utf-8")

        assert "Device = SDL/3/Xbox Wireless Controller" not in gcpad_text
        assert "Device = SDL/0/Xbox Wireless Controller" in gcpad_text


def test_apply_dolphin_profile_macos_guidless_detection_uses_detected_sdl_name_and_mapping_hotkeys(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.sys.platform", "darwin")
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.macos_dolphin_root_candidates", lambda: [dolphin_root]
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root]
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.detect_xbox_controllers",
            lambda max_devices=2: [
                XboxController(
                    slot=0,
                    name="Xbox Wireless Controller",
                    subtype=None,
                    guid=None,
                    vendor_id=0x045E,
                    product_id=0x0B13,
                )
            ],
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin._lookup_macos_embedded_sdl_mapping_for_identity",
            lambda *, name, vendor_id=None, product_id=None: None,
        )
        apply_named_controller_profile(config, emulator_name="dolphin", profile_name="xbox_1p")
        gcpad_text = (config_dir / "GCPadNew.ini").read_text(encoding="utf-8")
        wiimote_text = (config_dir / "WiimoteNew.ini").read_text(encoding="utf-8")
        hotkeys_text = (config_dir / "Hotkeys.ini").read_text(encoding="utf-8")

        assert "Device = SDL/0/Xbox Wireless Controller" in gcpad_text
        assert "Device = SDL/0/Xbox Wireless Controller" in wiimote_text
        assert "General/Exit = `Back` & `Start`" in hotkeys_text
        assert "Keys/Exit = `Back` & `Start`" in hotkeys_text


def test_apply_dolphin_profile_macos_guidless_detection_prefers_embedded_mapping_name(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.sys.platform", "darwin")
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.macos_dolphin_root_candidates", lambda: [dolphin_root]
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root]
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.detect_xbox_controllers",
            lambda max_devices=2: [
                XboxController(
                    slot=0,
                    name="Xbox Wireless Controller",
                    subtype=None,
                    guid=None,
                    vendor_id=0x045E,
                    product_id=0x0B13,
                )
            ],
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin._lookup_macos_embedded_sdl_mapping_for_identity",
            lambda *, name, vendor_id=None, product_id=None: controller_sdl_guid._SDLControllerMapping(
                guid="030000005e040000130b0000ff870000",
                name="Xbox Series X Controller",
                vendor_id=0x045E,
                product_id=0x0B13,
                version=0x87FF,
                fields={"back": "b10", "start": "b11"},
            ),
        )

        apply_named_controller_profile(config, emulator_name="dolphin", profile_name="xbox_1p")
        gcpad_text = (config_dir / "GCPadNew.ini").read_text(encoding="utf-8")

        assert "Device = SDL/0/Xbox Series X Controller" in gcpad_text


def test_apply_dolphin_profile_macos_updates_all_existing_config_roots(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        xdg_root = temp_root / "dolphin-xdg"
        app_support_root = temp_root / "dolphin-app-support"
        (xdg_root / "Config").mkdir(parents=True, exist_ok=True)
        (app_support_root / "Config").mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.sys.platform", "darwin")
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.macos_dolphin_root_candidates",
            lambda: [app_support_root, xdg_root],
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_runtime_user_dir", lambda config=None: xdg_root
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_config_dirs", lambda config=None: [xdg_root]
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.detect_xbox_controllers",
            lambda max_devices=2: [
                XboxController(
                    slot=0,
                    name="Xbox Series X Controller",
                    subtype=None,
                    guid="030000005e040000220b000011050000",
                    vendor_id=0x045E,
                    product_id=0x0B22,
                )
            ],
        )
        apply_named_controller_profile(config, emulator_name="dolphin", profile_name="xbox_1p")

        for root in (xdg_root, app_support_root):
            gcpad_text = (root / "Config" / "GCPadNew.ini").read_text(encoding="utf-8")
            assert "Device = SDL/0/Xbox Series X Controller" in gcpad_text
            assert "Buttons/A = `Button S`" in gcpad_text
            assert "Triggers/L-Analog = `Trigger L`" in gcpad_text


def test_apply_azahar_profile_macos_injects_sdl_identity(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        qt_config = temp_root / "azahar" / "qt-config.ini"
        qt_config.parent.mkdir(parents=True, exist_ok=True)
        qt_config.write_text("profile=0\n", encoding="utf-8")

        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar.sys.platform", "darwin")
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._azahar_target_config_paths", lambda: [qt_config])
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._probe_azahar_flatpak_guid", lambda port=0: None)
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_azahar._lookup_macos_embedded_sdl_mapping_for_port",
            lambda *, port: None,
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_azahar._discover_host_sdl_guid",
            lambda port=0: "040018dc5e040000130b000000006800",
        )

        apply_named_controller_profile(config, emulator_name="azahar", profile_name="xbox_1p")
        text = qt_config.read_text(encoding="utf-8")

        assert r'profiles\1\button_a="button:0,engine:sdl,guid:040018dc5e040000130b000000006800,port:0"' in text


def test_apply_azahar_profile_macos_uses_embedded_sdl_mapping(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        qt_config = temp_root / "azahar" / "qt-config.ini"
        qt_config.parent.mkdir(parents=True, exist_ok=True)
        qt_config.write_text("profile=0\n", encoding="utf-8")

        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar.sys.platform", "darwin")
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._azahar_target_config_paths", lambda: [qt_config])
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._probe_azahar_flatpak_guid", lambda port=0: None)
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_azahar._discover_host_sdl_guid",
            lambda port=0: "050000005e040000130b0000ff870001",
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_azahar._lookup_macos_embedded_sdl_mapping_for_port",
            lambda *, port: controller_sdl_guid._SDLControllerMapping(
                guid="050000005e040000130b0000ff870001",
                name="Xbox Series X Controller",
                vendor_id=0x045E,
                product_id=0x0B13,
                version=0x87FF,
                fields={
                    "a": "b0",
                    "b": "b1",
                    "back": "b8",
                    "dpdown": "h0.4",
                    "dpleft": "h0.8",
                    "dpright": "h0.2",
                    "dpup": "h0.1",
                    "guide": "b9",
                    "leftshoulder": "b4",
                    "lefttrigger": "a2",
                    "leftx": "a0",
                    "lefty": "a1",
                    "misc1": "b11",
                    "rightshoulder": "b5",
                    "righttrigger": "a5",
                    "rightx": "a3",
                    "righty": "a4",
                    "start": "b10",
                    "x": "b2",
                    "y": "b3",
                },
            ),
        )

        apply_named_controller_profile(config, emulator_name="azahar", profile_name="xbox_1p")
        text = qt_config.read_text(encoding="utf-8")

        assert r'profiles\1\button_a="button:1,engine:sdl,guid:050000005e040000130b0000ff870001,port:0"' in text
        assert r'profiles\1\button_b="button:0,engine:sdl,guid:050000005e040000130b0000ff870001,port:0"' in text
        assert r'profiles\1\button_x="button:3,engine:sdl,guid:050000005e040000130b0000ff870001,port:0"' in text
        assert r'profiles\1\button_y="button:2,engine:sdl,guid:050000005e040000130b0000ff870001,port:0"' in text
        assert r'profiles\1\button_select="button:8,engine:sdl,guid:050000005e040000130b0000ff870001,port:0"' in text
        assert r'profiles\1\button_start="button:10,engine:sdl,guid:050000005e040000130b0000ff870001,port:0"' in text
        assert r'profiles\1\button_l="button:4,engine:sdl,guid:050000005e040000130b0000ff870001,port:0"' in text
        assert r'profiles\1\button_r="button:5,engine:sdl,guid:050000005e040000130b0000ff870001,port:0"' in text
        assert (
            r'profiles\1\button_zl="axis:2,direction:+,engine:sdl,guid:050000005e040000130b0000ff870001,port:0,threshold:0.5"'
            in text
        )
        assert (
            r'profiles\1\button_zr="axis:5,direction:+,engine:sdl,guid:050000005e040000130b0000ff870001,port:0,threshold:0.5"'
            in text
        )
        assert r'profiles\1\button_home="button:9,engine:sdl,guid:050000005e040000130b0000ff870001,port:0"' in text
        assert (
            r'profiles\1\button_up="hat:0,direction:up,engine:sdl,guid:050000005e040000130b0000ff870001,port:0"' in text
        )
        assert (
            r'profiles\1\button_down="hat:0,direction:down,engine:sdl,guid:050000005e040000130b0000ff870001,port:0"'
            in text
        )
        assert (
            r'profiles\1\button_left="hat:0,direction:left,engine:sdl,guid:050000005e040000130b0000ff870001,port:0"'
            in text
        )
        assert (
            r'profiles\1\button_right="hat:0,direction:right,engine:sdl,guid:050000005e040000130b0000ff870001,port:0"'
            in text
        )
        assert (
            r'profiles\1\circle_pad="down:axis$01$1direction$0+$1engine$0sdl$1guid$0050000005e040000130b0000ff870001$1port$00$1threshold$00.5,engine:analog_from_button,left:axis$00$1direction$0-$1engine$0sdl$1guid$0050000005e040000130b0000ff870001$1port$00$1threshold$00-0.5,modifier:code$068$1engine$0keyboard,modifier_scale:0.500000,right:axis$00$1direction$0+$1engine$0sdl$1guid$0050000005e040000130b0000ff870001$1port$00$1threshold$00.5,up:axis$01$1direction$0-$1engine$0sdl$1guid$0050000005e040000130b0000ff870001$1port$00$1threshold$00-0.5"'
            in text
        )
        assert (
            r'profiles\1\c_stick="down:axis$04$1direction$0+$1engine$0sdl$1guid$0050000005e040000130b0000ff870001$1port$00$1threshold$00.5,engine:analog_from_button,left:axis$03$1direction$0-$1engine$0sdl$1guid$0050000005e040000130b0000ff870001$1port$00$1threshold$00-0.5,modifier:code$068$1engine$0keyboard,modifier_scale:0.500000,right:axis$03$1direction$0+$1engine$0sdl$1guid$0050000005e040000130b0000ff870001$1port$00$1threshold$00.5,up:axis$04$1direction$0-$1engine$0sdl$1guid$0050000005e040000130b0000ff870001$1port$00$1threshold$00-0.5"'
            in text
        )


def test_apply_azahar_profile_macos_preserves_existing_runtime_guid_and_default_flags(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        qt_config = temp_root / "azahar" / "qt-config.ini"
        qt_config.parent.mkdir(parents=True, exist_ok=True)
        qt_config.write_text(
            "\n".join(
                [
                    "[General]",
                    "profile=0",
                    "",
                    "[Controls]",
                    "profile=0",
                    r"profile\default=true",
                    r'profiles\1\button_a="code:65,engine:keyboard"',
                    r"profiles\1\button_a\default=true",
                    r'profiles\1\button_select="code:78,engine:keyboard"',
                    r"profiles\1\button_select\default=true",
                    r'profiles\1\button_start="code:77,engine:keyboard"',
                    r"profiles\1\button_start\default=true",
                    r'profiles\2\button_a="button:0,engine:sdl,guid:0300c6515e040000130b000023056800,port:0"',
                    r"profiles\2\button_a\default=false",
                    r'profiles\2\button_select="button:4,engine:sdl,guid:0300c6515e040000130b000023056800,port:0"',
                    r"profiles\2\button_select\default=false",
                    r'profiles\2\button_start="button:6,engine:sdl,guid:0300c6515e040000130b000023056800,port:0"',
                    r"profiles\2\button_start\default=false",
                    r"profiles\size=2",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar.sys.platform", "darwin")
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._azahar_target_config_paths", lambda: [qt_config])
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._probe_azahar_flatpak_guid", lambda port=0: None)
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._discover_host_sdl_guid", lambda port=0: None)
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_azahar._lookup_macos_embedded_sdl_mapping_for_port",
            lambda *, port: controller_sdl_guid._SDLControllerMapping(
                guid="050000005e040000130b0000ff870001",
                name="Xbox Series X Controller",
                vendor_id=0x045E,
                product_id=0x0B13,
                version=0x87FF,
                fields={
                    "a": "b0",
                    "b": "b1",
                    "back": "b8",
                    "guide": "b9",
                    "start": "b10",
                    "leftshoulder": "b4",
                    "rightshoulder": "b5",
                    "lefttrigger": "a2",
                    "righttrigger": "a5",
                    "dpup": "h0.1",
                    "dpdown": "h0.4",
                    "dpleft": "h0.8",
                    "dpright": "h0.2",
                    "leftx": "a0",
                    "lefty": "a1",
                    "rightx": "a3",
                    "righty": "a4",
                    "x": "b2",
                    "y": "b3",
                },
            ),
        )

        apply_named_controller_profile(config, emulator_name="azahar", profile_name="xbox_1p")
        text = qt_config.read_text(encoding="utf-8")

        assert r'profiles\1\button_a="button:1,engine:sdl,guid:0300c6515e040000130b000023056800,port:0"' in text
        assert r'profiles\1\button_select="button:8,engine:sdl,guid:0300c6515e040000130b000023056800,port:0"' in text
        assert r'profiles\1\button_start="button:10,engine:sdl,guid:0300c6515e040000130b000023056800,port:0"' in text
        assert r"profiles\1\button_a\default=false" in text
        assert r"profiles\1\button_select\default=false" in text
        assert r"profiles\1\button_start\default=false" in text


def test_apply_controller_profile_azahar_linux_upgrades_existing_sdl_without_guid(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
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
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._azahar_target_config_paths", lambda: [qt_config])
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._is_azahar_flatpak_config_path", lambda path: True)
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._probe_azahar_flatpak_guid", lambda port=0: None)
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._discover_host_sdl_guid", lambda port=0: None)

        apply_named_controller_profile(config, emulator_name="azahar", profile_name="xbox_1p")
        text = qt_config.read_text(encoding="utf-8")

        assert r'profiles\1\button_a="button:0,engine:sdl,guid:ABC123,port:0"' in text
        assert r'profiles\1\button_b="button:1,engine:sdl,guid:ABC123,port:0"' in text


def test_apply_controller_profile_azahar_linux_dedupes_guid_tokens(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
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
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._azahar_target_config_paths", lambda: [qt_config])
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._is_azahar_flatpak_config_path", lambda path: True)
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._probe_azahar_flatpak_guid", lambda port=0: None)
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._discover_host_sdl_guid", lambda port=0: None)

        apply_named_controller_profile(config, emulator_name="azahar", profile_name="xbox_1p")
        text = qt_config.read_text(encoding="utf-8")

        assert "guid:ABC123,guid:ABC123" not in text
        assert r'profiles\1\button_a="button:0,engine:sdl,guid:ABC123,port:0"' in text


def test_probe_azahar_flatpak_guid_uses_equals_command_flag(monkeypatch) -> None:
    import gamehub_cli.controllers.sdl_guid as controller_apply_mod

    captured: dict[str, list[str]] = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="030018dc5e040000130b000000006800\n", stderr=""
        )

    monkeypatch.setattr(controller_apply_mod.sys, "platform", "linux")
    monkeypatch.setattr(controller_apply_mod.shutil, "which", lambda name: "/usr/bin/flatpak")
    monkeypatch.setattr(controller_apply_mod.subprocess, "run", _fake_run)

    guid = controller_apply_mod._probe_azahar_flatpak_guid(port=0)

    assert guid == "030018dc5e040000130b000000006800"
    assert "--command=python3" in captured["cmd"]
    assert "--command" not in captured["cmd"]


def test_apply_controller_profile_dolphin_linux_preserves_existing_device_mapping(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "WiimoteNew.ini").write_text(
            "[Wiimote1]\nDevice = SDL/0/Steam Virtual Gamepad\n", encoding="utf-8"
        )

        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.sys.platform", "linux")
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root]
        )

        apply_controller_profile(config, emulator_name="dolphin", controller_count=1)

        wiimote_text = (config_dir / "WiimoteNew.ini").read_text(encoding="utf-8")
        assert "Device = SDL/0/Steam Virtual Gamepad" in wiimote_text


def test_apply_controller_profile_dolphin_linux_rebinds_generic_sdl_gamepad_for_controller_mode(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "WiimoteNew.ini").write_text("[Wiimote1]\nDevice = SDL/0/Gamepad\n", encoding="utf-8")

        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.sys.platform", "linux")
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.detect_xbox_controllers",
            lambda max_devices=2: [XboxController(slot=0, name="Steam Deck", subtype=None)],
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root]
        )

        apply_controller_profile(config, emulator_name="dolphin", controller_count=1)

        wiimote_text = (config_dir / "WiimoteNew.ini").read_text(encoding="utf-8")
        assert "Device = SDL/0/Gamepad" not in wiimote_text
        assert "Device = evdev/0/Steam Deck" in wiimote_text


def test_apply_controller_profile_dolphin_linux_deck_rebinds_sdl_xbox_alias_to_evdev_device(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "WiimoteNew.ini").write_text(
            "[Wiimote1]\nDevice = SDL/0/Microsoft X-Box 360 pad 0\n",
            encoding="utf-8",
        )

        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.is_steam_deck_linux", lambda: True)
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.detect_xbox_controllers",
            lambda max_devices=2: [XboxController(slot=0, name="Microsoft X-Box 360 pad 0", subtype=None)],
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root]
        )

        apply_controller_profile(config, emulator_name="dolphin", controller_count=1)
        wiimote_text = (config_dir / "WiimoteNew.ini").read_text(encoding="utf-8")

        assert "Device = SDL/0/Microsoft X-Box 360 pad 0" not in wiimote_text
        assert "Device = evdev/0/Microsoft X-Box 360 pad 0" in wiimote_text


def test_apply_controller_profile_dolphin_linux_rebinds_virtual_pointer_for_controller_mode(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "WiimoteNew.ini").write_text(
            "[Wiimote1]\nDevice = XInput2/0/Virtual core pointer\n",
            encoding="utf-8",
        )

        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.detect_xbox_controllers", lambda max_devices=2: [])
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root]
        )

        apply_controller_profile(config, emulator_name="dolphin", controller_count=1)

        wiimote_text = (config_dir / "WiimoteNew.ini").read_text(encoding="utf-8")
        assert "Device = XInput2/0/Virtual core pointer" not in wiimote_text
        assert "Device = SDL/0/Gamepad" in wiimote_text


def test_apply_controller_profile_dolphin_emits_device_mode_only_in_verbose_flow(
    monkeypatch, workspace_tempdir, capsys
) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.detect_xbox_controllers", lambda max_devices=2: [])
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root]
        )

        apply_controller_profile(config, emulator_name="dolphin", controller_count=1)
        assert "device_identity_mode=" not in capsys.readouterr().out

        audit_lines: list[str] = []
        apply_named_controller_profile(
            config,
            emulator_name="dolphin",
            profile_name="xbox_1p",
            verbose=True,
            writer=audit_lines.append,
        )
        assert any("controller-autoconfig\tdevice_identity_mode=" in line for line in audit_lines)
        assert any("controller-autoconfig\tdolphin_device_selected=" in line for line in audit_lines)


def test_apply_controller_profile_azahar_preserves_pointer_keys_when_quit_shortcut_is_escape(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        qt_config = temp_root / "azahar" / "qt-config.ini"
        qt_config.parent.mkdir(parents=True, exist_ok=True)
        qt_config.write_text(
            "\n".join(
                [
                    "profile=0",
                    r"Shortcuts\Main%20Window\Exit%20Citra\KeySeq=Ctrl+Q",
                    r"Shortcuts\Main%20Window\Exit%20Citra\KeySeq\default=true",
                    r'profiles\1\button_a="button:0,engine:sdl,guid:ABC123,port:0"',
                    r'profiles\1\touch_from_button_a="button:8,engine:keyboard"',
                    r'profiles\1\touch_device="engine:mouse,index:0"',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._azahar_target_config_paths", lambda: [qt_config])
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._is_azahar_flatpak_config_path", lambda path: False)
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_azahar._discover_host_sdl_guid",
            lambda port=0: "040018dc5e040000130b000000006800",
        )

        apply_named_controller_profile(config, emulator_name="azahar", profile_name="xbox_1p")
        text = qt_config.read_text(encoding="utf-8")

        assert r'profiles\1\button_a="button:0,engine:sdl,guid:040018dc5e040000130b000000006800,port:0"' in text
        assert r"Shortcuts\Main%20Window\Exit%20Citra\KeySeq=Esc" in text
        assert r"Shortcuts\Main%20Window\Exit%20Citra\KeySeq\default=false" in text
        assert r'profiles\1\touch_from_button_a="button:8,engine:keyboard"' in text
        assert r'profiles\1\touch_device="engine:mouse,index:0"' in text


def test_apply_controller_profile_azahar_rebinds_managed_buttons_from_keyboard_to_sdl(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        qt_config = temp_root / "azahar" / "qt-config.ini"
        qt_config.parent.mkdir(parents=True, exist_ok=True)
        qt_config.write_text(
            "\n".join(
                [
                    "profile=0",
                    r'profiles\1\button_a="code:65,engine:keyboard"',
                    r'profiles\1\button_select="code:16777219,engine:keyboard"',
                    r'profiles\1\touch_device="engine:mouse,index:0"',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._azahar_target_config_paths", lambda: [qt_config])
        monkeypatch.setattr("gamehub_cli.controllers.apply_azahar._is_azahar_flatpak_config_path", lambda path: False)
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_azahar._discover_host_sdl_guid",
            lambda port=0: "040018dc5e040000130b000000006800",
        )

        apply_named_controller_profile(config, emulator_name="azahar", profile_name="xbox_1p")
        text = qt_config.read_text(encoding="utf-8")

        assert r'profiles\1\button_a="button:0,engine:sdl,guid:040018dc5e040000130b000000006800,port:0"' in text
        assert r'profiles\1\button_select="button:4,engine:sdl,guid:040018dc5e040000130b000000006800,port:0"' in text
        assert r'profiles\1\touch_device="engine:mouse,index:0"' in text


def test_apply_controller_profile_dolphin_linux_deck_backfills_mouse_pointer_for_wii(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        monkeypatch.setattr(controller_profiles.sys, "platform", "linux")
        monkeypatch.setattr(controller_profiles, "DEFAULT_PROFILE_TEXTS", controller_profiles._default_profile_texts())
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.is_steam_deck_linux", lambda: True)
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root]
        )

        apply_controller_profile(config, emulator_name="dolphin", controller_count=1)
        wiimote_text = (config_dir / "WiimoteNew.ini").read_text(encoding="utf-8")

        assert "IR/Up = `XInput2/0/Virtual core pointer:Cursor Y-`" in wiimote_text
        assert "IR/Down = `XInput2/0/Virtual core pointer:Cursor Y+`" in wiimote_text
        assert "IR/Left = `XInput2/0/Virtual core pointer:Cursor X-`" in wiimote_text
        assert "IR/Right = `XInput2/0/Virtual core pointer:Cursor X+`" in wiimote_text
        assert "Buttons/B = EAST | `Button B` | `Trigger R` | `Axis 5+`" in wiimote_text


def test_apply_controller_profile_dolphin_linux_deck_seeds_mouse_pointer_mapping(
    monkeypatch, workspace_tempdir
) -> None:
    with workspace_tempdir("gamehub-controller-apply-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        dolphin_root = temp_root / "dolphin-user"
        config_dir = dolphin_root / "Config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "WiimoteNew.ini").write_text(
            "\n".join(
                [
                    "[Wiimote1]",
                    "Device = SteamDeck/0/Steam Deck",
                    "Buttons/B = EAST | `Button B`",
                    "IR/Up = `Mouse:Cursor Y-`",
                    "IR/Down = `Mouse:Cursor Y+`",
                    "IR/Left = `Mouse:Cursor X-`",
                    "IR/Right = `Mouse:Cursor X+`",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.controllers.apply_dolphin.is_steam_deck_linux", lambda: True)
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.detect_xbox_controllers",
            lambda max_devices=2: [XboxController(slot=0, name="Steam Deck", subtype=None)],
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_runtime_user_dir", lambda config=None: dolphin_root
        )
        monkeypatch.setattr(
            "gamehub_cli.controllers.apply_dolphin.resolve_dolphin_config_dirs", lambda config=None: [dolphin_root]
        )

        apply_controller_profile(config, emulator_name="dolphin", controller_count=1)
        wiimote_text = (config_dir / "WiimoteNew.ini").read_text(encoding="utf-8")

        assert "IR/Up = `XInput2/0/Virtual core pointer:Cursor Y-`" in wiimote_text
        assert "IR/Down = `XInput2/0/Virtual core pointer:Cursor Y+`" in wiimote_text
        assert "IR/Left = `XInput2/0/Virtual core pointer:Cursor X-`" in wiimote_text
        assert "IR/Right = `XInput2/0/Virtual core pointer:Cursor X+`" in wiimote_text


def _line_for_key(text: str, key: str) -> str | None:
    prefix = f"profiles\\1\\{key}="
    for line in text.splitlines():
        if line.startswith(prefix):
            return line
    return None
