from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import shutil
from uuid import uuid4

from gamehub_cli.fsops import replace_file




def test_replace_file_uses_native_replace_when_available() -> None:
    with _workspace_tempdir("gamehub-fsops-") as temp_root:
        source = temp_root / "source.bin"
        destination = temp_root / "destination.bin"
        source.write_bytes(b"new")
        destination.write_bytes(b"old")

        replace_file(source, destination)

        assert destination.read_bytes() == b"new"
        if source.exists():
            assert source.read_bytes() != b"new"


def test_replace_file_falls_back_on_windows_cross_drive_error(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-fsops-") as temp_root:
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
