from __future__ import annotations

import argparse
import sys
from pathlib import Path

import vdf

from gamehub_cli.common.config import load_config
from gamehub_cli.sync.steam_stage import resolve_steam_context


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate managed Steam shortcut wrapper entries.")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional path to config.toml. Defaults to standard config resolution.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    config = load_config(args.config)
    context = resolve_steam_context(config)
    if context is None:
        print("Steam context could not be resolved from the current config.", file=sys.stderr)
        return 1
    if not context.shortcuts_path.exists():
        print(f"Steam shortcuts file does not exist: {context.shortcuts_path}", file=sys.stderr)
        return 1

    print("SHORTCUTS_PATH:", context.shortcuts_path)

    with context.shortcuts_path.open("rb") as handle:
        data = vdf.binary_load(handle)

    bad_wrappers: list[tuple[object, ...]] = []
    bad_gamehub_mismatch: list[tuple[object, ...]] = []
    bad_payload_registry: list[tuple[object, ...]] = []
    managed = 0
    for key, entry in data.get("shortcuts", {}).items():
        if not isinstance(entry, dict):
            continue
        tags = entry.get("tags", {})
        values = (
            [tags[tag] for tag in sorted(tags, key=lambda item: int(str(item)) if str(item).isdigit() else str(item))]
            if isinstance(tags, dict)
            else []
        )
        if "GAMEHUB" not in values:
            continue
        managed += 1
        exe = str(entry.get("Exe", "")).strip().strip('"')
        launch = str(entry.get("LaunchOptions", "")).strip()
        has_inline_payload = "shortcut-launch --payload " in launch
        has_payload_ref = "shortcut-launch --payload-ref " in launch
        uses_gamehub = "gamehub" in exe.lower()
        uses_python_module = "python" in exe.lower() and (
            launch.startswith("-m gamehub_cli.main shortcut-launch --payload ")
            or launch.startswith("-m gamehub_cli.main shortcut-launch --payload-ref ")
        )
        has_payload = has_inline_payload or has_payload_ref

        if has_payload and not (uses_gamehub or uses_python_module):
            bad_wrappers.append((key, entry.get("AppName", ""), exe, launch))
        if uses_gamehub and launch.startswith("-m "):
            bad_gamehub_mismatch.append((key, entry.get("AppName", ""), exe, launch))
        if has_payload_ref and "--payload-registry " not in launch:
            bad_payload_registry.append((key, entry.get("AppName", ""), exe, launch))

    print("MANAGED_SHORTCUTS:", managed)
    print("BAD_WRAPPERS:", len(bad_wrappers))
    print("BAD_GAMEHUB_MISMATCH:", len(bad_gamehub_mismatch))
    print("BAD_PAYLOAD_REGISTRY:", len(bad_payload_registry))
    for row in bad_wrappers[:10]:
        print("BAD_WRAPPER:", row)
    for row in bad_gamehub_mismatch[:10]:
        print("BAD_GAMEHUB_MISMATCH:", row)
    for row in bad_payload_registry[:10]:
        print("BAD_PAYLOAD_REGISTRY:", row)

    return 1 if bad_wrappers or bad_gamehub_mismatch or bad_payload_registry else 0


if __name__ == "__main__":
    raise SystemExit(main())
