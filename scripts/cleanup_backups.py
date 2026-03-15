from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from gamehub_cli.common.config import GamehubConfig, load_config
from gamehub_cli.common.fsops import (
    DEFAULT_BACKUP_KEEP_LIMIT,
    iter_gamehub_backup_families,
    stale_gamehub_backups,
)
from gamehub_cli.common.shortcut_payload_registry import shortcut_payload_registry_path
from gamehub_cli.controllers.profiles import resolve_profiles_root
from gamehub_cli.firmware.runtime_azahar import default_azahar_qt_config_path
from gamehub_cli.firmware.targets import (
    default_pcsx2_ini_path,
    resolve_dolphin_user_dirs,
    retroarch_cfg_candidates_for_config,
)
from gamehub_cli.steam import build_context, discover_steam_id, discover_userdata_dir


@dataclass
class CleanupSummary:
    families: int = 0
    stale_backups: int = 0
    deleted: int = 0
    errors: int = 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prune legacy GAMEHUB backup files down to the configured keep limit.")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional path to config.toml. Defaults to standard config resolution.",
    )
    parser.add_argument(
        "--root",
        action="append",
        type=Path,
        default=[],
        help="Additional filesystem root to scan for GAMEHUB backups. May be repeated.",
    )
    parser.add_argument(
        "--server-data-root",
        type=Path,
        default=None,
        help="Optional GAMEHUB server data root (or saves/ root) to scan for server save backups.",
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=None,
        help=f"How many backups to keep per file family. Defaults to config/env, otherwise {DEFAULT_BACKUP_KEEP_LIMIT}.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete stale backups. Without this flag the script only reports what it would remove.",
    )
    return parser.parse_args()


def _unique_paths(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in paths:
        resolved = candidate.expanduser().resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def _steam_config_root(config: GamehubConfig) -> Path | None:
    userdata_dir = discover_userdata_dir(config.steam_userdata_dir)
    if userdata_dir is None:
        return None
    steam_id = discover_steam_id(userdata_dir, preferred_steam_id=config.steam_id)
    if steam_id is None:
        return None
    return build_context(userdata_dir, steam_id, config.steam_exe).shortcuts_path.parent


def _retroarch_roots(config: GamehubConfig) -> list[Path]:
    roots: list[Path] = []
    for cfg_path in retroarch_cfg_candidates_for_config(config=config):
        roots.append(cfg_path.parent)
        if cfg_path.parent.name.casefold() == "config":
            roots.append(cfg_path.parent.parent)
    return roots


def _pcsx2_roots(config: GamehubConfig) -> list[Path]:
    ini_path = default_pcsx2_ini_path(config=config)
    roots = [ini_path.parent]
    if ini_path.parent.name.casefold() == "inis":
        roots.append(ini_path.parent.parent)
    return roots


def _azahar_roots(config: GamehubConfig) -> list[Path]:
    ini_path = default_azahar_qt_config_path(config=config)
    roots = [ini_path.parent]
    if ini_path.parent.name.casefold() == "config":
        roots.append(ini_path.parent.parent)
    return roots


def _discover_client_roots(config: GamehubConfig) -> list[Path]:
    roots = [
        config.library_dir,
        config.state_path.parent,
        resolve_profiles_root(config),
        shortcut_payload_registry_path(config.state_path).parent,
        *_retroarch_roots(config),
        *_pcsx2_roots(config),
        *_azahar_roots(config),
        *resolve_dolphin_user_dirs(config=config),
    ]
    steam_root = _steam_config_root(config)
    if steam_root is not None:
        roots.append(steam_root)
    return _unique_paths(roots)


def _server_scan_root(server_data_root: Path) -> Path:
    expanded = server_data_root.expanduser().resolve(strict=False)
    saves_root = expanded / "saves"
    if saves_root.exists():
        return saves_root
    return expanded


def _collect_grouped_backups(
    roots: list[Path],
) -> tuple[dict[tuple[Path, str], list[Path]], dict[Path, Path]]:
    grouped: dict[tuple[Path, str], list[Path]] = {}
    owning_root_by_backup: dict[Path, Path] = {}
    seen_backups: set[Path] = set()

    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for directory, original_name, backups in iter_gamehub_backup_families(root):
            for backup_path in backups:
                resolved = backup_path.resolve(strict=False)
                if resolved in seen_backups:
                    continue
                seen_backups.add(resolved)
                grouped.setdefault((directory.resolve(strict=False), original_name), []).append(resolved)
                owning_root_by_backup[resolved] = root
    return grouped, owning_root_by_backup


def _resolved_keep_limit(args_keep: int | None, config: GamehubConfig) -> int:
    keep_limit = config.backups.keep_limit if args_keep is None else args_keep
    if keep_limit < 0:
        raise ValueError("--keep must be >= 0")
    return keep_limit


def _print_root_summary(root: Path, summary: CleanupSummary, *, apply: bool) -> None:
    action = "deleted" if apply else "would_delete"
    print(
        "backup-cleanup\troot-summary\t"
        f"root={root}\tfamilies={summary.families}\tstale_backups={summary.stale_backups}\t"
        f"{action}={summary.deleted}\terrors={summary.errors}"
    )


def main() -> int:
    args = _parse_args()
    try:
        config = load_config(args.config)
        keep_limit = _resolved_keep_limit(args.keep, config)
    except Exception as exc:  # noqa: BLE001
        print(f"backup cleanup configuration error: {exc}", file=sys.stderr)
        return 1

    roots = _discover_client_roots(config)
    roots.extend(root.expanduser() for root in args.root)
    if args.server_data_root is not None:
        roots.append(_server_scan_root(args.server_data_root))
    roots = _unique_paths(roots)
    if not roots:
        print("backup cleanup could not resolve any scan roots", file=sys.stderr)
        return 1

    mode = "apply" if args.apply else "dry-run"
    print(f"backup-cleanup\tstart\tmode={mode}\tkeep={keep_limit}")

    root_summaries: dict[Path, CleanupSummary] = {root: CleanupSummary() for root in roots}
    for root in roots:
        if not root.exists() or not root.is_dir():
            print(f"backup-cleanup\troot-skip\troot={root}\treason=missing")

    grouped_backups, owning_root_by_backup = _collect_grouped_backups(roots)

    for (directory, original_name), backups in sorted(
        grouped_backups.items(),
        key=lambda item: (str(item[0][0]).casefold(), item[0][1].casefold()),
    ):
        stale_paths = stale_gamehub_backups(backups, keep_limit=keep_limit)
        if not stale_paths:
            continue
        owner_root = owning_root_by_backup[backups[0]]
        summary = root_summaries[owner_root]
        summary.families += 1
        summary.stale_backups += len(stale_paths)
        family_label = directory / original_name
        for stale_path in stale_paths:
            action = "delete" if args.apply else "would-delete"
            print(f"backup-cleanup\t{action}\troot={owner_root}\tfamily={family_label}\tpath={stale_path}")
            if not args.apply:
                continue
            try:
                stale_path.unlink(missing_ok=True)
                summary.deleted += 1
            except OSError as exc:
                summary.errors += 1
                print(
                    f"backup-cleanup\terror\troot={owner_root}\tpath={stale_path}\tdetail={exc}",
                    file=sys.stderr,
                )

    total = CleanupSummary()
    for root in roots:
        summary = root_summaries[root]
        _print_root_summary(root, summary, apply=args.apply)
        total.families += summary.families
        total.stale_backups += summary.stale_backups
        total.deleted += summary.deleted
        total.errors += summary.errors

    deleted_label = "deleted" if args.apply else "would_delete"
    print(
        "backup-cleanup\tsummary\t"
        f"roots={len(roots)}\tfamilies={total.families}\tstale_backups={total.stale_backups}\t"
        f"{deleted_label}={total.deleted}\terrors={total.errors}"
    )
    return 1 if total.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
