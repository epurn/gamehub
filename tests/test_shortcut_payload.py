from __future__ import annotations

from gamehub_cli.common.shortcut_payload import encode_shortcut_payload, parse_shortcut_payload


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
            "emulator": "pcsx2",
            "target_exe": "/Applications/PCSX2.app/Contents/MacOS/pcsx2-qt",
            "target_args": ["-fullscreen", "/Users/test/Games/Gran Turismo 4.iso"],
            "macos_open_app": "/Applications/PCSX2.app",
            "macos_open_args": ["-fullscreen", "/Users/test/Games/Gran Turismo 4.iso"],
            "start_dir": "/Applications/PCSX2.app/Contents/MacOS",
        }
    )

    payload = parse_shortcut_payload(token)

    assert payload.target_exe == "/Applications/PCSX2.app/Contents/MacOS/pcsx2-qt"
    assert payload.target_args == ("-fullscreen", "/Users/test/Games/Gran Turismo 4.iso")
    assert payload.macos_open_app == "/Applications/PCSX2.app"
    assert payload.macos_open_args == ("-fullscreen", "/Users/test/Games/Gran Turismo 4.iso")
