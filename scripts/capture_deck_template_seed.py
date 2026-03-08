from __future__ import annotations

import argparse
from pathlib import Path

from gamehub_cli.common.config import load_config
from gamehub_cli.steam import (
    discover_deck_steam_input_roots,
    normalize_steam_input_title_dir,
)
from gamehub_cli.steam.io import _atomic_write_bytes
from gamehub_cli.steam.lifecycle import discover_steam_id, discover_userdata_dir

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WII_CONTROLLER_FILE = "wii_0.vdf"
_N3DS_CONTROLLER_FILE = "3ds_0.vdf"
_WII_GAMEHUB_FILE = "gamehub_wii.vdf"
_N3DS_GAMEHUB_FILE = "gamehub_3ds.vdf"
_SYSTEM_TO_SEED_PATH = {
    "wii_gc": _REPO_ROOT
    / "src"
    / "gamehub_cli"
    / "steam"
    / "template_seeds"
    / "steamdeck"
    / "wii_gc"
    / _WII_CONTROLLER_FILE,
    "n3ds": _REPO_ROOT
    / "src"
    / "gamehub_cli"
    / "steam"
    / "template_seeds"
    / "steamdeck"
    / "n3ds"
    / _N3DS_CONTROLLER_FILE,
}
_SYSTEM_TO_SOURCE_FILES = {
    "wii_gc": (_WII_GAMEHUB_FILE, _WII_CONTROLLER_FILE),
    "n3ds": (_N3DS_GAMEHUB_FILE, _N3DS_CONTROLLER_FILE),
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture a Steam Deck per-title controller template file into GAMEHUB repo seed files."
    )
    parser.add_argument(
        "--system",
        required=True,
        choices=sorted(_SYSTEM_TO_SEED_PATH),
        help="Seed target group to update: wii_gc or n3ds",
    )
    parser.add_argument(
        "--title",
        required=True,
        help="GAMEHUB Steam shortcut title with the desired Steam Input template applied",
    )
    parser.add_argument(
        "--steam-id",
        default=None,
        help="Optional Steam userdata id or SteamID64 to target. Defaults to config + auto discovery.",
    )
    parser.add_argument(
        "--controller-file",
        default=None,
        help=(
            "Optional controller VDF filename inside the title directory "
            "(allowed: gamehub_wii.vdf, gamehub_3ds.vdf, wii_0.vdf, 3ds_0.vdf). "
            "When omitted, GAMEHUB checks expected files for --system in priority order."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.toml"),
        help="Path to GAMEHUB config.toml (default: ./config.toml)",
    )
    return parser.parse_args()


def _resolve_existing_template_root(steam_id: str) -> Path:
    candidates = discover_deck_steam_input_roots(steam_id)
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate
    tried = ", ".join(str(path) for path in candidates) or "<none>"
    raise RuntimeError(f"No Steam Controller Configs root found for steam_id={steam_id} (tried: {tried})")


def _resolve_title_controller_template(
    template_root: Path,
    *,
    title: str,
    expected_files: tuple[str, ...],
) -> Path:
    title_dir = template_root / normalize_steam_input_title_dir(title)
    if not title_dir.exists() or not title_dir.is_dir():
        raise RuntimeError(
            "Title template directory not found. "
            f"Expected: {title_dir}. Save a per-game Steam Input layout for this title first."
        )

    if not expected_files:
        raise RuntimeError(f"Expected controller file list is empty for title directory: {title_dir}")
    for expected_file in expected_files:
        target = title_dir / expected_file
        if target.exists():
            return target
    available = sorted(path.name for path in title_dir.glob("*.vdf"))
    raise RuntimeError(
        f"Required controller file not found for title: {title_dir}. "
        f"Tried: {list(expected_files)}. Available in title dir: {available if available else '<none>'}"
    )


def main() -> int:
    args = _parse_args()
    config_path: Path = args.config.expanduser().resolve()
    config = load_config(config_path)
    userdata_dir = discover_userdata_dir(config.steam_userdata_dir)
    if userdata_dir is None:
        raise SystemExit("Steam userdata directory could not be discovered")

    preferred = args.steam_id if args.steam_id is not None else config.steam_id
    steam_id = discover_steam_id(userdata_dir, preferred_steam_id=preferred)
    if steam_id is None:
        raise SystemExit("Steam id could not be discovered")

    requested_file = args.controller_file
    if requested_file is not None and requested_file.startswith("controller_"):
        raise SystemExit(
            "controller_*.vdf is no longer supported for seed capture. "
            "Use gamehub_wii.vdf, gamehub_3ds.vdf, wii_0.vdf, or 3ds_0.vdf."
        )
    allowed = {_WII_CONTROLLER_FILE, _N3DS_CONTROLLER_FILE, _WII_GAMEHUB_FILE, _N3DS_GAMEHUB_FILE}
    if requested_file is not None and requested_file not in allowed:
        raise SystemExit(
            "Unsupported --controller-file value. "
            "Allowed values: gamehub_wii.vdf, gamehub_3ds.vdf, wii_0.vdf, 3ds_0.vdf."
        )
    expected_files = (requested_file,) if requested_file is not None else _SYSTEM_TO_SOURCE_FILES[args.system]

    template_root = _resolve_existing_template_root(steam_id)
    try:
        source_path = _resolve_title_controller_template(
            template_root,
            title=args.title,
            expected_files=expected_files,
        )
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    destination = _SYSTEM_TO_SEED_PATH[args.system]
    payload = source_path.read_bytes()
    _atomic_write_bytes(destination, payload)

    print(f"Captured seed: system={args.system} steam_id={steam_id}")
    print(f"source={source_path}")
    print(f"destination={destination}")
    print(f"bytes={len(payload)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
