from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import shutil
import uuid

import pytest

from gamehub_common.ids import make_file_id, make_title_id, sha256_file
from gamehub_server.indexer import SYSTEM_CATALOG, build_index

TMP_ROOT = Path(__file__).resolve().parents[1] / ".pytest_tmp_local"
TMP_ROOT.mkdir(parents=True, exist_ok=True)

INITIAL_SYSTEM_SET = {
    "GB",
    "GBA",
    "GBC",
    "GEN_MD",
    "N64",
    "NDS",
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


@contextmanager
def _workspace_tempdir(prefix: str):
    path = TMP_ROOT / f"{prefix}{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_build_index_scans_single_title() -> None:
    with _workspace_tempdir(prefix="gamehub-indexer-") as root:
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


def test_build_index_rejects_nested_title_directories() -> None:
    with _workspace_tempdir(prefix="gamehub-indexer-") as temp_dir:
        root = temp_dir
        _write_file(root / "roms" / "NES" / "SuperMarioBros" / "mario.nes")
        with pytest.raises(ValueError, match="Unexpected title directory"):
            build_index(root)


def test_build_index_rejects_duplicate_title_stems() -> None:
    with _workspace_tempdir(prefix="gamehub-indexer-") as temp_dir:
        root = temp_dir
        _write_file(root / "roms" / "PS2" / "FinalFantasyX.iso")
        _write_file(root / "roms" / "PS2" / "FinalFantasyX.chd")
        with pytest.raises(ValueError, match="Duplicate title name in PS2"):
            build_index(root)


def test_build_index_includes_firmware_metadata() -> None:
    with _workspace_tempdir(prefix="gamehub-indexer-") as temp_dir:
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


def test_build_index_requires_required_firmware_for_indexed_system() -> None:
    with _workspace_tempdir(prefix="gamehub-indexer-") as temp_dir:
        root = temp_dir
        _write_file(root / "roms" / "PS2" / "FinalFantasyX.iso")
        with pytest.raises(ValueError, match="Missing required firmware for PS2: scph10000.bin"):
            build_index(root)


def test_system_catalog_matches_initial_supported_set() -> None:
    assert set(SYSTEM_CATALOG) == INITIAL_SYSTEM_SET
    assert "PS1" not in SYSTEM_CATALOG
    assert SYSTEM_CATALOG["PSX"]["firmware"] == ("scph5501.bin",)


def test_build_index_supports_all_initial_systems() -> None:
    filenames = {
        "GB": "Tetris.gb",
        "GBA": "MetroidFusion.gba",
        "GBC": "PokemonCrystal.gbc",
        "GEN_MD": "Sonic2.md",
        "N64": "Mario64.z64",
        "NDS": "MarioKartDS.nds",
        "NES": "SuperMarioBros.nes",
        "PSX": "FinalFantasyVII.chd",
        "SNES": "SuperMetroid.sfc",
        "GC": "WindWaker.iso",
        "Wii": "MarioGalaxy.iso",
        "PS2": "FinalFantasyX.iso",
    }

    with _workspace_tempdir(prefix="gamehub-indexer-") as root:
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
