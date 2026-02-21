from __future__ import annotations

import os
from pathlib import Path

import pytest

import gamehub_server.indexer as indexer_module
from gamehub_common.ids import make_file_id, make_title_id, sha256_file
from gamehub_server.indexer import SYSTEM_CATALOG, build_index

INITIAL_SYSTEM_SET = {
    "GB",
    "GBA",
    "GBC",
    "GEN_MD",
    "N64",
    "NDS",
    "N3DS",
    "NES",
    "PSX",
    "SNES",
    "GC",
    "Wii",
    "PS2",
}


def _write_file(path: Path, payload: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def test_build_index_scans_single_title(workspace_tempdir) -> None:
    with workspace_tempdir(prefix="gamehub-indexer-") as root:
        rom_path = root / "roms" / "NES" / "SuperMarioBros.nes"
        _write_file(rom_path, b"rom")
        bundle = build_index(root)
        assert bundle.index.index_version == 1
        assert len(bundle.index.systems) == 1
        assert len(bundle.index.titles) == 1
        title = bundle.index.titles[0]
        assert title.system == "NES"
        assert title.title_name == "SuperMarioBros"
        assert title.title_rel_dir == "NES/SuperMarioBros.nes"
        expected_rom_rel = "roms/NES/SuperMarioBros.nes"
        expected_rom_sha = sha256_file(rom_path)
        assert title.rom.rel_path == expected_rom_rel
        assert title.rom.file_id == make_file_id(expected_rom_rel, expected_rom_sha)
        assert title.title_id == make_title_id("NES", "NES/SuperMarioBros.nes")
        assert title.rom.file_id in bundle.file_paths
        assert title.assets == ()
        assert bundle.asset_paths == {}


def test_build_index_rejects_nested_title_directories(workspace_tempdir) -> None:
    with workspace_tempdir(prefix="gamehub-indexer-") as temp_dir:
        root = temp_dir
        _write_file(root / "roms" / "NES" / "SuperMarioBros" / "mario.nes")
        with pytest.raises(ValueError, match="Unexpected title directory"):
            build_index(root)


def test_build_index_rejects_duplicate_title_stems(workspace_tempdir) -> None:
    with workspace_tempdir(prefix="gamehub-indexer-") as temp_dir:
        root = temp_dir
        _write_file(root / "roms" / "PS2" / "FinalFantasyX.iso")
        _write_file(root / "roms" / "PS2" / "FinalFantasyX.chd")
        with pytest.raises(ValueError, match="Duplicate title name in PS2"):
            build_index(root)


def test_build_index_includes_firmware_metadata(workspace_tempdir) -> None:
    with workspace_tempdir(prefix="gamehub-indexer-") as temp_dir:
        root = temp_dir
        _write_file(root / "roms" / "PS2" / "FinalFantasyX.iso")
        _write_file(root / "firmware" / "PS2" / "scph10000.bin", b"required")
        _write_file(root / "firmware" / "PS2" / "custom_patch.bin", b"optional")

        bundle = build_index(root)
        ps2 = next(system for system in bundle.index.systems if system.name == "PS2")
        by_name = {item.filename: item for item in ps2.firmware}

        assert set(by_name) == {"custom_patch.bin", "scph10000.bin"}
        assert by_name["scph10000.bin"].required is True
        assert by_name["custom_patch.bin"].required is False
        assert by_name["scph10000.bin"].sha256 == sha256_file(root / "firmware" / "PS2" / "scph10000.bin")
        assert by_name["custom_patch.bin"].sha256 == sha256_file(root / "firmware" / "PS2" / "custom_patch.bin")


def test_build_index_requires_required_firmware_for_indexed_system(workspace_tempdir) -> None:
    with workspace_tempdir(prefix="gamehub-indexer-") as temp_dir:
        root = temp_dir
        _write_file(root / "roms" / "PS2" / "FinalFantasyX.iso")
        with pytest.raises(ValueError, match="Missing required firmware for PS2: scph10000.bin"):
            build_index(root)


def test_system_catalog_matches_initial_supported_set() -> None:
    assert set(SYSTEM_CATALOG) == INITIAL_SYSTEM_SET
    assert "PS1" not in SYSTEM_CATALOG
    assert SYSTEM_CATALOG["N3DS"]["extensions"] == (".3ds", ".cci", ".cxi")
    assert SYSTEM_CATALOG["N3DS"]["emulator"] == "azahar"
    assert SYSTEM_CATALOG["N3DS"]["firmware"] == ()
    assert SYSTEM_CATALOG["PSX"]["firmware"] == ("scph5501.bin",)
    assert SYSTEM_CATALOG["Wii"]["firmware"] == ()
    assert SYSTEM_CATALOG["Wii"]["scan_firmware"] is False
    assert SYSTEM_CATALOG["N3DS"]["scan_firmware"] is False
    assert ' -b -e "{rom}"' in SYSTEM_CATALOG["GC"]["launch_template"]
    assert ' -b -e "{rom}"' in SYSTEM_CATALOG["Wii"]["launch_template"]
    assert ' -fullscreen "{rom}"' in SYSTEM_CATALOG["PS2"]["launch_template"]


def test_build_index_supports_all_initial_systems(workspace_tempdir) -> None:
    filenames = {
        "GB": "Tetris.gb",
        "GBA": "MetroidFusion.gba",
        "GBC": "PokemonCrystal.gbc",
        "GEN_MD": "Sonic2.md",
        "N64": "Mario64.z64",
        "NDS": "MarioKartDS.nds",
        "N3DS": "OcarinaOfTime.3ds",
        "NES": "SuperMarioBros.nes",
        "PSX": "FinalFantasyVII.chd",
        "SNES": "SuperMetroid.sfc",
        "GC": "WindWaker.iso",
        "Wii": "MarioGalaxy.iso",
        "PS2": "FinalFantasyX.iso",
    }

    with workspace_tempdir(prefix="gamehub-indexer-") as root:
        for system, filename in filenames.items():
            _write_file(root / "roms" / system / filename, b"rom")
        _write_file(root / "firmware" / "PSX" / "scph5501.bin", b"psx-fw")
        _write_file(root / "firmware" / "PS2" / "scph10000.bin", b"ps2-fw")
        _write_file(root / "firmware" / "Wii" / "keys.bin", b"wii-fw")

        bundle = build_index(root)
        system_names = {system.name for system in bundle.index.systems}
        title_systems = {title.system for title in bundle.index.titles}
        assert system_names == INITIAL_SYSTEM_SET
        assert title_systems == INITIAL_SYSTEM_SET
        assert all(title.system != "PS1" for title in bundle.index.titles)
        assert any(title.system == "PSX" for title in bundle.index.titles)
        assert len(bundle.index.titles) == len(INITIAL_SYSTEM_SET)


def test_build_index_ignores_psx_and_ps2_7z_archives(workspace_tempdir) -> None:
    with workspace_tempdir(prefix="gamehub-indexer-") as root:
        _write_file(root / "roms" / "PSX" / "Ape Escape.7z", b"archive")
        _write_file(root / "roms" / "PS2" / "Shadow of the Colossus.7z", b"archive")

        bundle = build_index(root)
        assert not bundle.index.titles


def test_build_index_does_not_require_wii_keys_file(workspace_tempdir) -> None:
    with workspace_tempdir(prefix="gamehub-indexer-") as root:
        _write_file(root / "roms" / "Wii" / "MarioGalaxy.iso", b"rom")

        bundle = build_index(root)
        assert len(bundle.index.titles) == 1
        assert bundle.index.titles[0].system == "Wii"


def test_build_index_ignores_wii_firmware_directory_files(workspace_tempdir) -> None:
    with workspace_tempdir(prefix="gamehub-indexer-") as root:
        _write_file(root / "roms" / "Wii" / "MarioGalaxy.iso", b"rom")
        _write_file(root / "firmware" / "Wii" / "keys.md", b"wiiu-keys")
        _write_file(root / "firmware" / "Wii" / "keys.bin", b"legacy")

        bundle = build_index(root)
        wii = next(system for system in bundle.index.systems if system.name == "Wii")
        assert wii.firmware == ()


def test_build_index_supports_dolphin_ciso_for_gc_and_wii(workspace_tempdir) -> None:
    with workspace_tempdir(prefix="gamehub-indexer-") as root:
        _write_file(root / "roms" / "GC" / "FZeroGX.ciso", b"gc-ciso")
        _write_file(root / "roms" / "Wii" / "MarioKartWii.ciso", b"wii-ciso")

        bundle = build_index(root)
        by_system = {title.system: title for title in bundle.index.titles}
        assert by_system["GC"].rom.extension == ".ciso"
        assert by_system["Wii"].rom.extension == ".ciso"


def test_build_index_supports_n3ds_supported_extensions_and_ignores_unsupported(workspace_tempdir) -> None:
    with workspace_tempdir(prefix="gamehub-indexer-") as root:
        _write_file(root / "roms" / "N3DS" / "Pilotwings.3ds", b"rom-3ds")
        _write_file(root / "roms" / "N3DS" / "MiiMaker.cci", b"rom-cci")
        _write_file(root / "roms" / "N3DS" / "HomeMenu.cxi", b"rom-cxi")
        _write_file(root / "roms" / "N3DS" / "InstallMe.cia", b"unsupported")

        bundle = build_index(root)
        titles = [title for title in bundle.index.titles if title.system == "N3DS"]
        extensions = {title.rom.extension for title in titles}
        names = {title.title_name for title in titles}

        assert extensions == {".3ds", ".cci", ".cxi"}
        assert names == {"Pilotwings", "MiiMaker", "HomeMenu"}
        assert "InstallMe" not in names


def test_build_index_ignores_n3ds_firmware_directory_files(workspace_tempdir) -> None:
    with workspace_tempdir(prefix="gamehub-indexer-") as root:
        _write_file(root / "roms" / "N3DS" / "Pilotwings.3ds", b"rom")
        _write_file(root / "firmware" / "N3DS" / "legacy_keys.txt", b"keys")
        _write_file(root / "firmware" / "N3DS" / "seeddb.bin", b"seeddb")

        bundle = build_index(root)
        n3ds = next(system for system in bundle.index.systems if system.name == "N3DS")
        assert n3ds.firmware == ()


def test_build_index_reuses_cached_hashes_for_unchanged_files(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir(prefix="gamehub-indexer-") as root:
        _write_file(root / "roms" / "PS2" / "FinalFantasyX.iso", b"rom")
        _write_file(root / "firmware" / "PS2" / "scph10000.bin", b"fw")
        build_index(root)

        calls: list[Path] = []
        original_sha256 = indexer_module.sha256_file

        def counting_sha256(path: Path) -> str:
            calls.append(path)
            return original_sha256(path)

        monkeypatch.setattr(indexer_module, "sha256_file", counting_sha256)
        build_index(root)

        assert calls == []


def test_build_index_rehashes_changed_files(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir(prefix="gamehub-indexer-") as root:
        rom_path = root / "roms" / "NES" / "SuperMarioBros.nes"
        _write_file(rom_path, b"rom-v1")
        build_index(root)

        calls: list[Path] = []
        original_sha256 = indexer_module.sha256_file

        def counting_sha256(path: Path) -> str:
            calls.append(path)
            return original_sha256(path)

        monkeypatch.setattr(indexer_module, "sha256_file", counting_sha256)
        _write_file(rom_path, b"rom-v2")
        stat = rom_path.stat()
        os.utime(rom_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

        build_index(root)

        assert calls == [rom_path]
