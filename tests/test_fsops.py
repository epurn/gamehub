from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import gamehub_cli.common.fsops as fsops
from gamehub_cli.common.fsops import backup_existing_file, iter_gamehub_backup_families, replace_file


def test_replace_file_uses_native_replace_when_available(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-fsops-") as temp_root:
        source = temp_root / "source.bin"
        destination = temp_root / "destination.bin"
        source.write_bytes(b"new")
        destination.write_bytes(b"old")

        replace_file(source, destination)

        assert destination.read_bytes() == b"new"
        if source.exists():
            assert source.read_bytes() != b"new"


def test_replace_file_falls_back_on_windows_cross_drive_error(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-fsops-") as temp_root:
        source = temp_root / "source.bin"
        destination = temp_root / "destination.bin"
        source.write_bytes(b"new")
        destination.write_bytes(b"old")

        original_replace = Path.replace

        def fake_replace(self: Path, target: Path):
            if self == source:
                err = OSError("cross-device rename")
                setattr(err, "winerror", 17)
                raise err
            return original_replace(self, target)

        monkeypatch.setattr(Path, "replace", fake_replace)

        replace_file(source, destination)

        assert destination.read_bytes() == b"new"
        # Fallback path should not leave the original payload in source.
        if source.exists():
            assert source.read_bytes() != b"new"


def test_backup_existing_file_prunes_older_backups(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-fsops-") as temp_root:
        current = temp_root / "state.json"
        current.write_text("current\n", encoding="utf-8")
        oldest = temp_root / "state.json.20260309115958.bak"
        newer = temp_root / "state.json.20260309115959.bak"
        oldest.write_text("oldest\n", encoding="utf-8")
        newer.write_text("newer\n", encoding="utf-8")

        fixed_now = datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC)

        class _FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_now if tz is None else fixed_now.astimezone(tz)

        monkeypatch.setattr(fsops, "datetime", _FixedDateTime)

        result = backup_existing_file(current, keep_limit=2)

        assert result.created_path == temp_root / "state.json.20260309120000.bak"
        assert result.pruned_paths == (oldest,)
        backups = sorted(temp_root.glob("state.json.*.bak"))
        assert backups == [newer, temp_root / "state.json.20260309120000.bak"]


def test_iter_gamehub_backup_families_ignores_non_gamehub_bak_files(workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-fsops-") as temp_root:
        (temp_root / "notes.bak").write_text("manual note\n", encoding="utf-8")
        (temp_root / "state.json.manual.bak").write_text("manual backup\n", encoding="utf-8")
        valid_backup = temp_root / "state.json.20260309120000.bak"
        valid_backup.write_text("managed backup\n", encoding="utf-8")

        families = list(iter_gamehub_backup_families(temp_root))

        assert families == [(temp_root, "state.json", (valid_backup,))]
