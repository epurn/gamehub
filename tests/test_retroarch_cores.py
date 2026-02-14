from __future__ import annotations

from contextlib import contextmanager
import io
from pathlib import Path
import shutil
from uuid import uuid4
import zipfile

from gamehub_cli.retroarch_cores import (
    RetroArchPaths,
    ensure_retroarch_cores,
    required_retroarch_cores,
)
from gamehub_common.models import LibraryIndex, RomSpec, SystemSpec, TitleEntry


@contextmanager
def _workspace_tempdir(prefix: str):
    root = Path(__file__).resolve().parents[1] / ".pytest_tmp_local"
    root.mkdir(parents=True, exist_ok=True)
    temp_dir = root / f"{prefix}{uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=False)
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _zip_blob(member_name: str, payload: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member_name, payload)
    return buffer.getvalue()


def test_required_retroarch_cores_extracts_from_launch_template() -> None:
    index = LibraryIndex(
        index_version=1,
        systems=(
            SystemSpec(
                name="NDS",
                rom_extensions=(".nds",),
                default_emulator="retroarch",
                launch_template='"{emulator}" -L cores/melondsds_libretro.dll "{rom}"',
                firmware=(),
            ),
        ),
        titles=(),
    )

    required = required_retroarch_cores(index)

    assert required == {"NDS": "melondsds_libretro"}


def test_required_retroarch_cores_uses_fallback_mapping_for_missing_core_token() -> None:
    index = LibraryIndex(
        index_version=1,
        systems=(
            SystemSpec(
                name="NDS",
                rom_extensions=(".nds",),
                default_emulator="retroarch",
                launch_template='"{emulator}" "{rom}"',
                firmware=(),
            ),
        ),
        titles=(),
    )

    required = required_retroarch_cores(index)

    assert required == {"NDS": "melondsds_libretro"}


def test_ensure_retroarch_cores_installs_core_and_info_once_for_shared_core(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-retroarch-cores-") as temp_root:
        cores_dir = temp_root / "cores"
        info_dir = temp_root / "info"
        paths = RetroArchPaths(cores_dir=cores_dir, info_dir=info_dir)
        index = LibraryIndex(
            index_version=1,
            systems=(
                SystemSpec(
                    name="GB",
                    rom_extensions=(".gb",),
                    default_emulator="retroarch",
                    launch_template='"{emulator}" -L cores/gambatte_libretro.dll "{rom}"',
                    firmware=(),
                ),
                SystemSpec(
                    name="GBC",
                    rom_extensions=(".gbc",),
                    default_emulator="retroarch",
                    launch_template='"{emulator}" -L cores/gambatte_libretro.dll "{rom}"',
                    firmware=(),
                ),
            ),
            titles=(),
        )
        calls: list[str] = []

        def fake_download(url: str, timeout_seconds: float = 30.0) -> bytes:
            del timeout_seconds
            calls.append(url)
            if url.endswith("assets/frontend/info.zip"):
                return _zip_blob("gambatte_libretro.info", b"info")
            return _zip_blob("gambatte_libretro.dll", b"core")

        monkeypatch.setattr("gamehub_cli.retroarch_cores._core_suffix", lambda: ".dll")
        monkeypatch.setattr(
            "gamehub_cli.retroarch_cores._core_base_url",
            lambda: "https://buildbot.libretro.com/nightly/windows/x86_64/latest/",
        )
        monkeypatch.setattr("gamehub_cli.retroarch_cores.resolve_retroarch_paths", lambda: paths)
        monkeypatch.setattr("gamehub_cli.retroarch_cores._download_bytes", fake_download)

        ensure_retroarch_cores(index=index, dry_run=False, verbose=False)

        assert (cores_dir / "gambatte_libretro.dll").read_bytes() == b"core"
        assert (info_dir / "gambatte_libretro.info").read_bytes() == b"info"
        assert len(calls) == 2
        assert calls[0].endswith("/gambatte_libretro.dll.zip")
        assert calls[1].endswith("/assets/frontend/info.zip")


def test_ensure_retroarch_cores_dry_run_reports_missing(monkeypatch, capsys) -> None:
    with _workspace_tempdir("gamehub-retroarch-cores-") as temp_root:
        index = LibraryIndex(
            index_version=1,
            systems=(),
            titles=(
                TitleEntry(
                    title_id="title_n64_sm64",
                    system="N64",
                    title_name="Super Mario 64",
                    title_rel_dir="N64/Super Mario 64.z64",
                    emulator="retroarch",
                    launch_template='"{emulator}" -L cores/mupen64plus_next_libretro.dll "{rom}"',
                    rom=RomSpec(
                        file_id="file_sm64",
                        rel_path="roms/N64/Super Mario 64.z64",
                        sha256="a" * 64,
                        size_bytes=4,
                        extension=".z64",
                    ),
                    assets=(),
                ),
            ),
        )
        monkeypatch.setattr("gamehub_cli.retroarch_cores._core_suffix", lambda: ".dll")
        monkeypatch.setattr(
            "gamehub_cli.retroarch_cores._core_base_url",
            lambda: "https://buildbot.libretro.com/nightly/windows/x86_64/latest/",
        )
        monkeypatch.setattr(
            "gamehub_cli.retroarch_cores.resolve_retroarch_paths",
            lambda: RetroArchPaths(cores_dir=temp_root / "cores", info_dir=temp_root / "info"),
        )

        ensure_retroarch_cores(index=index, dry_run=True, verbose=False)

        out = capsys.readouterr().out
        assert "retroarch-core\tmissing\tN64\tmupen64plus_next_libretro.dll" in out
        assert "retroarch-info\tmissing\tN64\tmupen64plus_next_libretro.info" in out
