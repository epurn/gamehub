from __future__ import annotations

from gamehub_cli.common.shortcut_payload import encode_shortcut_payload, parse_shortcut_payload
from gamehub_cli.common.shortcut_payload_registry import (
    load_shortcut_payload_token,
    save_shortcut_payload_registry_atomic,
)


def test_parse_shortcut_payload_round_trip() -> None:
    token = encode_shortcut_payload(
        {
            "v": 1,
            "emulator": "pcsx2",
            "target_exe": "flatpak",
            "target_args": ["run", "--file-forwarding", "net.pcsx2.PCSX2"],
            "start_dir": "",
            "config_path": "D:/GameHub/config.toml",
            "title_id": "title_ps2_ffx",
            "system": "PS2",
            "rom_rel_path": "roms/PS2/Final Fantasy X.iso",
        }
    )

    payload = parse_shortcut_payload(token)

    assert payload.version == 1
    assert payload.emulator == "pcsx2"
    assert payload.target_exe == "flatpak"
    assert payload.target_args == ("run", "--file-forwarding", "net.pcsx2.PCSX2")
    assert payload.config_path == "D:/GameHub/config.toml"
    assert payload.title_id == "title_ps2_ffx"
    assert payload.system == "PS2"
    assert payload.rom_rel_path == "roms/PS2/Final Fantasy X.iso"


def test_parse_shortcut_payload_strips_wrapping_quotes_from_args() -> None:
    token = encode_shortcut_payload(
        {
            "v": 1,
            "emulator": "dolphin",
            "target_exe": '"C:/Emu/Dolphin.exe"',
            "target_args": ['"-b"', '"C:/Games/Path With Spaces/game.iso"'],
            "start_dir": '"C:/Emu"',
        }
    )

    payload = parse_shortcut_payload(token)

    assert payload.target_exe == '"C:/Emu/Dolphin.exe"'
    assert payload.target_args == ("-b", "C:/Games/Path With Spaces/game.iso")


def test_parse_shortcut_payload_preserves_macos_open_args() -> None:
    token = encode_shortcut_payload(
        {
            "v": 1,
            "emulator": "dolphin",
            "target_exe": "/Users/tester/Applications/Dolphin.app/Contents/MacOS/DolphinQt",
            "target_args": ["-b", "-e", "/Users/tester/Games/Super Mario Galaxy.rvz"],
            "macos_open_app": "/Users/tester/Applications/Dolphin.app",
            "macos_open_args": ["-b", "-e", "/Users/tester/Games/Super Mario Galaxy.rvz"],
            "start_dir": "/Users/tester/Applications/Dolphin.app/Contents/MacOS",
        }
    )

    payload = parse_shortcut_payload(token)

    assert payload.target_exe == "/Users/tester/Applications/Dolphin.app/Contents/MacOS/DolphinQt"
    assert payload.target_args == ("-b", "-e", "/Users/tester/Games/Super Mario Galaxy.rvz")
    assert payload.macos_open_app == "/Users/tester/Applications/Dolphin.app"
    assert payload.macos_open_args == ("-b", "-e", "/Users/tester/Games/Super Mario Galaxy.rvz")


def test_parse_shortcut_payload_preserves_macos_user_app_bundle_target() -> None:
    token = encode_shortcut_payload(
        {
            "v": 1,
            "emulator": "retroarch",
            "target_exe": "/Users/tester/Applications/RetroArch.app/Contents/MacOS/retroarch-metal",
            "target_args": ["-f", "-L", "cores/gambatte_libretro.dylib", "/Users/tester/Games/Pokemon.gbc"],
            "macos_open_app": "/Users/tester/Applications/RetroArch.app",
            "macos_open_args": ["-f", "-L", "cores/gambatte_libretro.dylib", "/Users/tester/Games/Pokemon.gbc"],
        }
    )

    payload = parse_shortcut_payload(token)

    assert payload.target_exe == "/Users/tester/Applications/RetroArch.app/Contents/MacOS/retroarch-metal"
    assert payload.macos_open_app == "/Users/tester/Applications/RetroArch.app"
    assert payload.macos_open_args == (
        "-f",
        "-L",
        "cores/gambatte_libretro.dylib",
        "/Users/tester/Games/Pokemon.gbc",
    )


def test_shortcut_payload_registry_round_trip(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-shortcut-payload-registry-") as temp_root:
        token = encode_shortcut_payload(
            {
                "v": 1,
                "emulator": "dolphin",
                "target_exe": "/Users/tester/Applications/Dolphin.app/Contents/MacOS/DolphinQt",
                "target_args": ["-b", "-e", "/Users/tester/Games/Super Mario Galaxy.rvz"],
                "config_path": "/Users/tester/.gamehub/config.toml",
            }
        )
        registry_path = temp_root / "shortcut_payloads.json"

        save_shortcut_payload_registry_atomic(registry_path, {"title_wii_mario": token})

        assert load_shortcut_payload_token(registry_path, "title_wii_mario") == token
