from __future__ import annotations

from pathlib import Path

from gamehub_server.indexer import build_index


def test_build_index_scans_single_title() -> None:
    fixture_root = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "indexer_case"
    bundle = build_index(fixture_root)
    assert bundle.index.index_version == 1
    assert len(bundle.index.systems) == 1
    assert len(bundle.index.titles) == 1
    title = bundle.index.titles[0]
    assert title.system == "NES"
    assert title.title_name == "SuperMarioBros"
    assert title.rom.file_id in bundle.file_paths
    assert len(title.assets) == 1
    assert title.assets[0].asset_id in bundle.asset_paths
