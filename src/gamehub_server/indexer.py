from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import NotRequired, TypedDict

from gamehub_common.ids import make_file_id, make_title_id, sha256_file
from gamehub_common.models import FirmwareSpec, LibraryIndex, RomSpec, SystemSpec, TitleEntry

FIRMWARE_ROOT_NAME = "firmware"
ROMS_ROOT_NAME = "roms"
_DEFAULT_HASH_CACHE_FILENAME = "gamehub-hash-cache.sqlite3"
logger = logging.getLogger(__name__)


class _SystemCatalogEntry(TypedDict):
    extensions: tuple[str, ...]
    emulator: str
    launch_template: str
    firmware: tuple[str, ...]
    scan_firmware: NotRequired[bool]


SYSTEM_CATALOG: dict[str, _SystemCatalogEntry] = {
    "GB": {
        "extensions": (".gb", ".zip"),
        "emulator": "retroarch",
        "launch_template": '"{emulator}" -f -L cores/gambatte_libretro.dll "{rom}"',
        "firmware": (),
    },
    "GBA": {
        "extensions": (".gba", ".zip"),
        "emulator": "retroarch",
        "launch_template": '"{emulator}" -f -L cores/mgba_libretro.dll "{rom}"',
        "firmware": (),
    },
    "GBC": {
        "extensions": (".gbc", ".zip"),
        "emulator": "retroarch",
        "launch_template": '"{emulator}" -f -L cores/gambatte_libretro.dll "{rom}"',
        "firmware": (),
    },
    "GC": {
        "extensions": (".iso", ".gcm", ".rvz", ".ciso"),
        "emulator": "dolphin",
        "launch_template": '"{emulator}" -b -e "{rom}"',
        "firmware": (),
    },
    "GEN_MD": {
        "extensions": (".gen", ".md", ".smd", ".bin", ".zip"),
        "emulator": "retroarch",
        "launch_template": '"{emulator}" -f -L cores/genesis_plus_gx_libretro.dll "{rom}"',
        "firmware": (),
    },
    "NES": {
        "extensions": (".nes", ".zip"),
        "emulator": "retroarch",
        "launch_template": '"{emulator}" -f -L cores/fceumm_libretro.dll "{rom}"',
        "firmware": (),
    },
    "SNES": {
        "extensions": (".sfc", ".smc", ".zip"),
        "emulator": "retroarch",
        "launch_template": '"{emulator}" -f -L cores/snes9x_libretro.dll "{rom}"',
        "firmware": (),
    },
    "N64": {
        "extensions": (".n64", ".z64", ".v64", ".zip"),
        "emulator": "retroarch",
        "launch_template": '"{emulator}" -f -L cores/mupen64plus_next_libretro.dll "{rom}"',
        "firmware": (),
    },
    "NDS": {
        "extensions": (".nds", ".zip"),
        "emulator": "retroarch",
        "launch_template": '"{emulator}" -f -L cores/melondsds_libretro.dll "{rom}"',
        "firmware": (),
    },
    "N3DS": {
        "extensions": (".3ds", ".cci", ".cxi"),
        "emulator": "azahar",
        "launch_template": '"{emulator}" "{rom}"',
        "firmware": (),
        "scan_firmware": False,
    },
    "PSX": {
        "extensions": (".chd", ".cue", ".iso", ".pbp"),
        "emulator": "retroarch",
        "launch_template": '"{emulator}" -f -L cores/swanstation_libretro.dll "{rom}"',
        "firmware": ("scph5501.bin",),
    },
    "PS2": {
        "extensions": (".iso", ".chd"),
        "emulator": "pcsx2",
        "launch_template": '"{emulator}" -fullscreen "{rom}"',
        "firmware": ("scph10000.bin",),
    },
    "Wii": {
        "extensions": (".iso", ".wbfs", ".rvz", ".ciso"),
        "emulator": "dolphin",
        "launch_template": '"{emulator}" -b -e "{rom}"',
        "firmware": (),
        "scan_firmware": False,
    },
}


@dataclass(frozen=True)
class IndexBundle:
    index: LibraryIndex
    file_paths: dict[str, Path]
    asset_paths: dict[str, Path]


@dataclass
class _HashCache:
    root_id: str
    connection: sqlite3.Connection | None

    @classmethod
    def open(cls, data_root: Path) -> _HashCache:
        root_id = str(data_root.resolve())
        raw_path = os.environ.get("GAMEHUB_HASH_CACHE_PATH", "").strip()
        if raw_path:
            cache_path = Path(raw_path).expanduser()
        else:
            cache_path = Path(tempfile.gettempdir()) / _DEFAULT_HASH_CACHE_FILENAME
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(cache_path)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS file_hashes (
                    root_id TEXT NOT NULL,
                    rel_path TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (root_id, rel_path)
                )
                """
            )
            return cls(root_id=root_id, connection=connection)
        except (OSError, sqlite3.Error) as exc:
            logger.warning("hash cache disabled cache_path=%s reason=%s", cache_path, exc)
            return cls(root_id=root_id, connection=None)

    def get_sha256(self, path: Path, rel_path: str, *, size_bytes: int, mtime_ns: int) -> str:
        if self.connection is None:
            return sha256_file(path)

        try:
            row = self.connection.execute(
                """
                SELECT sha256
                FROM file_hashes
                WHERE root_id = ? AND rel_path = ? AND size_bytes = ? AND mtime_ns = ?
                """,
                (self.root_id, rel_path, int(size_bytes), int(mtime_ns)),
            ).fetchone()
        except sqlite3.Error as exc:
            logger.warning("hash cache read failed rel_path=%s reason=%s", rel_path, exc)
            return sha256_file(path)

        if row is not None:
            return str(row[0])

        digest = sha256_file(path)
        try:
            self.connection.execute(
                """
                INSERT INTO file_hashes (root_id, rel_path, size_bytes, mtime_ns, sha256, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(root_id, rel_path) DO UPDATE SET
                    size_bytes = excluded.size_bytes,
                    mtime_ns = excluded.mtime_ns,
                    sha256 = excluded.sha256,
                    updated_at = excluded.updated_at
                """,
                (self.root_id, rel_path, int(size_bytes), int(mtime_ns), digest, time.time()),
            )
        except sqlite3.Error as exc:
            logger.warning("hash cache write failed rel_path=%s reason=%s", rel_path, exc)
        return digest

    def close(self) -> None:
        if self.connection is None:
            return
        try:
            self.connection.commit()
        except sqlite3.Error as exc:
            logger.warning("hash cache commit failed reason=%s", exc)
        finally:
            self.connection.close()


def _relative_unix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _scan_firmware_specs(
    data_root: Path, system: str, required_filenames: tuple[str, ...], hash_cache: _HashCache
) -> tuple[tuple[FirmwareSpec, ...], tuple[str, ...]]:
    firmware_specs: list[FirmwareSpec] = []
    firmware_dir = data_root / FIRMWARE_ROOT_NAME / system
    if firmware_dir.exists() and not firmware_dir.is_dir():
        raise ValueError(f"Firmware path is not a directory: {firmware_dir}")

    found_required: set[str] = set()
    required_lookup = {name.casefold(): name for name in required_filenames}
    required_set = set(required_lookup.values())
    if firmware_dir.is_dir():
        for child in sorted(firmware_dir.iterdir(), key=lambda item: item.name.lower()):
            if not child.is_file():
                continue
            required_name = required_lookup.get(child.name.casefold())
            is_required = required_name is not None
            if required_name is not None:
                found_required.add(required_name)
            child_stat = child.stat()
            child_rel = _relative_unix(child, data_root)
            firmware_specs.append(
                FirmwareSpec(
                    filename=child.name,
                    sha256=hash_cache.get_sha256(
                        child,
                        child_rel,
                        size_bytes=child_stat.st_size,
                        mtime_ns=child_stat.st_mtime_ns,
                    ),
                    required=is_required,
                )
            )

    missing_required = tuple(sorted(required_set - found_required))
    return tuple(firmware_specs), missing_required


def build_index(data_root: Path) -> IndexBundle:
    roms_root = data_root / ROMS_ROOT_NAME
    if not roms_root.exists():
        return IndexBundle(index=LibraryIndex(), file_paths={}, asset_paths={})

    hash_cache = _HashCache.open(data_root)
    systems: list[SystemSpec] = []
    titles: list[TitleEntry] = []
    file_paths: dict[str, Path] = {}
    asset_paths: dict[str, Path] = {}
    try:
        for system_name in sorted(SYSTEM_CATALOG):
            system_dir = roms_root / system_name
            if not system_dir.exists():
                continue
            if not system_dir.is_dir():
                raise ValueError(f"System path is not a directory: {system_dir}")

            metadata = SYSTEM_CATALOG[system_name]
            extensions = tuple(ext.lower() for ext in metadata["extensions"])
            if metadata.get("scan_firmware", True):
                firmware_specs, missing_required_firmware = _scan_firmware_specs(
                    data_root, system_name, tuple(metadata["firmware"]), hash_cache
                )
            else:
                firmware_specs = ()
                missing_required_firmware = ()
            system_titles: list[TitleEntry] = []
            seen_title_names: set[str] = set()

            for rom_path in sorted(system_dir.iterdir(), key=lambda item: item.name.lower()):
                if rom_path.is_dir():
                    raise ValueError(
                        f"Unexpected title directory in {system_dir}: {rom_path.name}. "
                        "Expected layout roms/<system>/<title.ext>"
                    )
                if not rom_path.is_file():
                    continue
                if rom_path.suffix.lower() not in extensions:
                    continue

                title_name = rom_path.stem
                title_key = title_name.casefold()
                if title_key in seen_title_names:
                    raise ValueError(
                        f"Duplicate title name in {system_name}: {title_name}. "
                        "Ensure one ROM per title stem in roms/<system>/."
                    )
                seen_title_names.add(title_key)

                rom_rel = _relative_unix(rom_path, data_root)
                rom_stat = rom_path.stat()
                rom_sha = hash_cache.get_sha256(
                    rom_path,
                    rom_rel,
                    size_bytes=rom_stat.st_size,
                    mtime_ns=rom_stat.st_mtime_ns,
                )
                file_id = make_file_id(rom_rel, rom_sha)
                file_paths[file_id] = rom_path

                title_rel_dir = _relative_unix(rom_path, roms_root)
                title_id = make_title_id(system_name, title_rel_dir)

                system_titles.append(
                    TitleEntry(
                        title_id=title_id,
                        system=system_name,
                        title_name=title_name,
                        title_rel_dir=title_rel_dir,
                        emulator=metadata["emulator"],
                        launch_template=metadata["launch_template"],
                        rom=RomSpec(
                            file_id=file_id,
                            rel_path=rom_rel,
                            sha256=rom_sha,
                            size_bytes=rom_stat.st_size,
                            extension=rom_path.suffix.lower(),
                        ),
                        assets=(),
                    ),
                )

            if system_titles and missing_required_firmware:
                missing = ", ".join(missing_required_firmware)
                raise ValueError(f"Missing required firmware for {system_name}: {missing}")

            systems.append(
                SystemSpec(
                    name=system_name,
                    rom_extensions=extensions,
                    default_emulator=metadata["emulator"],
                    launch_template=metadata["launch_template"],
                    firmware=firmware_specs,
                )
            )
            titles.extend(system_titles)

        index = LibraryIndex(
            index_version=1,
            systems=tuple(sorted(systems, key=lambda item: item.name)),
            titles=tuple(sorted(titles, key=lambda item: (item.system, item.title_rel_dir))),
        )
        return IndexBundle(index=index, file_paths=file_paths, asset_paths=asset_paths)
    finally:
        hash_cache.close()
