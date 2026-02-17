from __future__ import annotations

import sys
import time
from urllib.parse import urljoin

from gamehub_common.models import LibraryIndex

from .config import GamehubConfig
from .controller_profiles import seed_default_profiles
from .downloads import download_with_atomic_write
from .emulators import ensure_emulators, resolve_emulator_executable
from .firmware_deploy import deploy_firmware_to_emulators
from .paths import from_rel_path
from .planner import create_sync_plan
from .retroarch_cores import ensure_retroarch_cores, resolve_retroarch_paths
from .state import load_state, mark_synced, save_state_atomic
from .steam import (
    backup_steam_configs,
    build_context,
    close_steam_best_effort,
    copy_grid_art,
    discover_steam_id,
    discover_userdata_dir,
    is_steam_running,
    prune_grid_noncanonical_variants,
    reopen_steam,
    steam_id64_from_userdata_id,
    update_cloud_collections,
    update_collections,
    upsert_shortcuts,
    wait_for_steam_exit,
)
import gamehub_cli.sync_artwork_stage as sync_artwork_stage
import gamehub_cli.sync_index as sync_index
import gamehub_cli.sync_steam_stage as sync_steam_stage
import gamehub_cli.sync_transfer_stage as sync_transfer_stage


httpx = sync_index.httpx


_is_retryable_index_status = sync_index._is_retryable_index_status
_is_retryable_index_fetch_error = sync_index._is_retryable_index_fetch_error

_stage_build_shortcut_specs = sync_steam_stage.build_shortcut_specs
_stage_resolve_steam_context = sync_steam_stage.resolve_steam_context
_stage_apply_steam_updates = sync_steam_stage.apply_steam_updates


kinds_to_download = sync_artwork_stage.kinds_to_download


def _print_plan(plan) -> None:
    sync_transfer_stage.print_plan(plan)


def _apply_downloads(
    server_url: str,
    plan,
    state,
    timeout_seconds: float,
    verbose: bool = False,
    max_parallel_downloads: int = sync_transfer_stage.DEFAULT_MAX_PARALLEL_DOWNLOADS,
) -> None:
    sync_transfer_stage.download_with_atomic_write = download_with_atomic_write
    sync_transfer_stage.apply_downloads(
        server_url,
        plan,
        state,
        timeout_seconds,
        verbose=verbose,
        max_parallel_downloads=max_parallel_downloads,
    )


def _bootstrap_firmware_dirs(config: GamehubConfig, index: LibraryIndex, dry_run: bool, verbose: bool) -> None:
    sync_transfer_stage.bootstrap_firmware_dirs(config, index, dry_run=dry_run, verbose=verbose)


def _build_artwork_assignments(
    config: GamehubConfig,
    index: LibraryIndex,
    dry_run: bool,
    timeout_seconds: float,
    verbose: bool,
):
    return sync_artwork_stage.build_artwork_assignments(
        config=config,
        index=index,
        dry_run=dry_run,
        timeout_seconds=timeout_seconds,
        verbose=verbose,
    )


def _build_shortcut_specs(index: LibraryIndex, config: GamehubConfig):
    sync_steam_stage.resolve_emulator_executable = resolve_emulator_executable
    sync_steam_stage.resolve_retroarch_paths = resolve_retroarch_paths
    sync_steam_stage.from_rel_path = from_rel_path
    sync_steam_stage.sys = sys
    return _stage_build_shortcut_specs(index, config)


def _resolve_steam_context(config: GamehubConfig):
    sync_steam_stage.discover_userdata_dir = discover_userdata_dir
    sync_steam_stage.discover_steam_id = discover_steam_id
    sync_steam_stage.build_context = build_context
    return _stage_resolve_steam_context(config)


def _apply_steam_updates(
    config: GamehubConfig,
    index: LibraryIndex,
    require_steam_closed: bool,
    artwork_by_title: dict[str, dict],
    reopen_steam_after_update: bool = True,
) -> None:
    sync_steam_stage.resolve_steam_context = _resolve_steam_context
    sync_steam_stage.build_shortcut_specs = _build_shortcut_specs
    sync_steam_stage.is_steam_running = is_steam_running
    sync_steam_stage.close_steam_best_effort = close_steam_best_effort
    sync_steam_stage.wait_for_steam_exit = wait_for_steam_exit
    sync_steam_stage.backup_steam_configs = backup_steam_configs
    sync_steam_stage.upsert_shortcuts = upsert_shortcuts
    sync_steam_stage.update_collections = update_collections
    sync_steam_stage.update_cloud_collections = update_cloud_collections
    sync_steam_stage.copy_grid_art = copy_grid_art
    sync_steam_stage.prune_grid_noncanonical_variants = prune_grid_noncanonical_variants
    sync_steam_stage.reopen_steam = reopen_steam
    _stage_apply_steam_updates(
        config,
        index=index,
        require_steam_closed=require_steam_closed,
        artwork_by_title=artwork_by_title,
        reopen_steam_after_update=reopen_steam_after_update,
    )


def _fetch_index_with_retries(
    *,
    index_url: str,
    timeout_seconds: float,
    attempts: int,
    retry_backoff_seconds: float,
    verbose: bool,
) -> dict:
    sync_index.httpx = httpx
    sync_index.time = time
    return sync_index.fetch_index_with_retries(
        index_url=index_url,
        timeout_seconds=timeout_seconds,
        attempts=attempts,
        retry_backoff_seconds=retry_backoff_seconds,
        verbose=verbose,
    )


def run_sync(
    config: GamehubConfig,
    dry_run: bool,
    verbose: bool,
    verify: bool,
    require_steam_closed: bool,
    skip_steam: bool = False,
    skip_steam_relaunch: bool = False,
) -> int:
    if verbose:
        print(
            "Effective config: "
            f"server={config.server_url} "
            f"gamehub_dir={config.library_dir} "
            f"firmware_dir={config.firmware_dir} "
            f"state={config.state_path} "
            f"steam_userdata={config.steam_userdata_dir or '<auto>'} "
            f"steam_id={config.steam_id or '<auto>'}"
        )
    print("Loading local sync state...")
    state = load_state(config.state_path)
    transfer_timeout = 60.0 if verbose else 30.0
    index_timeout = config.index_timeout_seconds if config.index_timeout_seconds is not None else transfer_timeout
    index_url = urljoin(config.server_url.rstrip("/") + "/", "v1/index")
    print(f"Fetching index: {index_url}")
    raw_index = _fetch_index_with_retries(
        index_url=index_url,
        timeout_seconds=index_timeout,
        attempts=config.index_fetch_attempts,
        retry_backoff_seconds=config.index_retry_backoff_seconds,
        verbose=verbose,
    )

    index = LibraryIndex.model_validate(raw_index)
    ensure_emulators(
        index=index,
        dry_run=dry_run,
        verbose=verbose,
        linux_install_backend=config.linux.emulator_install_backend,
        linux_install_command=config.linux.emulator_install_command,
        linux_flatpak_remote=config.linux.flatpak_remote,
    )
    ensure_retroarch_cores(
        index=index,
        dry_run=dry_run,
        verbose=verbose,
        explicit_cores_dir=config.linux.retroarch_cores_dir,
        explicit_info_dir=config.linux.retroarch_info_dir,
        explicit_base_url=config.linux.retroarch_cores_base_url,
        explicit_cfg_path=config.linux.retroarch_cfg_path,
    )
    _bootstrap_firmware_dirs(config=config, index=index, dry_run=dry_run, verbose=verbose)
    plan = create_sync_plan(index=index, config=config, state=state, verify=verify)
    _print_plan(plan)
    steam_context = _resolve_steam_context(config)
    if steam_context is not None:
        steam_id64 = steam_id64_from_userdata_id(steam_context.steam_id) or "<unknown>"
        print(
            f"Steam target: userdata_id={steam_context.steam_id} "
            f"steamid64={steam_id64} userdata={steam_context.userdata_dir}"
        )
    artwork_assignments = _build_artwork_assignments(
        config=config,
        index=index,
        dry_run=dry_run,
        timeout_seconds=transfer_timeout,
        verbose=verbose,
    )
    if dry_run:
        deploy_firmware_to_emulators(config=config, index=index, dry_run=True, verbose=verbose)
        return 0

    seeded_profiles = seed_default_profiles(config=config, verbose=verbose, force=True)
    if verbose and seeded_profiles:
        print(f"Seeded controller profile defaults: {len(seeded_profiles)}")

    _apply_downloads(
        config.server_url,
        plan,
        state,
        timeout_seconds=transfer_timeout,
        verbose=verbose,
        max_parallel_downloads=config.max_parallel_downloads,
    )
    deploy_firmware_to_emulators(config=config, index=index, dry_run=False, verbose=verbose)

    if skip_steam:
        print("Skipping Steam lifecycle and config updates (--skip-steam)")
    else:
        print("Applying Steam updates...")
        _apply_steam_updates(
            config,
            index=index,
            require_steam_closed=require_steam_closed,
            artwork_by_title=artwork_assignments,
            reopen_steam_after_update=not skip_steam_relaunch,
        )
    mark_synced(state)
    save_state_atomic(config.state_path, state)
    print("Sync completed")
    return 0
