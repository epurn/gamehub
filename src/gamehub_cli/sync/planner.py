from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from gamehub_common.ids import sha256_file
from gamehub_common.models import LibraryIndex, SaveBindingCatalog, SaveBindingSpec

from ..common.config import GamehubConfig
from ..common.paths import from_rel_path, resolve_rom_destination
from ..common.save_sync import (
    canonical_suffix_for_save,
    classify_save_action,
    local_file_sha256,
    save_binding_id_for_save,
    to_utc_timestamp,
)
from ..emulators.save_resolution import (
    LocalSaveCandidate,
    discover_local_exact_save_candidates,
    resolve_local_save_destination,
)
from .state import SyncState


@dataclass(frozen=True)
class PlanAction:
    kind: str
    system: str
    label: str
    url: str
    destination: Path
    expected_sha256: str
    content_id: str
    size_bytes: int = 0


@dataclass
class SyncPlan:
    firmware_actions: list[PlanAction] = field(default_factory=list)
    content_actions: list[PlanAction] = field(default_factory=list)
    blocked_systems: dict[str, str] = field(default_factory=dict)
    skipped_titles: int = 0
    save_actions: list["SavePlanAction"] = field(default_factory=list)

    @property
    def total_actions(self) -> int:
        return len(self.firmware_actions) + len(self.content_actions) + len(self.save_actions)


@dataclass(frozen=True)
class SavePlanAction:
    save_id: str
    binding_id: str
    title_id: str
    system: str
    kind: str
    decision: str
    reason: str
    url: str
    destination: Path | None
    canonical_suffix: str
    expected_sha256: str
    size_bytes: int
    remote_updated_at: str
    local_sha256: str | None = None


def _is_file_valid(path: Path, expected_sha256: str, verify: bool, expected_size_bytes: int | None = None) -> bool:
    if not path.exists():
        return False
    if expected_size_bytes is not None and path.stat().st_size != expected_size_bytes:
        return False
    if verify:
        return sha256_file(path) == expected_sha256
    return True


def _active_save_bindings(
    save_bindings: SaveBindingCatalog | None,
    *,
    config: GamehubConfig,
) -> tuple[SaveBindingSpec, ...]:
    if save_bindings is None or not config.save_sync.enabled:
        return ()
    bindings = tuple(save_bindings.bindings)
    if not config.save_sync.systems:
        return bindings
    return tuple(binding for binding in bindings if binding.system.upper() in config.save_sync.systems)


def _plan_local_only_exact_saves(
    *,
    config: GamehubConfig,
    remote_save_ids: set[str],
    save_bindings: tuple[SaveBindingSpec, ...],
) -> list[tuple[LocalSaveCandidate, str, str]]:
    planned: list[tuple[LocalSaveCandidate, str, str]] = []
    for candidate in discover_local_exact_save_candidates(save_bindings):
        if candidate.save_id in remote_save_ids:
            continue
        if config.save_sync.mode == "download":
            planned.append((candidate, "skip", "download-mode-local-new"))
        else:
            planned.append((candidate, "upload_new", "local-only-create"))
    return planned


def create_sync_plan(
    index: LibraryIndex,
    config: GamehubConfig,
    state: SyncState,
    verify: bool = False,
    *,
    save_bindings: SaveBindingCatalog | None = None,
) -> SyncPlan:
    plan = SyncPlan()
    system_map = {system.name: system for system in index.systems}

    for system_name in sorted(system_map):
        system = system_map[system_name]
        for firmware in system.firmware:
            key = f"{system_name}/{firmware.filename}"
            destination = config.firmware_dir / system_name / firmware.filename
            known_fw_sha = state.firmware_checksums.get(key)
            firmware_ok = _is_file_valid(destination, firmware.sha256, verify, expected_size_bytes=None) and (
                known_fw_sha is None or known_fw_sha == firmware.sha256
            )
            if not firmware_ok:
                plan.firmware_actions.append(
                    PlanAction(
                        kind="firmware",
                        system=system_name,
                        label=firmware.filename,
                        url=f"/v1/firmware/{system_name}/{firmware.filename}",
                        destination=destination,
                        expected_sha256=firmware.sha256,
                        content_id=key,
                    )
                )
                if firmware.required:
                    plan.blocked_systems[system_name] = "Missing required firmware"

    for title in index.titles:
        if title.system in plan.blocked_systems:
            plan.skipped_titles += 1
            continue

        rom_path = resolve_rom_destination(
            library_dir=config.library_dir,
            roms_dir=config.roms_dir,
            rel_path=title.rom.rel_path,
        )
        known_sha = state.downloaded_checksums.get(title.rom.file_id)
        rom_ok = _is_file_valid(rom_path, title.rom.sha256, verify, expected_size_bytes=title.rom.size_bytes) and (
            known_sha is None or known_sha == title.rom.sha256
        )
        if not rom_ok:
            plan.content_actions.append(
                PlanAction(
                    kind="rom",
                    system=title.system,
                    label=f"{title.title_name} ROM",
                    url=f"/v1/files/{title.rom.file_id}",
                    destination=rom_path,
                    expected_sha256=title.rom.sha256,
                    content_id=title.rom.file_id,
                    size_bytes=title.rom.size_bytes,
                )
            )

        for asset in title.assets:
            asset_path = from_rel_path(config.library_dir, asset.rel_path)
            known_asset_sha = state.downloaded_checksums.get(asset.asset_id)
            asset_ok = _is_file_valid(asset_path, asset.sha256, verify, expected_size_bytes=asset.size_bytes) and (
                known_asset_sha is None or known_asset_sha == asset.sha256
            )
            if asset_ok:
                continue
            plan.content_actions.append(
                PlanAction(
                    kind=f"asset:{asset.kind}",
                    system=title.system,
                    label=f"{title.title_name} {asset.kind}",
                    url=f"/v1/assets/{asset.asset_id}",
                    destination=asset_path,
                    expected_sha256=asset.sha256,
                    content_id=asset.asset_id,
                    size_bytes=asset.size_bytes,
                )
            )

    active_bindings = _active_save_bindings(save_bindings, config=config)
    remote_save_ids = {save.save_id for save in index.saves}
    for candidate, decision, reason in _plan_local_only_exact_saves(
        config=config,
        remote_save_ids=remote_save_ids,
        save_bindings=active_bindings,
    ):
        plan.save_actions.append(
            SavePlanAction(
                save_id=candidate.save_id,
                binding_id=candidate.binding_id,
                title_id=candidate.title_id,
                system=candidate.system,
                kind=candidate.kind,
                decision=decision,
                reason=reason,
                url=f"/v1/saves/{candidate.save_id}",
                destination=candidate.path,
                canonical_suffix=candidate.canonical_suffix,
                expected_sha256=candidate.sha256,
                size_bytes=candidate.size_bytes,
                remote_updated_at="",
                local_sha256=candidate.sha256,
            )
        )

    for save in sorted(index.saves, key=lambda item: (item.system, item.title_id, item.rel_path, item.save_id)):
        save_destination = resolve_local_save_destination(save, binding_roots=state.save_binding_roots)
        if not config.save_sync.enabled:
            decision, reason = "skip", "save-sync-disabled"
            local_sha = None
        elif config.save_sync.systems and save.system.upper() not in config.save_sync.systems:
            decision, reason = "skip", "system-filtered"
            local_sha = None
        elif save_destination is None:
            decision, reason = "skip", "save-path-unavailable"
            local_sha = None
        else:
            local_sha = local_file_sha256(save_destination)
            lineage = state.save_lineage.get(save.save_id, {})
            decision, reason = classify_save_action(
                save_sha256=save.sha256,
                local_sha256=local_sha,
                mode=config.save_sync.mode,
                conflict_policy=config.save_sync.conflict_policy,
                lineage_local_sha=lineage.get("local_sha256"),
                lineage_remote_sha=lineage.get("remote_sha256"),
            )

        plan.save_actions.append(
            SavePlanAction(
                save_id=save.save_id,
                binding_id=save_binding_id_for_save(save),
                title_id=save.title_id,
                system=save.system,
                kind=save.kind,
                decision=decision,
                reason=reason,
                url=f"/v1/saves/{save.save_id}",
                destination=save_destination,
                canonical_suffix=canonical_suffix_for_save(save),
                expected_sha256=save.sha256,
                size_bytes=save.size_bytes,
                remote_updated_at=to_utc_timestamp(save.updated_at),
                local_sha256=local_sha,
            )
        )

    plan.save_actions.sort(
        key=lambda item: (item.system, item.title_id, item.kind, item.decision, item.canonical_suffix, item.save_id)
    )
    return plan
