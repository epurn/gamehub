from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gamehub_common.ids import make_asset_id, make_file_id, make_title_id, sha256_file
from gamehub_common.models import AssetSpec, FirmwareSpec, LibraryIndex, RomSpec, SystemSpec, TitleEntry

ASSET_KINDS = ("grid", "hero", "logo", "icon")
FIRMWARE_ROOT_NAME = "firmware"
ROMS_ROOT_NAME = "roms"

SYSTEM_CATALOG = {
    "NES": {
        "extensions": (".nes", ".zip"),
        "emulator": "retroarch",
        "launch_template": '"{emulator}" -L cores/fceumm_libretro.dll "{rom}"',
        "firmware": (),
    },
    "SNES": {
        "extensions": (".sfc", ".smc", ".zip"),
        "emulator": "retroarch",
        "launch_template": '"{emulator}" -L cores/snes9x_libretro.dll "{rom}"',
        "firmware": (),
    },
    "N64": {
        "extensions": (".n64", ".z64", ".v64", ".zip"),
        "emulator": "retroarch",
        "launch_template": '"{emulator}" -L cores/mupen64plus_next_libretro.dll "{rom}"',
        "firmware": (),
    },
    "PS1": {
        "extensions": (".chd", ".cue", ".iso", ".pbp"),
        "emulator": "retroarch",
        "launch_template": '"{emulator}" -L cores/swanstation_libretro.dll "{rom}"',
        "firmware": ("scph5501.bin",),
    },
    "PS2": {
        "extensions": (".iso", ".chd"),
        "emulator": "pcsx2",
        "launch_template": '"{emulator}" --fullscreen "{rom}"',
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


def _scan_firmware_specs(data_root: Path, system: str, filenames: tuple[str, ...]) -> tuple[FirmwareSpec, ...]:
    firmware_specs: list[FirmwareSpec] = []
    firmware_dir = data_root / FIRMWARE_ROOT_NAME / system
    for filename in sorted(filenames):
        fw_path = firmware_dir / filename
        if not fw_path.exists():
            continue
        firmware_specs.append(
            FirmwareSpec(
                filename=filename,
                sha256=sha256_file(fw_path),
                required=True,
            )
        )
    return tuple(firmware_specs)


def _find_assets(data_root: Path, title_dir: Path) -> tuple[tuple[AssetSpec, ...], dict[str, Path]]:
    asset_specs: list[AssetSpec] = []
    asset_paths: dict[str, Path] = {}
    by_kind: dict[str, list[Path]] = {kind: [] for kind in ASSET_KINDS}
    for child in sorted(title_dir.iterdir()):
        if not child.is_file():
            continue
        stem = child.stem.lower()
        if stem in by_kind:
            by_kind[stem].append(child)

    for kind in ASSET_KINDS:
        matches = by_kind[kind]
        if len(matches) > 1:
            raise ValueError(f"Title directory {title_dir} has multiple '{kind}' assets")
        if not matches:
            continue
        path = matches[0]
        rel_path = _relative_unix(path, data_root)
        digest = sha256_file(path)
        asset_id = make_asset_id(rel_path, digest)
        asset_specs.append(
            AssetSpec(
                asset_id=asset_id,
                kind=kind,
                rel_path=rel_path,
                sha256=digest,
                size_bytes=path.stat().st_size,
            )
        )
        asset_paths[asset_id] = path

    return tuple(asset_specs), asset_paths


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
        firmware_specs = _scan_firmware_specs(data_root, system_name, tuple(metadata["firmware"]))
        systems.append(
            SystemSpec(
                name=system_name,
                rom_extensions=extensions,
                default_emulator=metadata["emulator"],
                launch_template=metadata["launch_template"],
                firmware=firmware_specs,
            )
        )

        for title_dir in sorted(system_dir.iterdir()):
            if not title_dir.is_dir():
                continue
            rom_candidates = [
                candidate
                for candidate in sorted(title_dir.iterdir())
                if candidate.is_file() and candidate.suffix.lower() in extensions
            ]
            if len(rom_candidates) != 1:
                raise ValueError(
                    f"Expected exactly one ROM in {title_dir}, found {len(rom_candidates)} "
                    f"for extensions {extensions}"
                )

            rom_path = rom_candidates[0]
            rom_rel = _relative_unix(rom_path, data_root)
            rom_sha = sha256_file(rom_path)
            file_id = make_file_id(rom_rel, rom_sha)
            file_paths[file_id] = rom_path

            title_rel_dir = _relative_unix(title_dir, roms_root)
            title_id = make_title_id(system_name, title_rel_dir)
            title_assets, title_asset_paths = _find_assets(data_root, title_dir)
            asset_paths.update(title_asset_paths)

            titles.append(
                TitleEntry(
                    title_id=title_id,
                    system=system_name,
                    title_name=title_dir.name,
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
                    assets=title_assets,
                )
            )

    index = LibraryIndex(
        index_version=1,
        systems=tuple(sorted(systems, key=lambda item: item.name)),
        titles=tuple(sorted(titles, key=lambda item: (item.system, item.title_name))),
    )
    return IndexBundle(index=index, file_paths=file_paths, asset_paths=asset_paths)
