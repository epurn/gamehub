from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable

from gamehub_common.models import LibraryIndex

from ..common.config import GamehubConfig
from ..common.config_edit import read_qsettings_key, upsert_qsettings_key
from ..common.fsops import DEFAULT_BACKUP_KEEP_LIMIT, prune_backup_family, replace_file
from ..firmware.pcsx2_ini import read_ini_lines
from ..firmware.targets import default_pcsx2_ini_path
from .apply_azahar import azahar_target_config_paths
from .apply_dolphin import dolphin_target_config_dirs
from .apply_ini import apply_managed_ini_sections, parse_ini_sections, write_controller_config_lines_atomic
from .managed_metadata import (
    MANAGED_METADATA_FILENAME,
    ManagedMetadataEntry,
    read_managed_metadata_entry,
    sha256_text,
    utc_now_iso,
    write_managed_metadata_entry,
)
from .profiles import (
    DEFAULT_PROFILE_TEXTS,
    PROFILE_KBM,
    PROFILE_XBOX_1P,
    PROFILE_XBOX_2P,
    azahar_managed_shortcut_qsettings,
    azahar_sdl_stick_qsettings,
    resolve_profiles_root,
    write_profile_text_atomic,
)

_KNOWN_EMULATOR_FAMILIES = ("pcsx2", "dolphin", "azahar")
_UNMANAGED_BACKUP_DIRNAME = ".gamehub-unmanaged-backups"
logger = logging.getLogger(__name__)


class ControllerOwnership(str, Enum):
    MANAGED = "managed"
    ASSISTED = "assisted"
    UNMANAGED = "unmanaged"


class ControllerTargetStatus(str, Enum):
    OK = "ok"
    MISSING = "missing"
    DRIFT = "drift"
    REPAIRED = "repaired"
    UNMANAGED = "unmanaged"
    ERROR = "error"


@dataclass(frozen=True)
class ControllerRuntimeSelectionRule:
    controller_count: str
    profile_name: str


@dataclass(frozen=True)
class ManagedProfileTarget:
    emulator_name: str
    profile_name: str
    filename: str
    destination: Path
    payload: str
    source_template: str


@dataclass(frozen=True)
class AssistedIniTarget:
    name: str
    destination: Path
    sections: dict[str, dict[str, str]]
    source_template: str


@dataclass(frozen=True)
class AssistedQSettingsTarget:
    name: str
    destination: Path
    keys: dict[str, str]
    source_template: str


@dataclass(frozen=True)
class ControllerConvergencePlan:
    runtime_selection: tuple[ControllerRuntimeSelectionRule, ...]
    managed_profile_targets: tuple[ManagedProfileTarget, ...]
    assisted_ini_targets: tuple[AssistedIniTarget, ...]
    assisted_qsettings_targets: tuple[AssistedQSettingsTarget, ...]
    steam_roots: tuple[Path, ...]
    steam_discovery_note: str | None = None

    @property
    def total_targets(self) -> int:
        return len(self.managed_profile_targets) + len(self.assisted_ini_targets) + len(self.assisted_qsettings_targets)


@dataclass(frozen=True)
class ControllerConvergenceFinding:
    ownership: ControllerOwnership
    status: ControllerTargetStatus
    target_path: Path
    detail: str
    repairable: bool
    repaired: bool


@dataclass
class ControllerConvergenceResult:
    findings: list[ControllerConvergenceFinding] = field(default_factory=list)
    total_targets: int = 0
    repaired_count: int = 0
    unchanged_count: int = 0
    drift_count: int = 0
    unmanaged_count: int = 0
    error_count: int = 0

    @property
    def unresolved_count(self) -> int:
        return self.drift_count + self.unmanaged_count + self.error_count


def _runtime_selection_rules() -> tuple[ControllerRuntimeSelectionRule, ...]:
    return (
        ControllerRuntimeSelectionRule(controller_count="0", profile_name=PROFILE_KBM),
        ControllerRuntimeSelectionRule(controller_count="1", profile_name=PROFILE_XBOX_1P),
        ControllerRuntimeSelectionRule(controller_count="2+", profile_name=PROFILE_XBOX_2P),
    )


def _normalize_emulator_family(raw: str) -> str | None:
    normalized = raw.casefold()
    for family in _KNOWN_EMULATOR_FAMILIES:
        if family in normalized:
            return family
    return None


def emulator_families_for_index(index: LibraryIndex) -> set[str]:
    families: set[str] = set()
    for title in index.titles:
        family = _normalize_emulator_family(title.emulator)
        if family is not None:
            families.add(family)
    return families


def _managed_source_template(*, emulator_name: str, profile_name: str, filename: str) -> str:
    return f"profile://{emulator_name}/{profile_name}/{filename}"


def _unique_paths(paths: list[Path]) -> tuple[Path, ...]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        marker = str(path).replace("\\", "/").casefold()
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(path)
    return tuple(unique)


def build_controller_convergence_plan(
    config: GamehubConfig,
    *,
    emulator_families: set[str] | None = None,
    steam_roots: tuple[Path, ...] = (),
    steam_discovery_note: str | None = None,
) -> ControllerConvergencePlan:
    families = (
        {value.casefold() for value in emulator_families if value.casefold() in _KNOWN_EMULATOR_FAMILIES}
        if emulator_families is not None
        else set(_KNOWN_EMULATOR_FAMILIES)
    )
    profile_root = resolve_profiles_root(config)

    managed_profile_targets: list[ManagedProfileTarget] = []
    for emulator_name in sorted(DEFAULT_PROFILE_TEXTS):
        if emulator_name not in families:
            continue
        profiles = DEFAULT_PROFILE_TEXTS[emulator_name]
        for profile_name in sorted(profiles):
            files = profiles[profile_name]
            for filename in sorted(files):
                payload = files[filename]
                managed_profile_targets.append(
                    ManagedProfileTarget(
                        emulator_name=emulator_name,
                        profile_name=profile_name,
                        filename=filename,
                        destination=profile_root / emulator_name / profile_name / filename,
                        payload=payload,
                        source_template=_managed_source_template(
                            emulator_name=emulator_name,
                            profile_name=profile_name,
                            filename=filename,
                        ),
                    )
                )

    assisted_ini_targets: list[AssistedIniTarget] = []
    if "pcsx2" in families:
        assisted_ini_targets.append(
            AssistedIniTarget(
                name="pcsx2-runtime",
                destination=default_pcsx2_ini_path(config=config),
                sections={
                    "InputSources": {"SDL": "true"},
                    "UI": {"ConfirmShutdown": "false"},
                },
                source_template="runtime://pcsx2/safe-controller-state",
            )
        )
    if "dolphin" in families:
        for config_dir in dolphin_target_config_dirs(config):
            assisted_ini_targets.append(
                AssistedIniTarget(
                    name="dolphin-runtime",
                    destination=config_dir / "Dolphin.ini",
                    sections={
                        "Core": {"SIDevice0": "6", "SIDevice1": "6"},
                        "Controls": {"WiimoteSource0": "1", "WiimoteSource1": "1"},
                    },
                    source_template="runtime://dolphin/safe-controller-state",
                )
            )

    assisted_qsettings_targets: list[AssistedQSettingsTarget] = []
    if "azahar" in families:
        for path in azahar_target_config_paths():
            assisted_qsettings_targets.append(
                AssistedQSettingsTarget(
                    name="azahar-runtime",
                    destination=path,
                    keys={
                        "profile": "0",
                        r"profile\default": "true",
                        **dict(azahar_managed_shortcut_qsettings()),
                        **dict(azahar_sdl_stick_qsettings(port=0)),
                    },
                    source_template="runtime://azahar/safe-controller-state",
                )
            )

    return ControllerConvergencePlan(
        runtime_selection=_runtime_selection_rules(),
        managed_profile_targets=tuple(managed_profile_targets),
        assisted_ini_targets=tuple(assisted_ini_targets),
        assisted_qsettings_targets=tuple(assisted_qsettings_targets),
        steam_roots=_unique_paths(list(steam_roots)),
        steam_discovery_note=steam_discovery_note,
    )


def format_runtime_selection_rules(rules: tuple[ControllerRuntimeSelectionRule, ...]) -> str:
    return ",".join(f"{rule.controller_count}->{rule.profile_name}" for rule in rules)


def _archive_unmanaged_profile_file(path: Path, *, keep_limit: int = DEFAULT_BACKUP_KEEP_LIMIT) -> Path:
    backup_root = path.parent / _UNMANAGED_BACKUP_DIRNAME
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    candidate = backup_root / f"{path.name}.{stamp}.bak"
    suffix = 1
    while candidate.exists():
        candidate = backup_root / f"{path.name}.{stamp}.{suffix}.bak"
        suffix += 1
    replace_file(path, candidate)
    for pruned_path in prune_backup_family(backup_root, path.name, keep_limit=keep_limit):
        logger.info("controller unmanaged backup pruned path=%s pruned_backup=%s", path, pruned_path)
    return candidate


def _record_managed_metadata(
    target: Path,
    spec: ManagedProfileTarget,
    *,
    keep_limit: int = DEFAULT_BACKUP_KEEP_LIMIT,
) -> None:
    write_managed_metadata_entry(
        target,
        ManagedMetadataEntry(
            source_profile=spec.profile_name,
            source_template=spec.source_template,
            timestamp_utc=utc_now_iso(),
            fingerprint_sha256=sha256_text(spec.payload),
            ownership=ControllerOwnership.MANAGED.value,
        ),
        keep_limit=keep_limit,
    )


def _metadata_is_managed_target(entry: ManagedMetadataEntry | None, spec: ManagedProfileTarget) -> bool:
    if entry is None:
        return False
    if entry.ownership != ControllerOwnership.MANAGED.value:
        return False
    if entry.source_profile != spec.profile_name:
        return False
    if entry.source_template != spec.source_template:
        return False
    return True


def _evaluate_managed_target(
    spec: ManagedProfileTarget,
    *,
    apply: bool,
    force_managed: bool,
    force_unmanaged: bool,
    keep_limit: int,
) -> ControllerConvergenceFinding:
    path = spec.destination
    expected_sha = sha256_text(spec.payload)
    metadata_entry, metadata_error = read_managed_metadata_entry(path)

    if not path.exists():
        if apply:
            write_profile_text_atomic(path, spec.payload, keep_limit=keep_limit)
            _record_managed_metadata(path, spec, keep_limit=keep_limit)
            return ControllerConvergenceFinding(
                ownership=ControllerOwnership.MANAGED,
                status=ControllerTargetStatus.REPAIRED,
                target_path=path,
                detail="missing managed profile created",
                repairable=True,
                repaired=True,
            )
        return ControllerConvergenceFinding(
            ownership=ControllerOwnership.MANAGED,
            status=ControllerTargetStatus.MISSING,
            target_path=path,
            detail="missing managed profile file",
            repairable=True,
            repaired=False,
        )

    try:
        current_text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return ControllerConvergenceFinding(
            ownership=ControllerOwnership.MANAGED,
            status=ControllerTargetStatus.ERROR,
            target_path=path,
            detail=f"failed reading managed profile: {exc}",
            repairable=False,
            repaired=False,
        )
    current_sha = sha256_text(current_text)
    metadata_owned = _metadata_is_managed_target(metadata_entry, spec)
    metadata_fingerprint_ok = (
        metadata_owned and metadata_entry is not None and metadata_entry.fingerprint_sha256 == current_sha
    )

    if current_sha == expected_sha:
        if metadata_fingerprint_ok:
            return ControllerConvergenceFinding(
                ownership=ControllerOwnership.MANAGED,
                status=ControllerTargetStatus.OK,
                target_path=path,
                detail="managed profile matches expected state",
                repairable=False,
                repaired=False,
            )
        if apply:
            _record_managed_metadata(path, spec)
            detail = "managed profile metadata refreshed"
            if metadata_error:
                detail = f"{detail} ({metadata_error})"
            return ControllerConvergenceFinding(
                ownership=ControllerOwnership.MANAGED,
                status=ControllerTargetStatus.REPAIRED,
                target_path=path,
                detail=detail,
                repairable=True,
                repaired=True,
            )
        detail = "managed profile metadata drift detected"
        if metadata_error:
            detail = f"{detail} ({metadata_error})"
        return ControllerConvergenceFinding(
            ownership=ControllerOwnership.MANAGED,
            status=ControllerTargetStatus.DRIFT,
            target_path=path,
            detail=detail,
            repairable=True,
            repaired=False,
        )

    if force_managed or metadata_owned:
        if apply:
            write_profile_text_atomic(path, spec.payload, backup_existing=True, keep_limit=keep_limit)
            _record_managed_metadata(path, spec, keep_limit=keep_limit)
            return ControllerConvergenceFinding(
                ownership=ControllerOwnership.MANAGED,
                status=ControllerTargetStatus.REPAIRED,
                target_path=path,
                detail="managed profile drift repaired",
                repairable=True,
                repaired=True,
            )
        return ControllerConvergenceFinding(
            ownership=ControllerOwnership.MANAGED,
            status=ControllerTargetStatus.DRIFT,
            target_path=path,
            detail="managed profile drift detected",
            repairable=True,
            repaired=False,
        )

    if apply and force_unmanaged:
        backup_path = _archive_unmanaged_profile_file(path, keep_limit=keep_limit)
        write_profile_text_atomic(path, spec.payload, keep_limit=keep_limit)
        _record_managed_metadata(path, spec, keep_limit=keep_limit)
        return ControllerConvergenceFinding(
            ownership=ControllerOwnership.MANAGED,
            status=ControllerTargetStatus.REPAIRED,
            target_path=path,
            detail=f"unmanaged profile archived to {backup_path} and replaced with managed baseline",
            repairable=True,
            repaired=True,
        )

    detail = "profile differs from managed baseline but is not marked as managed"
    if metadata_error:
        detail = f"{detail} ({metadata_error})"
    return ControllerConvergenceFinding(
        ownership=ControllerOwnership.UNMANAGED,
        status=ControllerTargetStatus.UNMANAGED,
        target_path=path,
        detail=detail,
        repairable=force_unmanaged,
        repaired=False,
    )


def _evaluate_assisted_ini_target(
    spec: AssistedIniTarget,
    *,
    apply: bool,
    keep_limit: int,
) -> ControllerConvergenceFinding:
    path = spec.destination
    if path.exists():
        existing_sections = parse_ini_sections(read_ini_lines(path))
    else:
        existing_sections = {}

    drift_keys: list[str] = []
    for section_name, keys in spec.sections.items():
        current = existing_sections.get(section_name, {})
        for key, desired in keys.items():
            if current.get(key) != desired:
                drift_keys.append(f"{section_name}/{key}")

    if not drift_keys:
        return ControllerConvergenceFinding(
            ownership=ControllerOwnership.ASSISTED,
            status=ControllerTargetStatus.OK,
            target_path=path,
            detail=f"{spec.name} assisted keys already converged",
            repairable=False,
            repaired=False,
        )

    if not apply:
        status = ControllerTargetStatus.MISSING if not path.exists() else ControllerTargetStatus.DRIFT
        return ControllerConvergenceFinding(
            ownership=ControllerOwnership.ASSISTED,
            status=status,
            target_path=path,
            detail=f"{spec.name} assisted key drift: {', '.join(drift_keys)}",
            repairable=True,
            repaired=False,
        )

    try:
        apply_managed_ini_sections(target_path=path, sections=spec.sections, keep_limit=keep_limit)
    except OSError as exc:
        return ControllerConvergenceFinding(
            ownership=ControllerOwnership.ASSISTED,
            status=ControllerTargetStatus.ERROR,
            target_path=path,
            detail=f"failed applying assisted ini keys: {exc}",
            repairable=False,
            repaired=False,
        )
    return ControllerConvergenceFinding(
        ownership=ControllerOwnership.ASSISTED,
        status=ControllerTargetStatus.REPAIRED,
        target_path=path,
        detail=f"{spec.name} assisted key drift repaired: {', '.join(drift_keys)}",
        repairable=True,
        repaired=True,
    )


def _evaluate_assisted_qsettings_target(
    spec: AssistedQSettingsTarget,
    *,
    apply: bool,
    keep_limit: int,
) -> ControllerConvergenceFinding:
    path = spec.destination
    lines = read_ini_lines(path)
    drift_keys = [key for key, desired in spec.keys.items() if read_qsettings_key(lines, key) != desired]
    if not drift_keys:
        return ControllerConvergenceFinding(
            ownership=ControllerOwnership.ASSISTED,
            status=ControllerTargetStatus.OK,
            target_path=path,
            detail=f"{spec.name} assisted keys already converged",
            repairable=False,
            repaired=False,
        )
    if not apply:
        status = ControllerTargetStatus.MISSING if not path.exists() else ControllerTargetStatus.DRIFT
        return ControllerConvergenceFinding(
            ownership=ControllerOwnership.ASSISTED,
            status=status,
            target_path=path,
            detail=f"{spec.name} assisted key drift: {', '.join(drift_keys)}",
            repairable=True,
            repaired=False,
        )

    changed = False
    try:
        for key, desired in spec.keys.items():
            lines, key_changed = upsert_qsettings_key(lines, key, desired)
            changed |= key_changed
        if changed or not path.exists():
            write_controller_config_lines_atomic(path, lines, keep_limit=keep_limit)
    except OSError as exc:
        return ControllerConvergenceFinding(
            ownership=ControllerOwnership.ASSISTED,
            status=ControllerTargetStatus.ERROR,
            target_path=path,
            detail=f"failed applying assisted qsettings keys: {exc}",
            repairable=False,
            repaired=False,
        )
    return ControllerConvergenceFinding(
        ownership=ControllerOwnership.ASSISTED,
        status=ControllerTargetStatus.REPAIRED,
        target_path=path,
        detail=f"{spec.name} assisted key drift repaired: {', '.join(drift_keys)}",
        repairable=True,
        repaired=True,
    )


def _unmanaged_profile_findings(
    plan: ControllerConvergencePlan,
    *,
    apply: bool,
    force_unmanaged: bool,
    keep_limit: int,
) -> list[ControllerConvergenceFinding]:
    findings: list[ControllerConvergenceFinding] = []
    expected_by_dir: dict[Path, set[str]] = {}
    for target in plan.managed_profile_targets:
        expected_by_dir.setdefault(target.destination.parent, set()).add(target.destination.name)
    for directory, expected_files in expected_by_dir.items():
        if not directory.exists():
            continue
        for candidate in sorted(directory.iterdir(), key=lambda path: path.name.casefold()):
            if not candidate.is_file():
                continue
            if candidate.name == MANAGED_METADATA_FILENAME:
                continue
            if candidate.name in expected_files:
                continue
            if apply and force_unmanaged:
                backup_path = _archive_unmanaged_profile_file(candidate, keep_limit=keep_limit)
                findings.append(
                    ControllerConvergenceFinding(
                        ownership=ControllerOwnership.UNMANAGED,
                        status=ControllerTargetStatus.REPAIRED,
                        target_path=candidate,
                        detail=f"unmanaged profile archived to {backup_path}",
                        repairable=True,
                        repaired=True,
                    )
                )
                continue
            findings.append(
                ControllerConvergenceFinding(
                    ownership=ControllerOwnership.UNMANAGED,
                    status=ControllerTargetStatus.UNMANAGED,
                    target_path=candidate,
                    detail="unmanaged profile file present",
                    repairable=force_unmanaged,
                    repaired=False,
                )
            )
    return findings


def apply_controller_convergence_plan(
    plan: ControllerConvergencePlan,
    *,
    apply: bool,
    force_managed: bool = False,
    force_unmanaged: bool = False,
    include_unmanaged_scan: bool = False,
    keep_limit: int = DEFAULT_BACKUP_KEEP_LIMIT,
) -> ControllerConvergenceResult:
    findings: list[ControllerConvergenceFinding] = []
    for managed_target in plan.managed_profile_targets:
        findings.append(
            _evaluate_managed_target(
                managed_target,
                apply=apply,
                force_managed=force_managed,
                force_unmanaged=force_unmanaged,
                keep_limit=keep_limit,
            )
        )
    for assisted_ini_target in plan.assisted_ini_targets:
        findings.append(_evaluate_assisted_ini_target(assisted_ini_target, apply=apply, keep_limit=keep_limit))
    for assisted_qsettings_target in plan.assisted_qsettings_targets:
        findings.append(
            _evaluate_assisted_qsettings_target(
                assisted_qsettings_target,
                apply=apply,
                keep_limit=keep_limit,
            )
        )
    if include_unmanaged_scan:
        findings.extend(
            _unmanaged_profile_findings(
                plan,
                apply=apply,
                force_unmanaged=force_unmanaged,
                keep_limit=keep_limit,
            )
        )

    result = ControllerConvergenceResult(findings=findings, total_targets=plan.total_targets)
    for finding in findings:
        if finding.repaired:
            result.repaired_count += 1
            continue
        if finding.status == ControllerTargetStatus.OK:
            result.unchanged_count += 1
            continue
        if finding.status in (ControllerTargetStatus.DRIFT, ControllerTargetStatus.MISSING):
            result.drift_count += 1
            continue
        if finding.status == ControllerTargetStatus.UNMANAGED:
            result.unmanaged_count += 1
            continue
        if finding.status == ControllerTargetStatus.ERROR:
            result.error_count += 1
    return result


def converge_controller_state(
    config: GamehubConfig,
    *,
    index: LibraryIndex,
    dry_run: bool,
    verbose: bool,
    force_managed: bool = False,
    writer: Callable[[str], None] = print,
) -> ControllerConvergenceResult:
    families = emulator_families_for_index(index)
    if not families:
        return ControllerConvergenceResult()
    plan = build_controller_convergence_plan(config, emulator_families=families)
    if verbose:
        writer(
            "controller-convergence\t"
            f"runtime_rules={format_runtime_selection_rules(plan.runtime_selection)}\t"
            f"managed_targets={len(plan.managed_profile_targets)}\t"
            f"assisted_targets={len(plan.assisted_ini_targets) + len(plan.assisted_qsettings_targets)}"
        )
    result = apply_controller_convergence_plan(
        plan,
        apply=not dry_run,
        force_managed=force_managed,
        include_unmanaged_scan=False,
        keep_limit=config.backups.keep_limit,
    )
    if verbose or result.unresolved_count > 0:
        writer(
            "controller-convergence\t"
            f"repaired={result.repaired_count}\t"
            f"unchanged={result.unchanged_count}\t"
            f"drift={result.drift_count}\t"
            f"unmanaged={result.unmanaged_count}\t"
            f"errors={result.error_count}"
        )
    return result


def run_controller_doctor(
    config: GamehubConfig,
    *,
    apply: bool,
    force: bool = False,
    steam_roots: tuple[Path, ...] = (),
    steam_discovery_note: str | None = None,
    writer: Callable[[str], None] = print,
) -> int:
    if force and not apply:
        raise ValueError("controller doctor force mode requires apply mode")
    plan = build_controller_convergence_plan(
        config,
        steam_roots=steam_roots,
        steam_discovery_note=steam_discovery_note,
    )
    writer(
        "controller-doctor\t"
        f"runtime_rules={format_runtime_selection_rules(plan.runtime_selection)}\t"
        f"managed_targets={len(plan.managed_profile_targets)}\t"
        f"assisted_targets={len(plan.assisted_ini_targets) + len(plan.assisted_qsettings_targets)}"
    )
    if plan.steam_roots:
        for root in plan.steam_roots:
            writer(f"controller-doctor\tdiscovered\tsteam_root={root}")
    if plan.steam_discovery_note:
        writer(f"controller-doctor\tnote\tsteam={plan.steam_discovery_note}")

    result = apply_controller_convergence_plan(
        plan,
        apply=apply,
        force_managed=False,
        force_unmanaged=force,
        include_unmanaged_scan=True,
        keep_limit=config.backups.keep_limit,
    )
    for finding in sorted(
        result.findings,
        key=lambda item: (
            item.status.value,
            item.ownership.value,
            str(item.target_path).casefold(),
        ),
    ):
        writer(
            "controller-doctor\t"
            f"status={finding.status.value}\t"
            f"ownership={finding.ownership.value}\t"
            f"repairable={str(finding.repairable).lower()}\t"
            f"repaired={str(finding.repaired).lower()}\t"
            f"target={finding.target_path}\t"
            f"detail={finding.detail}"
        )
    writer(
        "controller-doctor\tsummary\t"
        f"repaired={result.repaired_count}\t"
        f"unchanged={result.unchanged_count}\t"
        f"drift={result.drift_count}\t"
        f"unmanaged={result.unmanaged_count}\t"
        f"errors={result.error_count}"
    )
    return 1 if result.unresolved_count > 0 else 0
