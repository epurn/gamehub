from __future__ import annotations

from pathlib import Path

from .roots import path_identity

_DECK_TEMPLATE_LEGACY_AUTOCLOUD_FILENAME = "steam_autocloud.vdf"


def _legacy_steam_autocloud_paths(root: Path) -> list[Path]:
    candidates = [root / _DECK_TEMPLATE_LEGACY_AUTOCLOUD_FILENAME]
    if root.name.casefold() != "config":
        candidates.append(root / "config" / _DECK_TEMPLATE_LEGACY_AUTOCLOUD_FILENAME)
    unique: list[Path] = []
    seen: set[tuple[str, int, int] | tuple[str, str]] = set()
    for path in candidates:
        identity = path_identity(path)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(path)
    return unique


def cleanup_legacy_steam_autocloud_files(*, root: Path) -> None:
    for candidate in _legacy_steam_autocloud_paths(root):
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            candidate.unlink()
        except OSError as exc:
            raise RuntimeError(
                f"Steam Deck template sync failed: failed removing legacy steam autocloud config ({candidate}): {exc}"
            ) from exc
