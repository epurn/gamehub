from __future__ import annotations

from pathlib import Path, PurePosixPath


def _normalized_posix_parts(rel_path: str) -> tuple[str, ...]:
    rel = PurePosixPath(rel_path)
    return tuple(part for part in rel.parts if part not in {"", "."})


def from_rel_path(base: Path, rel_path: str, *, preferred_root: str | None = None) -> Path:
    parts = _normalized_posix_parts(rel_path)
    if preferred_root is None:
        return base.joinpath(*parts)

    preferred = preferred_root.strip().strip("/\\")
    if not preferred:
        return base.joinpath(*parts)

    preferred_folded = preferred.casefold()
    if parts and parts[0].casefold() == preferred_folded:
        canonical = base.joinpath(*parts)
        legacy = base.joinpath(*parts[1:])
    else:
        canonical = base.joinpath(preferred, *parts)
        legacy = base.joinpath(*parts)

    if canonical.exists():
        return canonical
    if legacy.exists():
        return legacy
    return canonical


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
        try:
            return from_rel_path(library_dir, rel_path, preferred_root="roms")
        except TypeError:
            # Compatibility for patched resolvers in tests/extensions that still use the old 2-arg signature.
            return from_rel_path(library_dir, rel_path)

    normalized_rel = strip_rel_path_root(rel_path, "roms")
    return from_rel_path(roms_dir, normalized_rel)
