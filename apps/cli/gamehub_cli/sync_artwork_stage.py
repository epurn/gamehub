from __future__ import annotations

from pathlib import Path

from gamehub_common.models import LibraryIndex

from .artwork import (
    SGDB_ART_KINDS,
    SgdbArtworkPipeline,
    SgdbClient,
    build_lookup_plan,
    redact_secret,
)
from .config import GamehubConfig


def kinds_to_download(kinds: tuple[str, ...]) -> str:
    return ",".join(kinds)


def build_artwork_assignments(
    config: GamehubConfig,
    index: LibraryIndex,
    dry_run: bool,
    timeout_seconds: float,
    verbose: bool,
) -> dict[str, dict[str, Path]]:
    def _from_cache() -> dict[str, dict[str, Path]]:
        cached: dict[str, dict[str, Path]] = {}
        for title in index.titles:
            title_dir = config.sgdb_cache_dir / title.title_id
            if not title_dir.is_dir():
                continue
            files: dict[str, Path] = {}
            for kind in SGDB_ART_KINDS:
                candidates = sorted(
                    (path for path in title_dir.glob(f"{kind}-*") if path.is_file() and path.stat().st_size > 0),
                    key=lambda item: item.stat().st_mtime,
                    reverse=True,
                )
                if candidates:
                    files[kind] = candidates[0]
            if files:
                cached[title.title_id] = files
        return cached

    if not config.sgdb_api_key:
        cached_only = _from_cache()
        if cached_only:
            print(f"SGDB API key missing; using cached artwork for {len(cached_only)} titles")
            return cached_only
        if verbose:
            print("SGDB artwork disabled (no API key configured)")
        return {}

    enabled_kinds = tuple(kind for kind in config.sgdb_enabled_kinds if kind in SGDB_ART_KINDS)
    if not enabled_kinds:
        print("SGDB artwork disabled (no valid artwork kinds configured)")
        return {}

    if dry_run:
        dry_run_plan = build_lookup_plan(index.titles, enabled_kinds)
        print(
            f"SGDB dry-run: key={redact_secret(config.sgdb_api_key)} "
            f"titles={len(dry_run_plan)} kinds={','.join(enabled_kinds)}"
        )
        for entry in dry_run_plan:
            print(f"sgdb\tlookup\t{entry.title_name}\t{kinds_to_download(entry.kinds)}")
        return {}

    print(f"Starting SGDB artwork sync for {len(index.titles)} titles")

    def _progress_lookup(position: int, total: int, title_name: str) -> None:
        if verbose:
            print(f"sgdb\tlookup\t{position}/{total}\t{title_name}")

    with SgdbClient(config.sgdb_api_key, timeout_seconds=timeout_seconds) as client:
        pipeline = SgdbArtworkPipeline(client, cache_dir=config.sgdb_cache_dir, kinds=enabled_kinds)
        result = pipeline.sync(index.titles, progress_cb=_progress_lookup)

    if result.warnings:
        for warning in result.warnings:
            print(f"Warning: {warning}")
    print(f"SGDB artwork: lookups={result.lookups} downloaded={result.downloaded} cached={result.cached}")

    assignments: dict[str, dict[str, Path]] = {}
    for bundle in result.bundles:
        assignments[bundle.title_id] = bundle.files
    cache_fallback = _from_cache()
    fallback_count = 0
    for title_id, files in cache_fallback.items():
        if title_id in assignments:
            continue
        assignments[title_id] = files
        fallback_count += 1
    if fallback_count and verbose:
        print(f"SGDB cache fallback restored artwork for {fallback_count} titles")
    return assignments
