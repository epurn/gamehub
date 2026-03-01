from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urljoin

from gamehub_common.models import LibraryIndex

from ..common.config import GamehubConfig
from . import index as sync_index
from .planner import PlanAction, SyncPlan, create_sync_plan
from .state import load_state


@dataclass(frozen=True)
class SyncDiagnosticsSnapshot:
    index: LibraryIndex
    plan: SyncPlan


def _transfer_timeout_seconds(verbose: bool) -> float:
    return 60.0 if verbose else 30.0


def build_sync_diagnostics_snapshot(
    config: GamehubConfig,
    *,
    verify: bool,
    verbose: bool,
) -> SyncDiagnosticsSnapshot:
    print("Loading local sync state...")
    state = load_state(config.state_path)
    transfer_timeout = _transfer_timeout_seconds(verbose)
    index_timeout = config.index_timeout_seconds if config.index_timeout_seconds is not None else transfer_timeout
    index_url = urljoin(config.server_url.rstrip("/") + "/", "v1/index")
    print(f"Fetching index: {index_url}")
    raw_index = sync_index.fetch_index_with_retries(
        index_url=index_url,
        timeout_seconds=index_timeout,
        attempts=config.index_fetch_attempts,
        retry_backoff_seconds=config.index_retry_backoff_seconds,
        verbose=verbose,
        http_client_module=sync_index.httpx,
        sleep_func=time.sleep,
    )
    index = LibraryIndex.model_validate(raw_index)
    plan = create_sync_plan(index=index, config=config, state=state, verify=verify)
    return SyncDiagnosticsSnapshot(index=index, plan=plan)


def _sorted_actions(actions: list[PlanAction]) -> list[PlanAction]:
    return sorted(
        actions,
        key=lambda action: (
            action.kind,
            action.system,
            action.label.casefold(),
            str(action.destination).replace("\\", "/").casefold(),
        ),
    )


def _print_plan_actions(prefix: str, actions: list[PlanAction]) -> None:
    for action in _sorted_actions(actions):
        print(
            f"{prefix}\tstatus=drift\tkind={action.kind}\tsystem={action.system}\t"
            f"item={action.label}\ttarget={action.destination}"
        )


def run_roms_doctor(
    config: GamehubConfig,
    *,
    verify: bool,
    verbose: bool,
    snapshot: SyncDiagnosticsSnapshot | None = None,
) -> int:
    active_snapshot = snapshot or build_sync_diagnostics_snapshot(config, verify=verify, verbose=verbose)
    plan = active_snapshot.plan
    print(f"rom-doctor\tcontent_actions={len(plan.content_actions)}\tskipped_titles={plan.skipped_titles}")
    for system_name, reason in sorted(plan.blocked_systems.items()):
        print(f"rom-doctor\tblocked-system\tsystem={system_name}\treason={reason}")
    _print_plan_actions("rom-doctor", plan.content_actions)
    print(
        "rom-doctor\tsummary\t"
        f"content_actions={len(plan.content_actions)}\t"
        f"skipped_titles={plan.skipped_titles}\t"
        f"blocked_systems={len(plan.blocked_systems)}"
    )
    return 1 if plan.content_actions or plan.skipped_titles > 0 else 0


def run_firmware_doctor(
    config: GamehubConfig,
    *,
    verify: bool,
    verbose: bool,
    snapshot: SyncDiagnosticsSnapshot | None = None,
) -> int:
    active_snapshot = snapshot or build_sync_diagnostics_snapshot(config, verify=verify, verbose=verbose)
    plan = active_snapshot.plan
    print(
        f"firmware-doctor\tfirmware_actions={len(plan.firmware_actions)}\tblocked_systems={len(plan.blocked_systems)}"
    )
    _print_plan_actions("firmware-doctor", plan.firmware_actions)
    for system_name, reason in sorted(plan.blocked_systems.items()):
        print(f"firmware-doctor\tblocked-system\tsystem={system_name}\treason={reason}")
    print(
        "firmware-doctor\tsummary\t"
        f"firmware_actions={len(plan.firmware_actions)}\t"
        f"blocked_systems={len(plan.blocked_systems)}"
    )
    return 1 if plan.firmware_actions or plan.blocked_systems else 0
