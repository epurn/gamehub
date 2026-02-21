from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from gamehub_common.ids import sha256_file
from gamehub_common.models import LibraryIndex

from .config import GamehubConfig
from .common.paths import from_rel_path
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

    @property
    def total_actions(self) -> int:
        return len(self.firmware_actions) + len(self.content_actions)


def _is_file_valid(path: Path, expected_sha256: str, verify: bool, expected_size_bytes: int | None = None) -> bool:
    if not path.exists():
        return False
    if expected_size_bytes is not None and path.stat().st_size != expected_size_bytes:
        return False
    if verify:
        return sha256_file(path) == expected_sha256
    return True


def create_sync_plan(index: LibraryIndex, config: GamehubConfig, state: SyncState, verify: bool = False) -> SyncPlan:
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

        rom_path = from_rel_path(config.library_dir, title.rom.rel_path, preferred_root="roms")
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

    return plan
