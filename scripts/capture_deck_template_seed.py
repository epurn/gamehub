from __future__ import annotations

import argparse
from pathlib import Path

from gamehub_cli.common.config import load_config
from gamehub_cli.steam.input_templates import (
    discover_deck_steam_input_roots,
    normalize_steam_input_title_dir,
)
from gamehub_cli.steam.io import _atomic_write_bytes
from gamehub_cli.steam.lifecycle import discover_steam_id, discover_userdata_dir

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SYSTEM_TO_SEED_PATH = {
    "wii_gc": _REPO_ROOT / "src" / "gamehub_cli" / "steam" / "template_seeds" / "steamdeck" / "wii_gc" / "controller_neptune.vdf",
    "n3ds": _REPO_ROOT / "src" / "gamehub_cli" / "steam" / "template_seeds" / "steamdeck" / "n3ds" / "controller_neptune.vdf",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture a Steam Deck per-title controller_neptune.vdf file into GAMEHUB repo seed files."
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

    template_root = _resolve_existing_template_root(steam_id)
    normalized_title = normalize_steam_input_title_dir(args.title)
    source_path = template_root / normalized_title / "controller_neptune.vdf"
    if not source_path.exists():
        raise SystemExit(
            "Source template file not found. "
            f"Expected: {source_path}. Ensure the title has a saved Steam Input template."
        )

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
