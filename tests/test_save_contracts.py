from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from gamehub_common.ids import make_save_id
from gamehub_common.models import LibraryIndex, SaveSpec


def test_save_spec_accepts_required_fields() -> None:
    save = SaveSpec(
        save_id="save_123",
        title_id="title_123",
        system="PS2",
        kind="memory_card",
        rel_path="saves/PS2/Final Fantasy X/Mcd001.ps2",
        sha256="a" * 64,
        size_bytes=1024,
        updated_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        portable=True,
    )

    assert save.kind == "memory_card"
    assert save.portable is True


def test_save_spec_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError, match="kind"):
        SaveSpec(
            save_id="save_123",
            title_id="title_123",
            system="PS2",
            kind="state",
            rel_path="saves/PS2/FFX/Mcd001.ps2",
            sha256="a" * 64,
            size_bytes=1024,
            updated_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
            portable=True,
        )


def test_save_spec_requires_declared_fields() -> None:
    with pytest.raises(ValidationError, match="title_id"):
        SaveSpec(
            save_id="save_123",
            system="PS2",
            kind="memory_card",
            rel_path="saves/PS2/FFX/Mcd001.ps2",
            sha256="a" * 64,
            size_bytes=1024,
            updated_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
            portable=True,
        )


def test_make_save_id_is_deterministic_and_checksum_sensitive() -> None:
    path = "saves/PS2/Final Fantasy X/Mcd001.ps2"
    checksum_a = "a" * 64
    checksum_b = "b" * 64

    first = make_save_id(path, checksum_a)
    second = make_save_id(path, checksum_a)
    changed = make_save_id(path, checksum_b)

    assert first == second
    assert first.startswith("save_")
    assert first != changed


def test_library_index_accepts_saves_collection() -> None:
    index = LibraryIndex(
        index_version=1,
        systems=(),
        titles=(),
        saves=(
            SaveSpec(
                save_id="save_123",
                title_id="title_123",
                system="PS2",
                kind="memory_card",
                rel_path="saves/PS2/Final Fantasy X/Mcd001.ps2",
                sha256="a" * 64,
                size_bytes=1024,
                updated_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
                portable=True,
            ),
        ),
    )

    assert len(index.saves) == 1
