from __future__ import annotations

import inspect
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from gamehub_common.models import LibraryIndex

from ..common.config import GamehubConfig
from . import downloads
from .downloads import download_with_atomic_write
from .planner import PlanAction, SyncPlan
from .state import SyncState

DEFAULT_MAX_PARALLEL_DOWNLOADS = 4


def print_plan(plan: SyncPlan) -> None:
    print("GAMEHUB Sync Plan")
    print("kind\tsystem\titem\tdestination\tsize")
    for action in [*plan.firmware_actions, *plan.content_actions]:
        print(f"{action.kind}\t{action.system}\t{action.label}\t{action.destination}\t{action.size_bytes}")
    for save_action in plan.save_actions:
        destination = save_action.destination if save_action.destination is not None else "<save-path-unavailable>"
        print(
            "save:"
            f"{save_action.decision}\t"
            f"{save_action.system}\t"
            f"{save_action.title_id}:{save_action.kind}\t"
            f"{destination}\t"
            f"{save_action.size_bytes}"
        )
    print("")
    count_by_kind = Counter(action.kind for action in [*plan.firmware_actions, *plan.content_actions])
    count_by_kind.update(f"save:{action.decision}" for action in plan.save_actions)
    print("Summary")
    print(f"Total actions: {plan.total_actions}")
    print(f"Blocked systems: {len(plan.blocked_systems)}")
    print(f"Skipped titles: {plan.skipped_titles}")
    for kind, count in sorted(count_by_kind.items()):
        print(f"{kind}: {count}")


def apply_downloads(
    server_url: str,
    plan: SyncPlan,
    state: SyncState,
    timeout_seconds: float,
    verbose: bool = False,
    max_parallel_downloads: int = DEFAULT_MAX_PARALLEL_DOWNLOADS,
) -> None:
    firmware_total = len(plan.firmware_actions)
    content_total = len(plan.content_actions)
    print(f"Downloading files: firmware={firmware_total} content={content_total}")

    supports_http_client = _supports_http_client_kwarg(download_with_atomic_write)
    http_client = _build_http_client(
        timeout_seconds=timeout_seconds,
        max_parallel_downloads=max_parallel_downloads,
        supports_http_client=supports_http_client,
    )

    try:
        _apply_download_group(
            server_url=server_url,
            actions=plan.firmware_actions,
            timeout_seconds=timeout_seconds,
            verbose=verbose,
            max_parallel_downloads=max_parallel_downloads,
            state_checksums=state.firmware_checksums,
            http_client=http_client,
            supports_http_client=supports_http_client,
            total_count=firmware_total,
        )
        _apply_download_group(
            server_url=server_url,
            actions=plan.content_actions,
            timeout_seconds=timeout_seconds,
            verbose=verbose,
            max_parallel_downloads=max_parallel_downloads,
            state_checksums=state.downloaded_checksums,
            http_client=http_client,
            supports_http_client=supports_http_client,
            total_count=content_total,
        )
    finally:
        if http_client is not None:
            http_client.close()


def _supports_http_client_kwarg(download_callable: Callable[..., object]) -> bool:
    try:
        params = inspect.signature(download_callable).parameters
    except (TypeError, ValueError):
        return False
    return "http_client" in params


def _build_http_client(
    timeout_seconds: float,
    max_parallel_downloads: int,
    supports_http_client: bool,
) -> Any | None:
    if not supports_http_client:
        return None
    if downloads.httpx is None:
        return None
    max_parallel = max(1, int(max_parallel_downloads))
    connection_limit = max(8, max_parallel * 4)
    return downloads.httpx.Client(
        timeout=timeout_seconds,
        limits=downloads.httpx.Limits(
            max_keepalive_connections=connection_limit,
            max_connections=connection_limit,
        ),
    )


def _download_one(
    *,
    server_url: str,
    action: PlanAction,
    timeout_seconds: float,
    http_client: Any | None,
    supports_http_client: bool,
) -> None:
    if supports_http_client and http_client is not None:
        download_with_atomic_write(
            server_url,
            action.url,
            action.destination,
            action.expected_sha256,
            timeout_seconds,
            http_client=http_client,
        )
        return
    download_with_atomic_write(server_url, action.url, action.destination, action.expected_sha256, timeout_seconds)


def _apply_download_group(
    *,
    server_url: str,
    actions: list[PlanAction],
    timeout_seconds: float,
    verbose: bool,
    max_parallel_downloads: int,
    state_checksums: dict[str, str],
    http_client: Any | None,
    supports_http_client: bool,
    total_count: int,
) -> None:
    if not actions:
        return
    worker_count = min(max(1, int(max_parallel_downloads)), len(actions))
    if worker_count <= 1:
        for index, action in enumerate(actions, start=1):
            if verbose:
                print(f"download\t{action.kind}\t{index}/{total_count}\t{action.label}")
            _download_one(
                server_url=server_url,
                action=action,
                timeout_seconds=timeout_seconds,
                http_client=http_client,
                supports_http_client=supports_http_client,
            )
            state_checksums[action.content_id] = action.expected_sha256
        return

    if verbose:
        print(f"download\tparallel\tworkers={worker_count}\tactions={len(actions)}")
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        future_by_action: dict[Future[None], PlanAction] = {}
        for action in actions:
            future = pool.submit(
                _download_one,
                server_url=server_url,
                action=action,
                timeout_seconds=timeout_seconds,
                http_client=http_client,
                supports_http_client=supports_http_client,
            )
            future_by_action[future] = action
        completed = 0
        for future in as_completed(future_by_action):
            action = future_by_action[future]
            future.result()
            completed += 1
            state_checksums[action.content_id] = action.expected_sha256
            if verbose:
                print(f"download\t{action.kind}\t{completed}/{total_count}\t{action.label}")


def bootstrap_firmware_dirs(config: GamehubConfig, index: LibraryIndex, dry_run: bool, verbose: bool) -> None:
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
