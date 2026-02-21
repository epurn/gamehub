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
    resolve_retroarch_paths,
    required_retroarch_cores,
)
from gamehub_common.models import LibraryIndex, RomSpec, SystemSpec, TitleEntry




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


def test_ensure_retroarch_cores_read_only_info_dir_warns_without_download_label(monkeypatch, capsys) -> None:
    with _workspace_tempdir("gamehub-retroarch-cores-ro-") as temp_root:
        cores_dir = temp_root / "cores"
        info_dir = temp_root / "info"
        cores_dir.mkdir(parents=True, exist_ok=True)
        (cores_dir / "fceumm_libretro.dll").write_bytes(b"core")
        index = LibraryIndex(
            index_version=1,
            systems=(
                SystemSpec(
                    name="NES",
                    rom_extensions=(".nes",),
                    default_emulator="retroarch",
                    launch_template='"{emulator}" -L cores/fceumm_libretro.dll "{rom}"',
                    firmware=(),
                ),
            ),
            titles=(),
        )
        monkeypatch.setattr("gamehub_cli.retroarch_cores._core_suffix", lambda: ".dll")
        monkeypatch.setattr(
            "gamehub_cli.retroarch_cores._core_base_url",
            lambda: "https://buildbot.libretro.com/nightly/windows/x86_64/latest/",
        )
        monkeypatch.setattr(
            "gamehub_cli.retroarch_cores.resolve_retroarch_paths",
            lambda: RetroArchPaths(cores_dir=cores_dir, info_dir=info_dir),
        )
        monkeypatch.setattr(
            "gamehub_cli.retroarch_cores._ensure_dir_writable",
            lambda path: (False, "[Errno 30] Read-only file system"),
        )
        monkeypatch.setattr(
            "gamehub_cli.retroarch_cores._download_bytes",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected download")),
        )

        ensure_retroarch_cores(index=index, dry_run=False, verbose=False)

        out = capsys.readouterr().out
        assert "skipping RetroArch info metadata install because info_dir is not writable" in out
        assert "failed to download RetroArch info.zip" not in out


def test_resolve_retroarch_paths_linux_ignores_usr_bin_parent(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-retroarch-linux-") as temp_root:
        home = temp_root / "home"
        home.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr("gamehub_cli.retroarch_cores.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr("gamehub_cli.retroarch_cores.os.name", "posix")
        monkeypatch.setattr("gamehub_cli.retroarch_cores.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.retroarch_cores.retroarch_cfg_candidates", lambda explicit_cfg_path=None: [])
        monkeypatch.setattr("gamehub_cli.retroarch_cores.resolve_emulator_executable", lambda _name: "/usr/bin/retroarch")

        paths = resolve_retroarch_paths()

        assert paths is not None
        assert paths.cores_dir != Path("/usr/bin/cores")
        assert paths.info_dir != Path("/usr/bin/info")


def test_resolve_retroarch_paths_linux_prefers_flatpak_when_export_detected(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-retroarch-flatpak-") as temp_root:
        home = temp_root / "home"
        export = home / ".local" / "share" / "flatpak" / "exports" / "bin" / "org.libretro.RetroArch"
        export.parent.mkdir(parents=True, exist_ok=True)
        export.write_bytes(b"#!/bin/sh")
        monkeypatch.setattr("gamehub_cli.retroarch_cores.os.name", "posix")
        monkeypatch.setattr("gamehub_cli.retroarch_cores.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.retroarch_cores.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr("gamehub_cli.retroarch_cores.retroarch_cfg_candidates", lambda explicit_cfg_path=None: [])
        monkeypatch.setattr("gamehub_cli.retroarch_cores.resolve_emulator_executable", lambda _name: str(export))

        paths = resolve_retroarch_paths()

        assert paths is not None
        assert paths.cores_dir == home / ".var" / "app" / "org.libretro.RetroArch" / "config" / "retroarch" / "cores"


def test_resolve_retroarch_paths_expands_tilde_cfg_values(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-retroarch-cfg-tilde-") as temp_root:
        home = temp_root / "home"
        cfg_path = home / ".config" / "retroarch" / "retroarch.cfg"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            "\n".join(
                [
                    'libretro_directory = "~/.var/app/org.libretro.RetroArch/config/retroarch/cores"',
                    'libretro_info_path = "~/.var/app/org.libretro.RetroArch/config/retroarch/info"',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("gamehub_cli.retroarch_cores.os.name", "posix")
        monkeypatch.setattr("gamehub_cli.retroarch_cores.sys.platform", "linux")
        monkeypatch.setattr("gamehub_cli.retroarch_cores.Path.home", classmethod(lambda cls: home))
        monkeypatch.setattr(
            "gamehub_cli.retroarch_cores.retroarch_cfg_candidates",
            lambda explicit_cfg_path=None: [cfg_path],
        )
        monkeypatch.setattr("gamehub_cli.retroarch_cores.resolve_emulator_executable", lambda _name: "/usr/bin/retroarch")

        paths = resolve_retroarch_paths()

        assert paths is not None
        assert paths.cores_dir == home / ".var" / "app" / "org.libretro.RetroArch" / "config" / "retroarch" / "cores"
        assert paths.info_dir == home / ".var" / "app" / "org.libretro.RetroArch" / "config" / "retroarch" / "info"


def test_resolve_retroarch_paths_windows_colon_cfg_values(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-retroarch-cfg-colon-") as temp_root:
        cfg_path = temp_root / "retroarch.cfg"
        cfg_path.write_text(
            "\n".join(
                [
                    'libretro_directory = ":/cores"',
                    'libretro_info_path = ":/info"',
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        monkeypatch.setattr("gamehub_cli.retroarch_cores.os.name", "nt")
        monkeypatch.setattr("gamehub_cli.retroarch_cores.retroarch_cfg_candidates", lambda explicit_cfg_path=None: [cfg_path])

        paths = resolve_retroarch_paths()

        assert paths is not None
        assert paths.cores_dir == temp_root / "cores"
        assert paths.info_dir == temp_root / "info"
