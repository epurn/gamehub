from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from .shortcuts import _canonical_unsigned_app_id
from .types import SteamArtworkAssignment, SteamContext


def backup_steam_configs(context: SteamContext) -> list[Path]:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backups: list[Path] = []
    sources: list[Path] = [context.shortcuts_path, context.localconfig_path]
    if context.cloudstorage_path is not None:
        sources.append(context.cloudstorage_path)
    for source in sources:
        if not source.exists():
            continue
        destination = source.with_name(f"{source.name}.{timestamp}.bak")
        shutil.copy2(source, destination)
        backups.append(destination)
    return backups


def copy_grid_art(context: SteamContext, assignments: list[SteamArtworkAssignment]) -> list[Path]:
    copied_files: list[Path] = []
    if not assignments:
        return copied_files

    grid_dir = context.userdata_dir / context.steam_id / "config" / "grid"
    grid_dir.mkdir(parents=True, exist_ok=True)
    suffixes_by_kind = {"hero": "_hero", "logo": "_logo", "icon": "_icon"}

    for assignment in assignments:
        app_id = _canonical_unsigned_app_id(assignment.steam_app_id)
        if not app_id:
            continue
        # Prefer a dedicated landscape asset when available; otherwise reuse portrait grid.
        grid_portrait = assignment.assets_by_kind.get("grid")
        grid_landscape = assignment.assets_by_kind.get("grid_landscape")
        if grid_portrait is not None and grid_portrait.exists():
            portrait_destination = grid_dir / f"{app_id}p{grid_portrait.suffix.lower() or '.png'}"
            shutil.copy2(grid_portrait, portrait_destination)
            copied_files.append(portrait_destination)
        landscape_source = grid_landscape if grid_landscape is not None and grid_landscape.exists() else grid_portrait
        if landscape_source is not None and landscape_source.exists():
            landscape_destination = grid_dir / f"{app_id}{landscape_source.suffix.lower() or '.png'}"
            shutil.copy2(landscape_source, landscape_destination)
            copied_files.append(landscape_destination)
        for kind, source in assignment.assets_by_kind.items():
            if kind not in suffixes_by_kind:
                continue
            if not source.exists():
                continue
            raw_suffixes = suffixes_by_kind[kind]
            suffixes = raw_suffixes if isinstance(raw_suffixes, tuple) else (raw_suffixes,)
            for suffix in suffixes:
                destination = grid_dir / f"{app_id}{suffix}{source.suffix.lower() or '.png'}"
                shutil.copy2(source, destination)
                copied_files.append(destination)
    return copied_files


def prune_grid_noncanonical_variants(context: SteamContext, steam_app_ids: list[str]) -> int:
    del context, steam_app_ids
    return 0
