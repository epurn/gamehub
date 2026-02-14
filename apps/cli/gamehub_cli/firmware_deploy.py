from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
from typing import Callable
from uuid import uuid4

from gamehub_common.ids import sha256_file
from gamehub_common.models import LibraryIndex

from .config import GamehubConfig
from .emulators import resolve_emulator_executable
from .fsops import replace_file


def _unique_paths(values: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[Path] = set()
    for value in values:
        resolved = value.expanduser()
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append(resolved)
    return result


def _parse_simple_kv_config(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or raw.startswith(";"):
            continue
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        values[key.strip().lower()] = value.strip().strip('"').strip("'")
    return values


def _retroarch_cfg_candidates() -> list[Path]:
    values: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        values.append(Path(appdata) / "RetroArch" / "retroarch.cfg")
    home = Path.home()
    values.append(home / ".config" / "retroarch" / "retroarch.cfg")
    values.append(home / ".var" / "app" / "org.libretro.RetroArch" / "config" / "retroarch" / "retroarch.cfg")
    return _unique_paths(values)


def _resolve_retroarch_system_dirs() -> list[Path]:
    values: list[Path] = []
    env_override = os.environ.get("RETROARCH_SYSTEM_DIR")
    if env_override:
        values.append(Path(env_override))

    for cfg_path in _retroarch_cfg_candidates():
        parsed = _parse_simple_kv_config(cfg_path)
        raw = parsed.get("system_directory")
        if not raw:
            continue
        if raw.lower() == "default":
            values.append(cfg_path.parent / "system")
            continue
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = cfg_path.parent / candidate
        values.append(candidate)

    retroarch_exe = Path(resolve_emulator_executable("retroarch").strip('"'))
    if retroarch_exe.exists():
        values.append(retroarch_exe.parent / "system")

    appdata = os.environ.get("APPDATA")
    if appdata:
        values.append(Path(appdata) / "RetroArch" / "system")
    home = Path.home()
    values.append(home / ".config" / "retroarch" / "system")
    values.append(home / ".var" / "app" / "org.libretro.RetroArch" / "config" / "retroarch" / "system")
    return _unique_paths(values)


def _pcsx2_ini_candidates() -> list[Path]:
    values: list[Path] = []
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        values.append(Path(user_profile) / "Documents" / "PCSX2" / "inis" / "PCSX2.ini")
        values.append(Path(user_profile) / "Documents" / "PCSX2" / "PCSX2.ini")
    appdata = os.environ.get("APPDATA")
    if appdata:
        values.append(Path(appdata) / "PCSX2" / "inis" / "PCSX2.ini")
        values.append(Path(appdata) / "PCSX2" / "PCSX2.ini")
    home = Path.home()
    values.append(home / "Documents" / "PCSX2" / "inis" / "PCSX2.ini")
    values.append(home / "Documents" / "PCSX2" / "PCSX2.ini")
    values.append(home / ".config" / "PCSX2" / "inis" / "PCSX2.ini")
    values.append(home / ".config" / "PCSX2" / "PCSX2.ini")
    values.append(home / ".var" / "app" / "net.pcsx2.PCSX2" / "config" / "PCSX2" / "inis" / "PCSX2.ini")
    return _unique_paths(values)


def _resolve_pcsx2_bios_dirs() -> list[Path]:
    values: list[Path] = []
    env_override = os.environ.get("PCSX2_BIOS_DIR")
    if env_override:
        values.append(Path(env_override))

    for ini_path in _pcsx2_ini_candidates():
        parsed = _parse_simple_kv_config(ini_path)
        bios_value = parsed.get("bios") or parsed.get("folders.bios")
        if not bios_value:
            continue
        candidate = Path(bios_value)
        if not candidate.is_absolute():
            # Resolve relative to config root (parent of `inis/` when present).
            root = ini_path.parent.parent if ini_path.parent.name.lower() == "inis" else ini_path.parent
            candidate = root / candidate
        values.append(candidate)

    appdata = os.environ.get("APPDATA")
    if appdata:
        values.append(Path(appdata) / "PCSX2" / "bios")
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        values.append(Path(user_profile) / "Documents" / "PCSX2" / "bios")
    home = Path.home()
    values.append(home / "Documents" / "PCSX2" / "bios")
    values.append(home / ".config" / "PCSX2" / "bios")
    values.append(home / ".var" / "app" / "net.pcsx2.PCSX2" / "config" / "PCSX2" / "bios")
    return _unique_paths(values)


def _resolve_dolphin_user_dirs() -> list[Path]:
    values: list[Path] = []
    env_override = os.environ.get("DOLPHIN_EMU_USERPATH")
    if env_override:
        values.append(Path(env_override))

    appdata = os.environ.get("APPDATA")
    if appdata:
        values.append(Path(appdata) / "Dolphin Emulator")

    home = Path.home()
    legacy = home / ".dolphin-emu"
    if legacy.exists():
        values.append(legacy)
    values.append(home / ".local" / "share" / "dolphin-emu")
    values.append(home / ".var" / "app" / "org.DolphinEmu.dolphin-emu" / "data" / "dolphin-emu")
    return _unique_paths(values)


def _target_dirs_for_system(system_name: str) -> list[Path]:
    if system_name == "PSX":
        return _resolve_retroarch_system_dirs()
    if system_name == "PS2":
        return _resolve_pcsx2_bios_dirs()
    if system_name == "Wii":
        return [path / "Wii" for path in _resolve_dolphin_user_dirs()]
    if system_name == "GC":
        return [path / "GC" for path in _resolve_dolphin_user_dirs()]
    return []


def _sha256(path: Path) -> str:
    return sha256_file(path)


def _copy_or_link(source: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and _sha256(destination) == _sha256(source):
        return "up_to_date"

    tmp = destination.with_name(f"{destination.name}.{uuid4().hex}.tmp")
    shutil.copy2(source, tmp)
    mode = "copied"
    replace_file(tmp, destination)
    return mode


def _default_pcsx2_ini_path() -> Path:
    candidates = _pcsx2_ini_candidates()
    for candidate in candidates:
        if candidate.exists():
            return candidate
    if candidates:
        return candidates[0]
    return Path.home() / "Documents" / "PCSX2" / "inis" / "PCSX2.ini"


def _read_ini_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="ignore").splitlines()


def _upsert_ini_key(lines: list[str], section: str, key: str, value: str) -> tuple[list[str], bool]:
    section_name = section.lower()
    key_name = key.lower()
    output: list[str] = []
    in_section = False
    section_found = False
    key_found = False
    changed = False

    for line in lines:
        stripped = line.strip()
        is_section = stripped.startswith("[") and stripped.endswith("]")
        if is_section:
            if in_section and not key_found:
                output.append(f"{key} = {value}")
                key_found = True
                changed = True
            current = stripped[1:-1].strip().lower()
            in_section = current == section_name
            if in_section:
                section_found = True
            output.append(line)
            continue

        if in_section and "=" in line:
            current_key = line.split("=", 1)[0].strip().lower()
            if current_key == key_name:
                desired = f"{key} = {value}"
                if stripped != desired:
                    output.append(desired)
                    changed = True
                else:
                    output.append(line)
                key_found = True
                continue

        output.append(line)

    if in_section and not key_found:
        output.append(f"{key} = {value}")
        changed = True
        key_found = True

    if not section_found:
        if output and output[-1].strip():
            output.append("")
        output.append(f"[{section}]")
        output.append(f"{key} = {value}")
        changed = True

    return output, changed


def _write_ini_atomic(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(lines).rstrip() + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp") as tmp:
        tmp.write(payload)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    replace_file(tmp_path, path)


def _configure_pcsx2_runtime(
    config: GamehubConfig,
    dry_run: bool,
    verbose: bool,
    writer: Callable[[str], None],
) -> None:
    bios_dir = Path(os.environ.get("PCSX2_BIOS_DIR", str(config.firmware_dir / "PS2"))).expanduser()
    ini_path = _default_pcsx2_ini_path()
    if dry_run:
        if verbose:
            writer(f"pcsx2\tdry-run\tconfigure\t{ini_path}\tbios={bios_dir}")
        return

    lines = _read_ini_lines(ini_path)
    lines, changed_ui = _upsert_ini_key(lines, "UI", "SetupWizardIncomplete", "false")
    lines, changed_bios = _upsert_ini_key(lines, "Folders", "Bios", str(bios_dir))
    if changed_ui or changed_bios or not ini_path.exists():
        _write_ini_atomic(ini_path, lines)
    bios_dir.mkdir(parents=True, exist_ok=True)
    if verbose:
        writer(f"pcsx2\tconfigured\t{ini_path}\tbios={bios_dir}")


def deploy_firmware_to_emulators(
    config: GamehubConfig,
    index: LibraryIndex,
    dry_run: bool,
    verbose: bool,
    writer: Callable[[str], None] = print,
) -> None:
    requested = 0
    applied = 0
    skipped = 0
    has_ps2 = any(system.name == "PS2" for system in index.systems)
    if has_ps2:
        _configure_pcsx2_runtime(config=config, dry_run=dry_run, verbose=verbose, writer=writer)

    for system in index.systems:
        if system.name == "PS2":
            # PCSX2 reads BIOS directly from configured path (no firmware mirroring copy).
            continue
        target_dirs = _target_dirs_for_system(system.name)
        if not target_dirs:
            continue
        for firmware in system.firmware:
            source = config.firmware_dir / system.name / firmware.filename
            for target_dir in target_dirs:
                destination = target_dir / firmware.filename
                requested += 1
                if not source.exists():
                    if verbose:
                        writer(f"firmware\tmissing-source\t{source}\t->\t{destination}")
                    skipped += 1
                    continue
                if dry_run:
                    if verbose:
                        writer(f"firmware\tdry-run\t{source}\t->\t{destination}")
                    continue
                result = _copy_or_link(source, destination)
                if verbose:
                    writer(f"firmware\t{result}\t{source}\t->\t{destination}")
                if result == "up_to_date":
                    skipped += 1
                else:
                    applied += 1

    if dry_run:
        if verbose and requested > 0:
            writer(f"Firmware deployment dry-run targets: {requested}")
        return
    if requested == 0:
        return
    writer(f"Firmware deployment: targets={requested} applied={applied} skipped={skipped}")
