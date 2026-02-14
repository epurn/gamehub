from __future__ import annotations

from collections import Counter
import json
from urllib.parse import urljoin
from urllib.request import urlopen

try:
    import httpx  # type: ignore
except ModuleNotFoundError:
    httpx = None

from gamehub_common.models import LibraryIndex

from .config import GamehubConfig
from .downloads import download_with_atomic_write
from .planner import SyncPlan, create_sync_plan
from .state import SyncState, load_state, mark_synced, save_state_atomic
from .steam import (
    backup_steam_configs,
    build_context,
    close_steam_best_effort,
    copy_grid_art_placeholder,
    discover_steam_id,
    discover_userdata_dir,
    is_steam_running,
    reopen_steam,
    update_collections_placeholder,
    upsert_shortcuts_placeholder,
    wait_for_steam_exit,
)


def _print_plan(plan: SyncPlan) -> None:
    print("GAMEHUB Sync Plan")
    print("kind\tsystem\titem\tdestination\tsize")
    for action in [*plan.firmware_actions, *plan.content_actions]:
        print(f"{action.kind}\t{action.system}\t{action.label}\t{action.destination}\t{action.size_bytes}")
    print("")
    count_by_kind = Counter(action.kind for action in [*plan.firmware_actions, *plan.content_actions])
    print("Summary")
    print(f"Total actions: {plan.total_actions}")
    print(f"Blocked systems: {len(plan.blocked_systems)}")
    print(f"Skipped titles: {plan.skipped_titles}")
    for kind, count in sorted(count_by_kind.items()):
        print(f"{kind}: {count}")


def _apply_downloads(
    server_url: str,
    plan: SyncPlan,
    state: SyncState,
    timeout_seconds: float,
) -> None:
    for action in plan.firmware_actions:
        download_with_atomic_write(server_url, action.url, action.destination, action.expected_sha256, timeout_seconds)
        state.firmware_checksums[action.content_id] = action.expected_sha256

    for action in plan.content_actions:
        download_with_atomic_write(server_url, action.url, action.destination, action.expected_sha256, timeout_seconds)
        state.downloaded_checksums[action.content_id] = action.expected_sha256


def _apply_steam_updates(config: GamehubConfig, require_steam_closed: bool) -> None:
    userdata_dir = discover_userdata_dir(config.steam_userdata_dir)
    if userdata_dir is None:
        print("Steam userdata directory not found; skipping Steam updates")
        return

    steam_id = discover_steam_id(userdata_dir)
    if steam_id is None:
        print("No Steam ID found in userdata; skipping Steam updates")
        return

    context = build_context(userdata_dir, steam_id, config.steam_exe)
    was_running = is_steam_running()
    if was_running:
        close_steam_best_effort()
        closed = wait_for_steam_exit()
        if not closed and require_steam_closed:
            raise RuntimeError("Steam must be closed before writing config files")

    backups = backup_steam_configs(context)
    if backups:
        print(f"Backed up Steam config files: {', '.join(str(item) for item in backups)}")

    upsert_shortcuts_placeholder()
    update_collections_placeholder()
    copy_grid_art_placeholder()
    if was_running:
        reopen_steam(context)


def run_sync(
    config: GamehubConfig,
    dry_run: bool,
    verbose: bool,
    verify: bool,
    require_steam_closed: bool,
) -> int:
    state = load_state(config.state_path)
    transport_timeout = 60.0 if verbose else 30.0
    index_url = urljoin(config.server_url.rstrip("/") + "/", "v1/index")

    if httpx is not None:
        response = httpx.get(index_url, timeout=transport_timeout)
        response.raise_for_status()
        raw_index = response.json()
    else:
        with urlopen(index_url, timeout=transport_timeout) as response:  # noqa: S310
            raw_index = json.loads(response.read().decode("utf-8"))

    index = LibraryIndex.model_validate(raw_index)
    plan = create_sync_plan(index=index, config=config, state=state, verify=verify)
    _print_plan(plan)
    if dry_run:
        return 0

    _apply_downloads(config.server_url, plan, state, timeout_seconds=transport_timeout)

    _apply_steam_updates(config, require_steam_closed=require_steam_closed)
    mark_synced(state)
    save_state_atomic(config.state_path, state)
    print("Sync completed")
    return 0
