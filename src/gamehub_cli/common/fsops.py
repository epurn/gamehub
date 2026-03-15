from __future__ import annotations

import errno
import os
import re
import shutil
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_BACKUP_KEEP_LIMIT = 3
_GAMEHUB_BACKUP_NAME_RE = re.compile(r"^(?P<original_name>.+)\.(?P<stamp>\d{14})(?:\.(?P<collision>\d+))?\.bak$")


@dataclass(frozen=True)
class BackupFilename:
    original_name: str
    stamp: str
    collision: int


@dataclass(frozen=True)
class BackupResult:
    created_path: Path | None
    pruned_paths: tuple[Path, ...] = ()


def _should_fallback_replace(exc: OSError) -> bool:
    if isinstance(exc, PermissionError):
        return True
    if exc.errno == errno.EXDEV:
        return True
    # Windows may surface cross-device rename failures as winerror 17.
    if getattr(exc, "winerror", None) == 17:
        return True
    return False


def replace_file(source: Path, destination: Path) -> None:
    try:
        source.replace(destination)
        return
    except OSError as exc:
        if not _should_fallback_replace(exc):
            raise
        # Some restricted filesystems deny rename/replace operations.
        with source.open("rb") as src, destination.open("wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        try:
            source.unlink(missing_ok=True)
        except OSError:
            # Best effort cleanup only; destination content has been safely written.
            with source.open("wb") as handle:
                handle.truncate(0)
                handle.flush()
                os.fsync(handle.fileno())


def parse_gamehub_backup_name(filename: str) -> BackupFilename | None:
    matched = _GAMEHUB_BACKUP_NAME_RE.match(filename)
    if matched is None:
        return None
    collision = matched.group("collision")
    return BackupFilename(
        original_name=matched.group("original_name"),
        stamp=matched.group("stamp"),
        collision=int(collision) if collision is not None else 0,
    )


def sort_gamehub_backups(paths: Iterable[Path]) -> tuple[Path, ...]:
    ordered: list[tuple[str, int, str, Path]] = []
    for path in paths:
        parsed = parse_gamehub_backup_name(path.name)
        if parsed is None:
            continue
        ordered.append((parsed.stamp, parsed.collision, path.name.casefold(), path))
    ordered.sort(reverse=True)
    return tuple(item[-1] for item in ordered)


def stale_gamehub_backups(paths: Iterable[Path], *, keep_limit: int) -> tuple[Path, ...]:
    if keep_limit < 0:
        raise ValueError(f"keep_limit must be >= 0 (got {keep_limit})")
    ordered = sort_gamehub_backups(paths)
    return ordered[keep_limit:]


def iter_gamehub_backup_families(root: Path) -> Iterator[tuple[Path, str, tuple[Path, ...]]]:
    if not root.exists() or not root.is_dir():
        return

    groups: dict[tuple[Path, str], list[Path]] = {}
    for candidate in root.rglob("*.bak"):
        if not candidate.is_file():
            continue
        parsed = parse_gamehub_backup_name(candidate.name)
        if parsed is None:
            continue
        groups.setdefault((candidate.parent, parsed.original_name), []).append(candidate)

    for (directory, original_name), paths in sorted(
        groups.items(),
        key=lambda item: (str(item[0][0]).casefold(), item[0][1].casefold()),
    ):
        yield directory, original_name, sort_gamehub_backups(paths)


def prune_backup_family(directory: Path, original_name: str, *, keep_limit: int) -> tuple[Path, ...]:
    if keep_limit < 0:
        raise ValueError(f"keep_limit must be >= 0 (got {keep_limit})")
    if not directory.exists() or not directory.is_dir():
        return ()

    family_paths: list[Path] = []
    for candidate in directory.iterdir():
        if not candidate.is_file() or not candidate.name.endswith(".bak"):
            continue
        parsed = parse_gamehub_backup_name(candidate.name)
        if parsed is None or parsed.original_name != original_name:
            continue
        family_paths.append(candidate)

    pruned = stale_gamehub_backups(family_paths, keep_limit=keep_limit)
    for candidate in pruned:
        candidate.unlink(missing_ok=True)
    return pruned


def backup_existing_file(path: Path, *, keep_limit: int = DEFAULT_BACKUP_KEEP_LIMIT) -> BackupResult:
    if not path.exists() or not path.is_file():
        return BackupResult(created_path=None)
    if keep_limit < 1:
        raise ValueError(f"keep_limit must be >= 1 (got {keep_limit})")

    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    candidate = path.with_name(f"{path.name}.{stamp}.bak")
    suffix = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.{stamp}.{suffix}.bak")
        suffix += 1

    shutil.copy2(path, candidate)
    pruned = prune_backup_family(candidate.parent, path.name, keep_limit=keep_limit)
    return BackupResult(created_path=candidate, pruned_paths=pruned)
