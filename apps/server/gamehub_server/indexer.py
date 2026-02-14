from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gamehub_common.ids import make_file_id, make_title_id, sha256_file
from gamehub_common.models import FirmwareSpec, LibraryIndex, RomSpec, SystemSpec, TitleEntry

FIRMWARE_ROOT_NAME = "firmware"
ROMS_ROOT_NAME = "roms"

SYSTEM_CATALOG = {
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
        "extensions": (".iso", ".gcm", ".rvz"),
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
        "extensions": (".iso", ".wbfs", ".rvz"),
        "emulator": "dolphin",
        "launch_template": '"{emulator}" -b -e "{rom}"',
        "firmware": ("keys.bin",),
    },
}


@dataclass(frozen=True)
class IndexBundle:
    index: LibraryIndex
    file_paths: dict[str, Path]
    asset_paths: dict[str, Path]


def _relative_unix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _scan_firmware_specs(
    data_root: Path, system: str, required_filenames: tuple[str, ...]
) -> tuple[tuple[FirmwareSpec, ...], tuple[str, ...]]:
    firmware_specs: list[FirmwareSpec] = []
    firmware_dir = data_root / FIRMWARE_ROOT_NAME / system
    if firmware_dir.exists() and not firmware_dir.is_dir():
        raise ValueError(f"Firmware path is not a directory: {firmware_dir}")

    found_required: set[str] = set()
    required_set = set(required_filenames)
    if firmware_dir.is_dir():
        for child in sorted(firmware_dir.iterdir(), key=lambda item: item.name.lower()):
            if not child.is_file():
                continue
            is_required = child.name in required_set
            if is_required:
                found_required.add(child.name)
            firmware_specs.append(
                FirmwareSpec(
                    filename=child.name,
                    sha256=sha256_file(child),
                    required=is_required,
                )
            )

    missing_required = tuple(sorted(required_set - found_required))
    return tuple(firmware_specs), missing_required


def build_index(data_root: Path) -> IndexBundle:
    roms_root = data_root / ROMS_ROOT_NAME
    if not roms_root.exists():
        return IndexBundle(index=LibraryIndex(), file_paths={}, asset_paths={})

    systems: list[SystemSpec] = []
    titles: list[TitleEntry] = []
    file_paths: dict[str, Path] = {}
    asset_paths: dict[str, Path] = {}

    for system_name in sorted(SYSTEM_CATALOG):
        system_dir = roms_root / system_name
        if not system_dir.exists():
            continue
        if not system_dir.is_dir():
            raise ValueError(f"System path is not a directory: {system_dir}")

        metadata = SYSTEM_CATALOG[system_name]
        extensions = tuple(ext.lower() for ext in metadata["extensions"])
        firmware_specs, missing_required_firmware = _scan_firmware_specs(
            data_root, system_name, tuple(metadata["firmware"])
        )
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
            rom_sha = sha256_file(rom_path)
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
                        size_bytes=rom_path.stat().st_size,
                        extension=rom_path.suffix.lower(),
                    ),
                    assets=(),
                )
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
