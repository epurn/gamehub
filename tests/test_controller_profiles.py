from __future__ import annotations

import sys
from pathlib import Path

import gamehub_cli.controllers.profiles as controller_profiles
from gamehub_cli.common.config import ControllersConfig, GamehubConfig
from gamehub_cli.controllers.profiles import (
    PROFILE_KBM,
    PROFILE_XBOX_1P,
    PROFILE_XBOX_2P,
    load_profile_file,
    profile_name_for_controller_count,
    resolve_profiles_root,
    seed_default_profiles,
)


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


def test_profile_name_for_controller_count() -> None:
    assert profile_name_for_controller_count(0) == PROFILE_KBM
    assert profile_name_for_controller_count(1) == PROFILE_XBOX_1P
    assert profile_name_for_controller_count(2) == PROFILE_XBOX_2P
    assert profile_name_for_controller_count(99) == PROFILE_XBOX_2P


def test_seed_default_profiles_creates_profile_tree(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-profiles-") as temp_root:
        config = _config(temp_root)

        created = seed_default_profiles(config)
        root = resolve_profiles_root(config)

        assert created
        assert (root / "pcsx2" / "kbm" / "PCSX2.ini").exists()
        assert (root / "pcsx2" / "xbox_1p" / "PCSX2.ini").exists()
        assert (root / "pcsx2" / "xbox_2p" / "PCSX2.ini").exists()
        assert (root / "dolphin" / "kbm" / "GCPadNew.ini").exists()
        assert (root / "dolphin" / "xbox_1p" / "WiimoteNew.ini").exists()
        assert (root / "azahar" / "xbox_2p" / "qt-config.ini").exists()

        pcsx2_xbox_1p = (root / "pcsx2" / "xbox_1p" / "PCSX2.ini").read_text(encoding="utf-8")
        assert "Cross = SDL-0/A" in pcsx2_xbox_1p
        assert "Cross = Keyboard/K" in pcsx2_xbox_1p
        assert "Cross = Keyboard/Num0" not in pcsx2_xbox_1p

        dolphin_gc_xbox_1p = (root / "dolphin" / "xbox_1p" / "GCPadNew.ini").read_text(encoding="utf-8")
        assert "[GCPad2]" in dolphin_gc_xbox_1p
        assert "Buttons/A = X" in dolphin_gc_xbox_1p
        assert "Buttons/A = SOUTH | `Button A`" in dolphin_gc_xbox_1p
        assert "Buttons/Z = `Shoulder R` | `Button 5`" in dolphin_gc_xbox_1p
        assert "Triggers/R = `Trigger R` | `Axis 5+`" in dolphin_gc_xbox_1p

        dolphin_wii_xbox_1p = (root / "dolphin" / "xbox_1p" / "WiimoteNew.ini").read_text(encoding="utf-8")
        assert "[Wiimote2]" in dolphin_wii_xbox_1p
        assert "Buttons/A = `Click 0`" in dolphin_wii_xbox_1p
        assert "Buttons/A = SOUTH | `Button A`" in dolphin_wii_xbox_1p
        assert "Buttons/A = SOUTH | `Button A` | `Shoulder R` | `Button 5`" in dolphin_wii_xbox_1p
        assert "Buttons/B = EAST | `Button B` | `Trigger R` | `Axis 5+`" in dolphin_wii_xbox_1p

        dolphin_kbm_hotkeys = (root / "dolphin" / "kbm" / "Hotkeys.ini").read_text(encoding="utf-8")
        if sys.platform.startswith("linux"):
            assert "Device = XInput2/0/Virtual core pointer" in dolphin_kbm_hotkeys


def test_seed_default_profiles_linux_uses_platform_neutral_dolphin_defaults(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-profiles-") as temp_root:
        config = _config(temp_root)

        monkeypatch.setattr(controller_profiles.sys, "platform", "linux")
        monkeypatch.setattr(controller_profiles, "DEFAULT_PROFILE_TEXTS", controller_profiles._default_profile_texts())

        seed_default_profiles(config)
        root = resolve_profiles_root(config)

        dolphin_gc_xbox_1p = (root / "dolphin" / "xbox_1p" / "GCPadNew.ini").read_text(encoding="utf-8")
        dolphin_wii_xbox_1p = (root / "dolphin" / "xbox_1p" / "WiimoteNew.ini").read_text(encoding="utf-8")

        assert "Device = SDL/0/Gamepad" in dolphin_gc_xbox_1p
        assert "Device = DInput/0/Keyboard Mouse" in dolphin_gc_xbox_1p
        assert "Buttons/A = SOUTH | `Button A`" in dolphin_wii_xbox_1p
        assert "Buttons/B = EAST | `Button B`" in dolphin_wii_xbox_1p
        assert "Buttons/A = SOUTH | `Button A` | `Shoulder R` | `Button 5`" in dolphin_wii_xbox_1p
        assert "Buttons/B = EAST | `Button B` | `Trigger R` | `Axis 5+`" in dolphin_wii_xbox_1p
        assert "Device = SteamDeck/0/Steam Deck" not in dolphin_gc_xbox_1p
        assert "Device = SteamDeck/0/Steam Deck" not in dolphin_wii_xbox_1p


def test_seed_default_profiles_skips_custom_profiles_dir(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-profiles-") as temp_root:
        config = GamehubConfig(
            server_url="http://localhost:8000",
            library_dir=temp_root / "library",
            firmware_dir=temp_root / "firmware",
            state_path=temp_root / "state.json",
            steam_userdata_dir=None,
            steam_id=None,
            steam_exe=None,
            sgdb_api_key=None,
            sgdb_cache_dir=temp_root / "cache",
            sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
            controllers=ControllersConfig(profiles_dir=temp_root / "custom-profiles"),
        )

        created = seed_default_profiles(config)
        root = resolve_profiles_root(config)

        assert created == []
        assert not (root / "pcsx2" / "kbm" / "PCSX2.ini").exists()


def test_load_profile_file_prefers_user_override(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-profiles-") as temp_root:
        config = _config(temp_root)
        seed_default_profiles(config)
        root = resolve_profiles_root(config)
        profile_file = root / "pcsx2" / "kbm" / "PCSX2.ini"
        profile_file.write_text("[Hotkeys]\nOpenPauseMenu = Keyboard/F1\n", encoding="utf-8")

        lines = load_profile_file(
            config,
            emulator_name="pcsx2",
            profile_name="kbm",
            filename="PCSX2.ini",
        )

        assert "OpenPauseMenu = Keyboard/F1" in "\n".join(lines)
