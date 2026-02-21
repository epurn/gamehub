from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable
from urllib.parse import urljoin

from gamehub_common.models import LibraryIndex

from ..common.config import GamehubConfig
from ..controllers.profiles import seed_default_profiles
from ..emulators import ensure_emulators
from ..firmware.deploy import deploy_firmware_to_emulators
from ..firmware.retroarch_cores import ensure_retroarch_cores
from ..steam import steam_id64_from_userdata_id
from . import artwork_stage, steam_stage, transfer_stage
from . import index as sync_index
from .planner import create_sync_plan
from .state import load_state, mark_synced, save_state_atomic


@dataclass(frozen=True)
class SyncDependencies:
    fetch_index_with_retries: Callable[..., dict]
    print_plan: Callable[[Any], None]
    apply_downloads: Callable[..., None]
    bootstrap_firmware_dirs: Callable[[GamehubConfig, LibraryIndex, bool, bool], None]
    build_artwork_assignments: Callable[..., dict[str, dict[str, Path]]]
    build_shortcut_specs: Callable[[LibraryIndex, GamehubConfig], list]
    resolve_steam_context: Callable[[GamehubConfig], object | None]
    apply_steam_updates: Callable[..., None]


def _default_dependencies() -> SyncDependencies:
    return SyncDependencies(
        fetch_index_with_retries=sync_index.fetch_index_with_retries,
        print_plan=transfer_stage.print_plan,
        apply_downloads=transfer_stage.apply_downloads,
        bootstrap_firmware_dirs=transfer_stage.bootstrap_firmware_dirs,
        build_artwork_assignments=artwork_stage.build_artwork_assignments,
        build_shortcut_specs=steam_stage.build_shortcut_specs,
        resolve_steam_context=steam_stage.resolve_steam_context,
        apply_steam_updates=steam_stage.apply_steam_updates,
    )


_DEPS = _default_dependencies()

# Compatibility exports for existing tests/helpers.
httpx: ModuleType | None = sync_index.httpx
_is_retryable_index_status = sync_index._is_retryable_index_status
_is_retryable_index_fetch_error = sync_index._is_retryable_index_fetch_error
kinds_to_download = artwork_stage.kinds_to_download


def configure_dependencies(
    *,
    fetch_index_with_retries: Callable[..., dict] | None = None,
    print_plan: Callable[[object], None] | None = None,
    apply_downloads: Callable[..., None] | None = None,
    bootstrap_firmware_dirs: Callable[[GamehubConfig, LibraryIndex, bool, bool], None] | None = None,
    build_artwork_assignments: Callable[..., dict[str, dict[str, Path]]] | None = None,
    build_shortcut_specs: Callable[[LibraryIndex, GamehubConfig], list] | None = None,
    resolve_steam_context: Callable[[GamehubConfig], object | None] | None = None,
    apply_steam_updates: Callable[..., None] | None = None,
) -> None:
    """Allow explicit sync dependency overrides without mutating stage modules."""

    global _DEPS
    _DEPS = SyncDependencies(
        fetch_index_with_retries=fetch_index_with_retries or _DEPS.fetch_index_with_retries,
        print_plan=print_plan or _DEPS.print_plan,
        apply_downloads=apply_downloads or _DEPS.apply_downloads,
        bootstrap_firmware_dirs=bootstrap_firmware_dirs or _DEPS.bootstrap_firmware_dirs,
        build_artwork_assignments=build_artwork_assignments or _DEPS.build_artwork_assignments,
        build_shortcut_specs=build_shortcut_specs or _DEPS.build_shortcut_specs,
        resolve_steam_context=resolve_steam_context or _DEPS.resolve_steam_context,
        apply_steam_updates=apply_steam_updates or _DEPS.apply_steam_updates,
    )


def _print_plan(plan: object) -> None:
    _DEPS.print_plan(plan)


def _apply_downloads(
    server_url: str,
    plan: object,
    state: object,
    timeout_seconds: float,
    verbose: bool = False,
    max_parallel_downloads: int = transfer_stage.DEFAULT_MAX_PARALLEL_DOWNLOADS,
) -> None:
    _DEPS.apply_downloads(
        server_url,
        plan,
        state,
        timeout_seconds,
        verbose=verbose,
        max_parallel_downloads=max_parallel_downloads,
    )


def _bootstrap_firmware_dirs(config: GamehubConfig, index: LibraryIndex, dry_run: bool, verbose: bool) -> None:
    _DEPS.bootstrap_firmware_dirs(config, index, dry_run, verbose)


def _build_artwork_assignments(
    config: GamehubConfig,
    index: LibraryIndex,
    dry_run: bool,
    timeout_seconds: float,
    verbose: bool,
) -> dict[str, dict[str, Path]]:
    return _DEPS.build_artwork_assignments(
        config=config,
        index=index,
        dry_run=dry_run,
        timeout_seconds=timeout_seconds,
        verbose=verbose,
    )


def _build_shortcut_specs(index: LibraryIndex, config: GamehubConfig):
    return _DEPS.build_shortcut_specs(index, config)


def _resolve_steam_context(config: GamehubConfig):
    return _DEPS.resolve_steam_context(config)


def _apply_steam_updates(
    config: GamehubConfig,
    index: LibraryIndex,
    require_steam_closed: bool,
    artwork_by_title: dict[str, dict[str, Path]],
    reopen_steam_after_update: bool = True,
) -> None:
    _DEPS.apply_steam_updates(
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
    return _DEPS.fetch_index_with_retries(
        index_url=index_url,
        timeout_seconds=timeout_seconds,
        attempts=attempts,
        retry_backoff_seconds=retry_backoff_seconds,
        verbose=verbose,
        http_client_module=httpx,
        sleep_func=time.sleep,
    )


def run_sync(
    config: GamehubConfig,
    dry_run: bool,
    verbose: bool,
    verify: bool,
    require_steam_closed: bool,
    skip_steam: bool = False,
    skip_steam_relaunch: bool = False,
    reseed_profiles: bool = False,
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

    if config.controllers.launch_autoconfig:
        seeded_profiles = seed_default_profiles(config=config, verbose=verbose, force=reseed_profiles)
        if verbose:
            if seeded_profiles:
                print(f"Seeded controller profile defaults: {len(seeded_profiles)}")
            elif config.controllers.profiles_dir is not None:
                print("Controller profiles: custom profiles_dir set; default seeding skipped")

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
