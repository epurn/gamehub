from __future__ import annotations

import os
from pathlib import Path

from gamehub_cli.common.paths import from_rel_path, normalized_local_path
from gamehub_cli.common.platform_paths import (
    RETROARCH_FLATPAK_APP_ID,
    host_path,
    is_flatpak_command,
    parse_simple_kv_config,
    retroarch_cfg_candidates,
    unique_paths,
)


def test_from_rel_path_uses_posix_relative_segments() -> None:
    base = Path("D:/GameHub")
    resolved = from_rel_path(base, "roms/NES/Super Mario Bros.nes")
    assert resolved == Path("D:/GameHub/roms/NES/Super Mario Bros.nes")


def test_from_rel_path_returns_canonical_path_when_only_legacy_exists(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-paths-") as temp_root:
        legacy = temp_root / "NES" / "SuperMarioBros.nes"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_bytes(b"legacy")
        canonical = temp_root / "roms" / "NES" / "SuperMarioBros.nes"

        resolved = from_rel_path(temp_root, "roms/NES/SuperMarioBros.nes", preferred_root="roms")
        assert resolved == canonical
        assert resolved != legacy


def test_from_rel_path_prefers_canonical_when_present(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-paths-") as temp_root:
        canonical = temp_root / "roms" / "NES" / "SuperMarioBros.nes"
        canonical.parent.mkdir(parents=True, exist_ok=True)
        canonical.write_bytes(b"canonical")

        resolved = from_rel_path(temp_root, "NES/SuperMarioBros.nes", preferred_root="roms")
        assert resolved == canonical


def test_is_flatpak_command_matches_flatpak_export_path() -> None:
    value = "/home/deck/.local/share/flatpak/exports/bin/org.libretro.RetroArch"
    assert is_flatpak_command(value, RETROARCH_FLATPAK_APP_ID) is True


def test_unique_paths_dedupes_expanduser_results(monkeypatch) -> None:
    values = unique_paths([Path("C:/RetroArch"), Path("C:/RetroArch"), Path("D:/RetroArch")])
    assert values == [Path("C:/RetroArch"), Path("D:/RetroArch")]


def test_host_path_uses_host_path_class_when_os_name_is_monkeypatched(monkeypatch) -> None:
    expected_type = type(host_path("."))
    monkeypatch.setattr("gamehub_cli.common.platform_paths.os.name", "nt" if os.name != "nt" else "posix")

    candidate = host_path("/Applications/RetroArch.app")

    assert type(candidate) is expected_type


def test_parse_simple_kv_config_reads_key_value_pairs(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-paths-") as temp_root:
        cfg = temp_root / "retroarch.cfg"
        cfg.write_text(
            "\n".join(
                [
                    "# comment",
                    "libretro_directory = /opt/retroarch/cores",
                    'system_directory = "default"',
                ]
            ),
            encoding="utf-8",
        )
        parsed = parse_simple_kv_config(cfg)
        assert parsed["libretro_directory"] == "/opt/retroarch/cores"
        assert parsed["system_directory"] == "default"


def test_retroarch_cfg_candidates_dedupes_explicit_path(monkeypatch) -> None:
    home = Path("/var/home/deck")
    explicit = home / ".config" / "retroarch" / "retroarch.cfg"
    monkeypatch.setattr("gamehub_cli.common.platform_paths.Path.home", classmethod(lambda cls: home))
    monkeypatch.setattr("gamehub_cli.common.platform_paths._OS_NAME", "posix")
    candidates = retroarch_cfg_candidates(explicit_cfg_path=explicit)
    assert candidates.count(explicit) == 1


def test_retroarch_cfg_candidates_includes_portable_windows_cfg(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-paths-") as temp_root:
        retroarch_root = temp_root / "RetroArch-Win64"
        retroarch_root.mkdir(parents=True, exist_ok=True)
        retroarch_exe = retroarch_root / "retroarch.exe"
        retroarch_exe.write_text("", encoding="utf-8")

        monkeypatch.setattr("gamehub_cli.common.platform_paths._OS_NAME", "nt")

        candidates = retroarch_cfg_candidates(
            explicit_cfg_path=None,
            resolve_emulator_executable=lambda _name: str(retroarch_exe),
        )

        assert retroarch_root / "retroarch.cfg" in candidates


def test_retroarch_cfg_candidates_prefers_flatpak_cfg_when_runtime_is_flatpak(monkeypatch) -> None:
    home = Path("/var/home/deck")
    monkeypatch.setattr("gamehub_cli.common.platform_paths.Path.home", classmethod(lambda cls: home))
    monkeypatch.setattr("gamehub_cli.common.platform_paths._OS_NAME", "posix")

    candidates = retroarch_cfg_candidates(
        explicit_cfg_path=None,
        resolve_emulator_executable=lambda _name: str(
            home / ".local" / "share" / "flatpak" / "exports" / "bin" / RETROARCH_FLATPAK_APP_ID
        ),
    )

    assert candidates[:2] == [
        home / ".var" / "app" / RETROARCH_FLATPAK_APP_ID / "config" / "retroarch" / "retroarch.cfg",
        home / ".config" / "retroarch" / "retroarch.cfg",
    ]


def test_normalized_local_path_handles_windows_style_segments() -> None:
    normalized = normalized_local_path(r"C:\Users\Deck\Saved Games\PCSX2\memcards")
    assert normalized == Path("C:/Users/Deck/Saved Games/PCSX2/memcards")


def test_normalized_local_path_strips_current_directory_segments() -> None:
    normalized = normalized_local_path("./saves/./PS2/Mcd001.ps2")
    assert normalized == Path("saves/PS2/Mcd001.ps2")
