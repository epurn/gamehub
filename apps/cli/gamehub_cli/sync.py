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

from .artwork import (
    SGDB_ART_KINDS,
    SgdbArtworkPipeline,
    SgdbClient,
    build_lookup_plan,
    build_stub_steam_app_id,
    redact_secret,
)
from .config import GamehubConfig
from .downloads import download_with_atomic_write
from .planner import SyncPlan, create_sync_plan
from .state import SyncState, load_state, mark_synced, save_state_atomic
from .steam import (
    SteamArtworkAssignment,
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


def _build_artwork_assignments(
    config: GamehubConfig,
    index: LibraryIndex,
    dry_run: bool,
    timeout_seconds: float,
    verbose: bool,
) -> list[SteamArtworkAssignment]:
    if not config.sgdb_api_key:
        if verbose:
            print("SGDB artwork disabled (no API key configured)")
        return []

    enabled_kinds = tuple(kind for kind in config.sgdb_enabled_kinds if kind in SGDB_ART_KINDS)
    if not enabled_kinds:
        print("SGDB artwork disabled (no valid artwork kinds configured)")
        return []

    if dry_run:
        dry_run_plan = build_lookup_plan(index.titles, enabled_kinds)
        print(
            f"SGDB dry-run: key={redact_secret(config.sgdb_api_key)} "
            f"titles={len(dry_run_plan)} kinds={','.join(enabled_kinds)}"
        )
        for entry in dry_run_plan:
            print(f"sgdb\tlookup\t{entry.title_name}\t{kinds_to_download(entry.kinds)}")
        return []

    with SgdbClient(config.sgdb_api_key, timeout_seconds=timeout_seconds) as client:
        pipeline = SgdbArtworkPipeline(client, cache_dir=config.sgdb_cache_dir, kinds=enabled_kinds)
        result = pipeline.sync(index.titles)

    if result.warnings:
        for warning in result.warnings:
            print(f"Warning: {warning}")
    print(f"SGDB artwork: lookups={result.lookups} downloaded={result.downloaded} cached={result.cached}")

    assignments: list[SteamArtworkAssignment] = []
    for bundle in result.bundles:
        assignments.append(
            SteamArtworkAssignment(
                steam_app_id=build_stub_steam_app_id(bundle.title_id),
                assets_by_kind=bundle.files,
            )
        )
    return assignments


def kinds_to_download(kinds: tuple[str, ...]) -> str:
    return ",".join(kinds)


def _apply_steam_updates(
    config: GamehubConfig,
    require_steam_closed: bool,
    artwork_assignments: list[SteamArtworkAssignment],
) -> None:
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
        if not closed:
            print("Steam is still running after close attempt; skipping Steam updates for safety")
            return

    backups = backup_steam_configs(context)
    if backups:
        print(f"Backed up Steam config files: {', '.join(str(item) for item in backups)}")

    upsert_shortcuts_placeholder()
    update_collections_placeholder()
    copied = copy_grid_art_placeholder(context, artwork_assignments)
    if copied:
        print(f"Copied {len(copied)} artwork files into Steam grid")
    if was_running:
        reopen_steam(context)


def run_sync(
    config: GamehubConfig,
    dry_run: bool,
    verbose: bool,
    verify: bool,
    require_steam_closed: bool,
    skip_steam: bool = False,
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
    artwork_assignments = _build_artwork_assignments(
        config=config,
        index=index,
        dry_run=dry_run,
        timeout_seconds=transport_timeout,
        verbose=verbose,
    )
    if dry_run:
        return 0

    _apply_downloads(config.server_url, plan, state, timeout_seconds=transport_timeout)

    if skip_steam:
        print("Skipping Steam lifecycle and config updates (--skip-steam)")
    else:
        _apply_steam_updates(
            config,
            require_steam_closed=require_steam_closed,
            artwork_assignments=artwork_assignments,
        )
    mark_synced(state)
    save_state_atomic(config.state_path, state)
    print("Sync completed")
    return 0
