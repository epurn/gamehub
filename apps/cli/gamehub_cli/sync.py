from __future__ import annotations

from collections import Counter
import json
import re
from pathlib import Path, PurePosixPath
import shlex
import sys
import time
from urllib.error import HTTPError, URLError
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
    redact_secret,
)
from .config import GamehubConfig
from .downloads import download_with_atomic_write
from .emulators import ensure_emulators, resolve_emulator_executable
from .firmware_deploy import deploy_firmware_to_emulators
from .planner import SyncPlan, create_sync_plan
from .retroarch_cores import ensure_retroarch_cores, resolve_retroarch_paths
from .state import SyncState, load_state, mark_synced, save_state_atomic
from .steam import (
    SteamContext,
    SteamArtworkAssignment,
    SteamShortcutSpec,
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

_RETROARCH_CORE_TOKEN_RE = re.compile(r"(?P<prefix>-L\s+)(?P<token>[^\s]+)")


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
    verbose: bool = False,
) -> None:
    firmware_total = len(plan.firmware_actions)
    content_total = len(plan.content_actions)
    print(f"Downloading files: firmware={firmware_total} content={content_total}")

    for index, action in enumerate(plan.firmware_actions, start=1):
        if verbose:
            print(f"download\tfirmware\t{index}/{firmware_total}\t{action.label}")
        download_with_atomic_write(server_url, action.url, action.destination, action.expected_sha256, timeout_seconds)
        state.firmware_checksums[action.content_id] = action.expected_sha256

    for index, action in enumerate(plan.content_actions, start=1):
        if verbose:
            print(f"download\t{action.kind}\t{index}/{content_total}\t{action.label}")
        download_with_atomic_write(server_url, action.url, action.destination, action.expected_sha256, timeout_seconds)
        state.downloaded_checksums[action.content_id] = action.expected_sha256


def _build_artwork_assignments(
    config: GamehubConfig,
    index: LibraryIndex,
    dry_run: bool,
    timeout_seconds: float,
    verbose: bool,
) -> dict[str, dict[str, Path]]:
    def _from_cache() -> dict[str, dict[str, Path]]:
        cached: dict[str, dict[str, Path]] = {}
        for title in index.titles:
            title_dir = config.sgdb_cache_dir / title.title_id
            if not title_dir.is_dir():
                continue
            files: dict[str, Path] = {}
            for kind in SGDB_ART_KINDS:
                candidates = sorted(
                    (path for path in title_dir.glob(f"{kind}-*") if path.is_file() and path.stat().st_size > 0),
                    key=lambda item: item.stat().st_mtime,
                    reverse=True,
                )
                if candidates:
                    files[kind] = candidates[0]
            if files:
                cached[title.title_id] = files
        return cached

    if not config.sgdb_api_key:
        cached_only = _from_cache()
        if cached_only:
            print(f"SGDB API key missing; using cached artwork for {len(cached_only)} titles")
            return cached_only
        if verbose:
            print("SGDB artwork disabled (no API key configured)")
        return {}

    enabled_kinds = tuple(kind for kind in config.sgdb_enabled_kinds if kind in SGDB_ART_KINDS)
    if not enabled_kinds:
        print("SGDB artwork disabled (no valid artwork kinds configured)")
        return {}

    if dry_run:
        dry_run_plan = build_lookup_plan(index.titles, enabled_kinds)
        print(
            f"SGDB dry-run: key={redact_secret(config.sgdb_api_key)} "
            f"titles={len(dry_run_plan)} kinds={','.join(enabled_kinds)}"
        )
        for entry in dry_run_plan:
            print(f"sgdb\tlookup\t{entry.title_name}\t{kinds_to_download(entry.kinds)}")
        return {}

    print(f"Starting SGDB artwork sync for {len(index.titles)} titles")

    def _progress_lookup(position: int, total: int, title_name: str) -> None:
        if verbose:
            print(f"sgdb\tlookup\t{position}/{total}\t{title_name}")

    with SgdbClient(config.sgdb_api_key, timeout_seconds=timeout_seconds) as client:
        pipeline = SgdbArtworkPipeline(client, cache_dir=config.sgdb_cache_dir, kinds=enabled_kinds)
        result = pipeline.sync(index.titles, progress_cb=_progress_lookup)

    if result.warnings:
        for warning in result.warnings:
            print(f"Warning: {warning}")
    print(f"SGDB artwork: lookups={result.lookups} downloaded={result.downloaded} cached={result.cached}")

    assignments: dict[str, dict[str, Path]] = {}
    for bundle in result.bundles:
        assignments[bundle.title_id] = bundle.files
    cache_fallback = _from_cache()
    fallback_count = 0
    for title_id, files in cache_fallback.items():
        if title_id in assignments:
            continue
        assignments[title_id] = files
        fallback_count += 1
    if fallback_count and verbose:
        print(f"SGDB cache fallback restored artwork for {fallback_count} titles")
    return assignments


def kinds_to_download(kinds: tuple[str, ...]) -> str:
    return ",".join(kinds)


def _from_rel_path(base: Path, rel_path: str) -> Path:
    rel = PurePosixPath(rel_path)
    return base.joinpath(*rel.parts)


def _bootstrap_firmware_dirs(config: GamehubConfig, index: LibraryIndex, dry_run: bool, verbose: bool) -> None:
    targets = [config.firmware_dir]
    targets.extend(config.firmware_dir / system.name for system in index.systems)

    unique_targets: list[Path] = []
    seen: set[Path] = set()
    for target in targets:
        if target in seen:
            continue
        seen.add(target)
        unique_targets.append(target)

    if dry_run:
        if verbose:
            for target in unique_targets:
                if not target.exists():
                    print(f"layout\tfirmware\tcreate\t{target}")
        return

    created = 0
    for target in unique_targets:
        if target.exists():
            continue
        target.mkdir(parents=True, exist_ok=True)
        created += 1
    if verbose and created > 0:
        print(f"Bootstrapped firmware directories: {created}")


def _normalize_linux_retroarch_launch_template(launch_template: str, config: GamehubConfig) -> str:
    if not sys.platform.startswith("linux"):
        return launch_template
    match = _RETROARCH_CORE_TOKEN_RE.search(launch_template)
    if not match:
        return launch_template

    raw_token = match.group("token").strip().strip('"').replace("\\", "/")
    core_name = raw_token.rsplit("/", 1)[-1]
    if core_name.endswith(".dll"):
        core_name = core_name[:-4]
    elif core_name.endswith(".so"):
        core_name = core_name[:-3]
    if not core_name.endswith("_libretro"):
        return launch_template

    core_filename = f"{core_name}.so"
    core_token = f"cores/{core_filename}"
    paths = resolve_retroarch_paths(
        explicit_cores_dir=config.linux.retroarch_cores_dir,
        explicit_info_dir=config.linux.retroarch_info_dir,
        explicit_cfg_path=config.linux.retroarch_cfg_path,
    )
    if paths is not None:
        core_token = (paths.cores_dir / core_filename).as_posix()

    replacement = f'{match.group("prefix")}"{core_token}"'
    return f"{launch_template[:match.start()]}{replacement}{launch_template[match.end() :]}"


def _is_flatpak_command(path_value: str, app_id: str) -> bool:
    normalized = path_value.strip().strip('"').replace("\\", "/").lower()
    app = app_id.casefold()
    return normalized.endswith(f"/{app}") or f"flatpak/exports/bin/{app}" in normalized


def _flatpak_visible_home_path(path: Path) -> str:
    value = path.as_posix()
    if value.startswith("/var/home/"):
        return "/home/" + value[len("/var/home/") :]
    return value


def _build_shortcut_specs(
    index: LibraryIndex,
    config: GamehubConfig,
) -> list[SteamShortcutSpec]:
    specs: list[SteamShortcutSpec] = []
    for title in sorted(index.titles, key=lambda item: (item.system, item.title_name.casefold(), item.title_id)):
        rom_path = _from_rel_path(config.library_dir, title.rom.rel_path)
        emulator_exe = resolve_emulator_executable(title.emulator)
        pcsx2_flatpak = (
            sys.platform.startswith("linux")
            and "pcsx2" in title.emulator.casefold()
            and _is_flatpak_command(emulator_exe, "net.pcsx2.PCSX2")
        )
        rom_for_launch = str(rom_path)
        if pcsx2_flatpak:
            rom_for_launch = _flatpak_visible_home_path(rom_path)
        launch_template = title.launch_template
        if "retroarch" in title.emulator.casefold():
            launch_template = _normalize_linux_retroarch_launch_template(launch_template, config)
        if pcsx2_flatpak and "--" not in launch_template and '"{rom}"' in launch_template:
            launch_template = launch_template.replace('"{rom}"', '-- "{rom}"', 1)
        launch_line = launch_template.format(emulator=emulator_exe, rom=rom_for_launch)
        parts = shlex.split(launch_line, posix=False)
        if parts:
            exe = parts[0]
            launch_options = " ".join(parts[1:])
        else:
            exe = emulator_exe
            launch_options = f'"{rom_path}"'
        start_dir = ""
        exe_path = Path(exe.strip('"'))
        if exe_path.parent != Path("."):
            start_dir = str(exe_path.parent)
        specs.append(
            SteamShortcutSpec(
                title_id=title.title_id,
                system=title.system,
                title_name=title.title_name,
                exe=exe,
                launch_options=launch_options,
                start_dir=start_dir,
                icon_path="",
            )
        )
    return specs


def _resolve_steam_context(config: GamehubConfig) -> SteamContext | None:
    userdata_dir = discover_userdata_dir(config.steam_userdata_dir)
    if userdata_dir is None:
        print("Steam userdata directory not found; skipping Steam updates")
        return None

    steam_id = discover_steam_id(userdata_dir, preferred_steam_id=config.steam_id)
    if steam_id is None:
        print("No Steam ID found in userdata; skipping Steam updates")
        return None

    return build_context(userdata_dir, steam_id, config.steam_exe)


def _is_retryable_index_status(status_code: int) -> bool:
    return status_code in {408, 429} or 500 <= status_code <= 599


def _is_retryable_index_fetch_error(exc: Exception) -> bool:
    if isinstance(exc, HTTPError):
        return _is_retryable_index_status(int(exc.code))
    if isinstance(exc, URLError):
        return True
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    if httpx is None:
        return False
    timeout_exception = getattr(httpx, "TimeoutException", None)
    transport_error = getattr(httpx, "TransportError", None)
    http_status_error = getattr(httpx, "HTTPStatusError", None)
    if timeout_exception is not None and isinstance(exc, timeout_exception):
        return True
    if transport_error is not None and isinstance(exc, transport_error):
        return True
    if http_status_error is not None and isinstance(exc, http_status_error):
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int):
            return _is_retryable_index_status(status_code)
    return False


def _fetch_index_with_retries(
    *,
    index_url: str,
    timeout_seconds: float,
    attempts: int,
    retry_backoff_seconds: float,
    verbose: bool,
) -> dict:
    total_attempts = max(1, int(attempts))
    last_error: Exception | None = None
    for attempt in range(1, total_attempts + 1):
        try:
            if verbose and total_attempts > 1:
                print(f"Fetching index attempt {attempt}/{total_attempts}")
            if httpx is not None:
                response = httpx.get(index_url, timeout=timeout_seconds)
                response.raise_for_status()
                return response.json()
            with urlopen(index_url, timeout=timeout_seconds) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            if attempt >= total_attempts or not _is_retryable_index_fetch_error(exc):
                raise
            delay = retry_backoff_seconds * (2 ** (attempt - 1))
            print(
                f"Warning: index fetch attempt {attempt}/{total_attempts} failed ({exc.__class__.__name__}). "
                f"Retrying in {delay:.1f}s..."
            )
            time.sleep(delay)
    if last_error is not None:
        raise last_error
    raise RuntimeError("Index fetch failed without an error")


def _apply_steam_updates(
    config: GamehubConfig,
    index: LibraryIndex,
    require_steam_closed: bool,
    artwork_by_title: dict[str, dict[str, Path]],
) -> None:
    context = _resolve_steam_context(config)
    if context is None:
        return
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

    shortcut_specs = _build_shortcut_specs(index, config)
    shortcut_result = upsert_shortcuts(context, shortcut_specs)
    print(
        "Steam shortcuts synced: "
        f"managed_titles={len(shortcut_result.app_ids_by_title)} total_shortcuts={shortcut_result.total_shortcuts}"
    )
    if not shortcut_result.app_ids_by_system:
        print("Warning: no GAMEHUB appids were derived from persisted shortcuts")
    local_update_count = update_collections(context, shortcut_result.app_ids_by_system)
    cloud_update_count = update_cloud_collections(context, shortcut_result.app_ids_by_system)
    update_count = local_update_count + cloud_update_count
    if update_count:
        details: list[str] = []
        if local_update_count:
            details.append(f"localconfig={local_update_count}")
        if cloud_update_count:
            details.append(f"cloud={cloud_update_count}")
        suffix = f" ({', '.join(details)})" if details else ""
        print(f"Updated {update_count} Steam collections{suffix}")
    else:
        print("Steam collections unchanged")

    artwork_assignments: list[SteamArtworkAssignment] = []
    for title_id, files in artwork_by_title.items():
        app_id = shortcut_result.app_ids_by_title.get(title_id)
        if not app_id:
            continue
        artwork_assignments.append(SteamArtworkAssignment(steam_app_id=app_id, assets_by_kind=files))
    if artwork_by_title and not artwork_assignments:
        print("Warning: SGDB artwork resolved, but no matching GAMEHUB shortcuts were found for appid mapping")
    copied = copy_grid_art(context, artwork_assignments)
    pruned = prune_grid_noncanonical_variants(context, list(shortcut_result.app_ids_by_title.values()))
    if copied:
        print(f"Copied {len(copied)} artwork files into Steam grid")
    elif artwork_assignments:
        print("Warning: artwork assignments existed but no files were copied")
    if pruned:
        print(f"Pruned {pruned} non-canonical Steam grid artwork files")
    reopened = reopen_steam(context)
    if not reopened:
        print("Warning: Steam relaunch command was not found; start Steam manually")


def run_sync(
    config: GamehubConfig,
    dry_run: bool,
    verbose: bool,
    verify: bool,
    require_steam_closed: bool,
    skip_steam: bool = False,
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

    _apply_downloads(config.server_url, plan, state, timeout_seconds=transfer_timeout, verbose=verbose)
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
        )
    mark_synced(state)
    save_state_atomic(config.state_path, state)
    print("Sync completed")
    return 0
