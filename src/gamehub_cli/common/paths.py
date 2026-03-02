from __future__ import annotations

import re
from pathlib import Path, PurePosixPath


def _normalized_posix_parts(rel_path: str) -> tuple[str, ...]:
    rel = PurePosixPath(rel_path)
    return tuple(part for part in rel.parts if part not in {"", "."})


def normalized_local_path(value: str | Path) -> Path:
    raw = str(value).strip().strip('"')
    if not raw:
        return Path()

    normalized_raw = raw.replace("\\", "/")
    drive_match = re.match(r"^([A-Za-z]:)/(.*)$", normalized_raw)
    if drive_match is not None:
        drive = drive_match.group(1)
        remainder = drive_match.group(2)
        posix = PurePosixPath(remainder)
        parts = tuple(part for part in posix.parts if part not in {"", "."})
        if not parts:
            return Path(f"{drive}/")
        return Path(f"{drive}/", *parts)

    posix = PurePosixPath(normalized_raw)
    parts = tuple(part for part in posix.parts if part not in {"", "."})
    if not parts:
        return Path()
    return Path(*parts)


def from_rel_path(base: Path, rel_path: str, *, preferred_root: str | None = None) -> Path:
    parts = _normalized_posix_parts(rel_path)
    if preferred_root is None:
        return base.joinpath(*parts)

    preferred = preferred_root.strip().strip("/\\")
    if not preferred:
        return base.joinpath(*parts)

    preferred_folded = preferred.casefold()
    if parts and parts[0].casefold() == preferred_folded:
        return base.joinpath(*parts)
    return base.joinpath(preferred, *parts)


def strip_rel_path_root(rel_path: str, root: str) -> str:
    parts = _normalized_posix_parts(rel_path)
    normalized_root = root.strip().strip("/\\").casefold()
    if not normalized_root:
        return "/".join(parts)
    if parts and parts[0].casefold() == normalized_root:
        return "/".join(parts[1:])
    return "/".join(parts)


def resolve_rom_destination(*, library_dir: Path, roms_dir: Path | None, rel_path: str) -> Path:
    if roms_dir is None:
        return from_rel_path(library_dir, rel_path, preferred_root="roms")

    normalized_rel = strip_rel_path_root(rel_path, "roms")
    return from_rel_path(roms_dir, normalized_rel)
