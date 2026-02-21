from __future__ import annotations

import sys
import time

from ..common.paths import from_rel_path
from ..controllers.profiles import seed_default_profiles
from ..downloads import download_with_atomic_write
from ..emulators import ensure_emulators, resolve_emulator_executable
from ..firmware import deploy_firmware_to_emulators, ensure_retroarch_cores, resolve_retroarch_paths
from ..steam import (
    backup_steam_configs,
    build_context,
    close_steam_best_effort,
    copy_grid_art,
    discover_steam_id,
    discover_userdata_dir,
    is_steam_running,
    prune_grid_noncanonical_variants,
    reopen_steam,
    update_cloud_collections,
    update_collections,
    upsert_shortcuts,
    wait_for_steam_exit,
)
from . import index as sync_index
from . import orchestrator as _orchestrator
from . import steam_stage, transfer_stage
from .artwork_stage import kinds_to_download
from .index import _is_retryable_index_fetch_error, _is_retryable_index_status

# Compatibility handle used by tests/callers that monkeypatch gamehub_cli.sync.httpx.
httpx = _orchestrator.httpx


def configure_dependencies(**kwargs):
    return _orchestrator.configure_dependencies(**kwargs)


def _sync_runtime_overrides() -> None:
    _orchestrator.httpx = httpx
    _orchestrator.time = time

    _orchestrator.ensure_emulators = ensure_emulators
    _orchestrator.ensure_retroarch_cores = ensure_retroarch_cores
    _orchestrator.deploy_firmware_to_emulators = deploy_firmware_to_emulators
    _orchestrator.seed_default_profiles = seed_default_profiles

    sync_index.time = time
    transfer_stage.download_with_atomic_write = download_with_atomic_write

    steam_stage.discover_userdata_dir = discover_userdata_dir
    steam_stage.discover_steam_id = discover_steam_id
    steam_stage.build_context = build_context
    steam_stage.is_steam_running = is_steam_running
    steam_stage.close_steam_best_effort = close_steam_best_effort
    steam_stage.wait_for_steam_exit = wait_for_steam_exit
    steam_stage.backup_steam_configs = backup_steam_configs
    steam_stage.upsert_shortcuts = upsert_shortcuts
    steam_stage.update_collections = update_collections
    steam_stage.update_cloud_collections = update_cloud_collections
    steam_stage.copy_grid_art = copy_grid_art
    steam_stage.prune_grid_noncanonical_variants = prune_grid_noncanonical_variants
    steam_stage.reopen_steam = reopen_steam
    steam_stage.resolve_emulator_executable = resolve_emulator_executable
    steam_stage.resolve_retroarch_paths = resolve_retroarch_paths
    steam_stage.from_rel_path = from_rel_path
    steam_stage.sys = sys


def _print_plan(plan):
    _sync_runtime_overrides()
    return _orchestrator._print_plan(plan)


def _apply_downloads(*args, **kwargs):
    _sync_runtime_overrides()
    return _orchestrator._apply_downloads(*args, **kwargs)


def _bootstrap_firmware_dirs(*args, **kwargs):
    _sync_runtime_overrides()
    return _orchestrator._bootstrap_firmware_dirs(*args, **kwargs)


def _build_artwork_assignments(*args, **kwargs):
    _sync_runtime_overrides()
    return _orchestrator._build_artwork_assignments(*args, **kwargs)


def _build_shortcut_specs(*args, **kwargs):
    _sync_runtime_overrides()
    return _orchestrator._build_shortcut_specs(*args, **kwargs)


def _resolve_steam_context(*args, **kwargs):
    _sync_runtime_overrides()
    return _orchestrator._resolve_steam_context(*args, **kwargs)


def _apply_steam_updates(*args, **kwargs):
    _sync_runtime_overrides()
    return _orchestrator._apply_steam_updates(*args, **kwargs)


def _fetch_index_with_retries(*args, **kwargs):
    _sync_runtime_overrides()
    return _orchestrator._fetch_index_with_retries(*args, **kwargs)


def run_sync(*args, **kwargs):
    _sync_runtime_overrides()
    return _orchestrator.run_sync(*args, **kwargs)


__all__ = [
    "backup_steam_configs",
    "build_context",
    "close_steam_best_effort",
    "configure_dependencies",
    "copy_grid_art",
    "deploy_firmware_to_emulators",
    "discover_steam_id",
    "discover_userdata_dir",
    "download_with_atomic_write",
    "ensure_emulators",
    "ensure_retroarch_cores",
    "from_rel_path",
    "httpx",
    "is_steam_running",
    "kinds_to_download",
    "prune_grid_noncanonical_variants",
    "reopen_steam",
    "resolve_emulator_executable",
    "resolve_retroarch_paths",
    "run_sync",
    "seed_default_profiles",
    "sys",
    "time",
    "update_cloud_collections",
    "update_collections",
    "upsert_shortcuts",
    "wait_for_steam_exit",
    "_apply_downloads",
    "_apply_steam_updates",
    "_bootstrap_firmware_dirs",
    "_build_artwork_assignments",
    "_build_shortcut_specs",
    "_fetch_index_with_retries",
    "_is_retryable_index_fetch_error",
    "_is_retryable_index_status",
    "_print_plan",
    "_resolve_steam_context",
]
