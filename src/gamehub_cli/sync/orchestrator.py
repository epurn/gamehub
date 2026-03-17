from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, cast
from urllib.parse import urljoin

from gamehub_common.models import LibraryIndex, SaveBindingCatalog

from ..common.config import GamehubConfig
from ..controllers.convergence import converge_controller_state
from ..controllers.profiles import seed_default_profiles
from ..emulators import ensure_emulators
from ..firmware.deploy import deploy_firmware_to_emulators
from ..firmware.retroarch_cores import ensure_retroarch_cores
from ..steam import SteamContext, SteamShortcutSpec, steam_id64_from_userdata_id
from . import artwork_stage, save_stage, steam_stage, transfer_stage
from . import index as sync_index
from .planner import create_sync_plan
from .save_conflicts import prune_persisted_save_conflicts
from .server_status import require_server_compatibility
from .state import (
    SyncState,
    has_bootstrap_marker,
    load_state,
    mark_bootstrapped,
    mark_synced,
    save_state_atomic,
)


@dataclass(frozen=True)
class SyncDependencies:
    fetch_index_with_retries: Callable[..., dict]
    print_plan: Callable[[Any], None]
    apply_downloads: Callable[..., None]
    bootstrap_firmware_dirs: Callable[[GamehubConfig, LibraryIndex, bool, bool], None]
    converge_controller_state: Callable[..., object]
    build_artwork_assignments: Callable[..., dict[str, dict[str, Path]]]
    build_shortcut_specs: Callable[[LibraryIndex, GamehubConfig], list[SteamShortcutSpec]]
    resolve_steam_context: Callable[[GamehubConfig], SteamContext | None]
    apply_steam_updates: Callable[..., None]


@dataclass
class SyncPlanSummary:
    total_actions: int = 0
    blocked_systems: dict[str, str] = field(default_factory=dict)
    skipped_titles: int = 0
    counts_by_kind: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "total_actions": self.total_actions,
            "blocked_systems": dict(self.blocked_systems),
            "skipped_titles": self.skipped_titles,
            "counts_by_kind": dict(self.counts_by_kind),
        }


@dataclass
class SyncDownloadSummary:
    firmware_planned: int = 0
    content_planned: int = 0
    total_planned: int = 0
    completed: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "firmware_planned": self.firmware_planned,
            "content_planned": self.content_planned,
            "total_planned": self.total_planned,
            "completed": self.completed,
        }


@dataclass
class SyncSaveSummary:
    enabled: bool = False
    planned: int = 0
    downloaded: int = 0
    uploaded: int = 0
    conflicts: int = 0
    skipped: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "planned": self.planned,
            "downloaded": self.downloaded,
            "uploaded": self.uploaded,
            "conflicts": self.conflicts,
            "skipped": self.skipped,
        }


@dataclass
class SyncSteamSummary:
    requested: bool = False
    applied: bool = False
    skipped: bool = False
    reason: str | None = None
    target_userdata_id: str | None = None
    target_steamid64: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "requested": self.requested,
            "applied": self.applied,
            "skipped": self.skipped,
            "reason": self.reason,
            "target_userdata_id": self.target_userdata_id,
            "target_steamid64": self.target_steamid64,
        }


@dataclass
class SyncRunReport:
    ok: bool
    dry_run: bool
    server_url: str | None
    plan: SyncPlanSummary = field(default_factory=SyncPlanSummary)
    downloads: SyncDownloadSummary = field(default_factory=SyncDownloadSummary)
    save_sync: SyncSaveSummary = field(default_factory=SyncSaveSummary)
    steam: SyncSteamSummary = field(default_factory=SyncSteamSummary)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "dry_run": self.dry_run,
            "server_url": self.server_url,
            "plan": self.plan.to_dict(),
            "downloads": self.downloads.to_dict(),
            "save_sync": self.save_sync.to_dict(),
            "steam": self.steam.to_dict(),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


def _default_dependencies() -> SyncDependencies:
    return SyncDependencies(
        fetch_index_with_retries=sync_index.fetch_index_with_retries,
        print_plan=transfer_stage.print_plan,
        apply_downloads=transfer_stage.apply_downloads,
        bootstrap_firmware_dirs=transfer_stage.bootstrap_firmware_dirs,
        converge_controller_state=converge_controller_state,
        build_artwork_assignments=artwork_stage.build_artwork_assignments,
        build_shortcut_specs=steam_stage.build_shortcut_specs,
        resolve_steam_context=steam_stage.resolve_steam_context,
        apply_steam_updates=steam_stage.apply_steam_updates,
    )


_DEPS = _default_dependencies()


def configure_dependencies(
    *,
    fetch_index_with_retries: Callable[..., dict] | None = None,
    print_plan: Callable[[object], None] | None = None,
    apply_downloads: Callable[..., None] | None = None,
    bootstrap_firmware_dirs: Callable[[GamehubConfig, LibraryIndex, bool, bool], None] | None = None,
    converge_controller_state: Callable[..., object] | None = None,
    build_artwork_assignments: Callable[..., dict[str, dict[str, Path]]] | None = None,
    build_shortcut_specs: Callable[[LibraryIndex, GamehubConfig], list[SteamShortcutSpec]] | None = None,
    resolve_steam_context: Callable[[GamehubConfig], SteamContext | None] | None = None,
    apply_steam_updates: Callable[..., None] | None = None,
) -> None:
    """Allow explicit sync dependency overrides without mutating stage modules."""

    global _DEPS
    _DEPS = SyncDependencies(
        fetch_index_with_retries=fetch_index_with_retries or _DEPS.fetch_index_with_retries,
        print_plan=print_plan or _DEPS.print_plan,
        apply_downloads=apply_downloads or _DEPS.apply_downloads,
        bootstrap_firmware_dirs=bootstrap_firmware_dirs or _DEPS.bootstrap_firmware_dirs,
        converge_controller_state=converge_controller_state or _DEPS.converge_controller_state,
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


def _converge_controller_state(
    config: GamehubConfig,
    *,
    index: LibraryIndex,
    dry_run: bool,
    verbose: bool,
    force_managed: bool,
) -> object:
    return _DEPS.converge_controller_state(
        config,
        index=index,
        dry_run=dry_run,
        verbose=verbose,
        force_managed=force_managed,
    )


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


def _build_shortcut_specs(index: LibraryIndex, config: GamehubConfig) -> list[SteamShortcutSpec]:
    return _DEPS.build_shortcut_specs(index, config)


def _resolve_steam_context(config: GamehubConfig) -> SteamContext | None:
    return _DEPS.resolve_steam_context(config)


def _apply_steam_updates(
    config: GamehubConfig,
    index: LibraryIndex,
    require_steam_closed: bool,
    artwork_by_title: dict[str, dict[str, Path]],
    reopen_steam_after_update: bool = True,
    reseed_profiles: bool = False,
) -> None:
    _DEPS.apply_steam_updates(
        config,
        index=index,
        require_steam_closed=require_steam_closed,
        artwork_by_title=artwork_by_title,
        reopen_steam_after_update=reopen_steam_after_update,
        reseed_profiles=reseed_profiles,
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
        http_client_module=sync_index.httpx,
        sleep_func=time.sleep,
        reporter=print,
    )


def _print_effective_config(config: GamehubConfig) -> None:
    print(
        "Effective config: "
        f"server={config.server_url} "
        f"gamehub_dir={config.library_dir} "
        f"firmware_dir={config.firmware_dir} "
        f"state={config.state_path} "
        f"steam_userdata={config.steam_userdata_dir or '<auto>'} "
        f"steam_id={config.steam_id or '<auto>'}"
    )


def _load_sync_state(config: GamehubConfig) -> SyncState:
    print("Loading local sync state...")
    return load_state(config.state_path)


def _transfer_timeout_seconds(verbose: bool) -> float:
    return 60.0 if verbose else 30.0


def _load_validated_index(config: GamehubConfig, *, transfer_timeout: float, verbose: bool) -> LibraryIndex:
    require_server_compatibility(config, verbose=verbose, timeout_seconds=transfer_timeout)
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
    return cast(LibraryIndex, LibraryIndex.model_validate(raw_index))


def _load_validated_save_bindings(
    config: GamehubConfig, *, transfer_timeout: float, verbose: bool
) -> SaveBindingCatalog | None:
    if not config.save_sync.enabled:
        return None
    bindings_timeout = config.index_timeout_seconds if config.index_timeout_seconds is not None else transfer_timeout
    bindings_url = urljoin(config.server_url.rstrip("/") + "/", "v1/save-bindings")
    print(f"Fetching save bindings: {bindings_url}")
    raw_bindings = sync_index.fetch_save_bindings_with_retries(
        bindings_url=bindings_url,
        timeout_seconds=bindings_timeout,
        attempts=config.index_fetch_attempts,
        retry_backoff_seconds=config.index_retry_backoff_seconds,
        verbose=verbose,
        http_client_module=sync_index.httpx,
        sleep_func=time.sleep,
        reporter=print,
    )
    return cast(SaveBindingCatalog, SaveBindingCatalog.model_validate(raw_bindings))


def _bootstrap_runtime(
    config: GamehubConfig,
    *,
    index: LibraryIndex,
    dry_run: bool,
    verbose: bool,
) -> None:
    ensure_emulators(
        index=index,
        dry_run=dry_run,
        verbose=verbose,
        linux_install_backend=config.linux.emulator_install_backend,
        linux_install_command=config.linux.emulator_install_command,
        linux_flatpak_remote=config.linux.flatpak_remote,
        macos_install_backend=config.macos.emulator_install_backend,
        macos_install_command=config.macos.emulator_install_command,
        macos_disable_pcsx2_rosetta=config.macos.disable_pcsx2_rosetta,
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


def _converge_bootstrap_controller_state(
    config: GamehubConfig,
    *,
    index: LibraryIndex,
    dry_run: bool,
    verbose: bool,
    reseed_profiles: bool,
) -> None:
    if not config.controllers.launch_autoconfig:
        return
    if not dry_run:
        seeded_profiles = seed_default_profiles(
            config=config,
            verbose=verbose,
            force=reseed_profiles,
            allow_custom=True,
        )
        if verbose and seeded_profiles:
            print(f"Seeded controller profile defaults: {len(seeded_profiles)}")
    _converge_controller_state(
        config,
        index=index,
        dry_run=dry_run,
        verbose=verbose,
        force_managed=reseed_profiles,
    )


def _sync_requires_init(state: SyncState) -> bool:
    return not has_bootstrap_marker(state)


def _summarize_plan(plan: object) -> SyncPlanSummary:
    from .planner import SyncPlan

    typed_plan = cast(SyncPlan, plan)
    count_by_kind = Counter(action.kind for action in [*typed_plan.firmware_actions, *typed_plan.content_actions])
    count_by_kind.update(f"save:{action.decision}" for action in typed_plan.save_actions)
    return SyncPlanSummary(
        total_actions=typed_plan.total_actions,
        blocked_systems=dict(typed_plan.blocked_systems),
        skipped_titles=typed_plan.skipped_titles,
        counts_by_kind={kind: count_by_kind[kind] for kind in sorted(count_by_kind)},
    )


def _summarize_downloads(plan: object, *, completed: int = 0) -> SyncDownloadSummary:
    from .planner import SyncPlan

    typed_plan = cast(SyncPlan, plan)
    firmware_planned = len(typed_plan.firmware_actions)
    content_planned = len(typed_plan.content_actions)
    return SyncDownloadSummary(
        firmware_planned=firmware_planned,
        content_planned=content_planned,
        total_planned=firmware_planned + content_planned,
        completed=completed,
    )


def _empty_save_summary(*, enabled: bool) -> SyncSaveSummary:
    return SyncSaveSummary(enabled=enabled)


def _summarize_save_stage(result: save_stage.SaveStageResult, *, enabled: bool) -> SyncSaveSummary:
    return SyncSaveSummary(
        enabled=enabled,
        planned=result.planned,
        downloaded=result.downloaded,
        uploaded=result.uploaded,
        conflicts=result.conflicts,
        skipped=result.skipped,
    )


def _default_sync_report(*, config: GamehubConfig | None, dry_run: bool, skip_steam: bool) -> SyncRunReport:
    return SyncRunReport(
        ok=False,
        dry_run=dry_run,
        server_url=config.server_url if config is not None else None,
        save_sync=_empty_save_summary(enabled=config.save_sync.enabled if config is not None else False),
        steam=SyncSteamSummary(
            requested=not skip_steam, skipped=skip_steam, reason="--skip-steam" if skip_steam else None
        ),
    )


def run_init(
    config: GamehubConfig,
    dry_run: bool,
    verbose: bool,
    reseed_profiles: bool = False,
) -> int:
    if verbose:
        _print_effective_config(config)
    state = _load_sync_state(config)
    transfer_timeout = _transfer_timeout_seconds(verbose)
    index = _load_validated_index(config, transfer_timeout=transfer_timeout, verbose=verbose)
    _bootstrap_runtime(config, index=index, dry_run=dry_run, verbose=verbose)
    deploy_firmware_to_emulators(config=config, index=index, dry_run=dry_run, verbose=verbose)
    _converge_bootstrap_controller_state(
        config,
        index=index,
        dry_run=dry_run,
        verbose=verbose,
        reseed_profiles=reseed_profiles,
    )
    if dry_run:
        print("Init dry-run completed")
        return 0
    mark_bootstrapped(state)
    save_state_atomic(config.state_path, state, keep_limit=config.backups.keep_limit)
    print("Init completed")
    return 0


def run_sync_report(
    config: GamehubConfig,
    dry_run: bool,
    verbose: bool,
    verify: bool,
    require_steam_closed: bool,
    skip_steam: bool = False,
    skip_steam_relaunch: bool = False,
    reseed_profiles: bool = False,
    *,
    capture_errors: bool = False,
) -> SyncRunReport:
    report = _default_sync_report(config=config, dry_run=dry_run, skip_steam=skip_steam)

    try:
        if verbose:
            _print_effective_config(config)
        state = _load_sync_state(config)
        if _sync_requires_init(state):
            message = "GAMEHUB is not initialized. Run 'gamehub init' before the first sync."
            print(message)
            report.errors.append(message)
            return report

        transfer_timeout = _transfer_timeout_seconds(verbose)
        index = _load_validated_index(config, transfer_timeout=transfer_timeout, verbose=verbose)
        save_bindings = _load_validated_save_bindings(config, transfer_timeout=transfer_timeout, verbose=verbose)
        _bootstrap_runtime(config, index=index, dry_run=dry_run, verbose=verbose)

        plan = create_sync_plan(index=index, config=config, state=state, verify=verify, save_bindings=save_bindings)
        report.plan = _summarize_plan(plan)
        report.downloads = _summarize_downloads(plan)
        if report.plan.blocked_systems:
            for system_name, reason in sorted(report.plan.blocked_systems.items()):
                report.warnings.append(f"Blocked system {system_name}: {reason}")
        _print_plan(plan)

        steam_context = _resolve_steam_context(config)
        if steam_context is not None:
            steam_id64 = steam_id64_from_userdata_id(steam_context.steam_id) or "<unknown>"
            report.steam.target_userdata_id = steam_context.steam_id
            report.steam.target_steamid64 = steam_id64
            print(
                f"Steam target: userdata_id={steam_context.steam_id} "
                f"steamid64={steam_id64} userdata={steam_context.userdata_dir}"
            )
        elif not skip_steam:
            report.steam.skipped = True
            report.steam.reason = "steam-context-unavailable"
            report.warnings.append("Steam updates were not applied because no Steam target was resolved.")

        artwork_assignments = _build_artwork_assignments(
            config=config,
            index=index,
            dry_run=dry_run,
            timeout_seconds=transfer_timeout,
            verbose=verbose,
        )
        if dry_run:
            save_result = save_stage.apply_save_stage(
                server_url=config.server_url,
                plan=plan,
                state=state,
                timeout_seconds=transfer_timeout,
                dry_run=True,
                verbose=verbose,
                backup_keep_limit=config.backups.keep_limit,
            )
            if isinstance(save_result, save_stage.SaveStageResult):
                report.save_sync = _summarize_save_stage(save_result, enabled=config.save_sync.enabled)
            deploy_firmware_to_emulators(config=config, index=index, dry_run=True, verbose=verbose)
            _converge_bootstrap_controller_state(
                config,
                index=index,
                dry_run=True,
                verbose=verbose,
                reseed_profiles=reseed_profiles,
            )
            report.ok = True
            return report

        _apply_downloads(
            config.server_url,
            plan,
            state,
            timeout_seconds=transfer_timeout,
            verbose=verbose,
            max_parallel_downloads=config.max_parallel_downloads,
        )
        report.downloads = _summarize_downloads(plan, completed=_summarize_downloads(plan).total_planned)
        save_result = save_stage.apply_save_stage(
            server_url=config.server_url,
            plan=plan,
            state=state,
            timeout_seconds=transfer_timeout,
            dry_run=False,
            verbose=verbose,
            backup_keep_limit=config.backups.keep_limit,
        )
        if isinstance(save_result, save_stage.SaveStageResult):
            report.save_sync = _summarize_save_stage(save_result, enabled=config.save_sync.enabled)
        deploy_firmware_to_emulators(config=config, index=index, dry_run=False, verbose=verbose)
        _converge_bootstrap_controller_state(
            config,
            index=index,
            dry_run=False,
            verbose=verbose,
            reseed_profiles=reseed_profiles,
        )

        if skip_steam:
            message = "Skipping Steam lifecycle and config updates (--skip-steam)"
            print(message)
            if message not in report.warnings:
                report.warnings.append(message)
            report.steam.skipped = True
            report.steam.reason = "--skip-steam"
        else:
            print("Applying Steam updates...")
            _apply_steam_updates(
                config,
                index=index,
                require_steam_closed=require_steam_closed,
                artwork_by_title=artwork_assignments,
                reopen_steam_after_update=not skip_steam_relaunch,
                reseed_profiles=reseed_profiles,
            )
            report.steam.applied = steam_context is not None
            report.steam.skipped = steam_context is None
            if steam_context is None and report.steam.reason is None:
                report.steam.reason = "steam-context-unavailable"

        prune_persisted_save_conflicts(state=state, plan=plan)
        mark_synced(state)
        mark_bootstrapped(state)
        save_state_atomic(config.state_path, state, keep_limit=config.backups.keep_limit)
        print("Sync completed")
        report.ok = True
        return report
    except Exception as exc:
        if not capture_errors:
            raise
        message = str(exc).strip() or exc.__class__.__name__
        if message not in report.errors:
            report.errors.append(message)
        return report


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
    report = run_sync_report(
        config,
        dry_run=dry_run,
        verbose=verbose,
        verify=verify,
        require_steam_closed=require_steam_closed,
        skip_steam=skip_steam,
        skip_steam_relaunch=skip_steam_relaunch,
        reseed_profiles=reseed_profiles,
        capture_errors=False,
    )
    return 0 if report.ok else 1
