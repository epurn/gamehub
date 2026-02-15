from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Callable
from uuid import uuid4

from gamehub_common.ids import sha256_file
from gamehub_common.models import LibraryIndex

from .config import GamehubConfig
from .emulators import resolve_emulator_executable
from .fsops import replace_file


def _override_path(*env_names: str, config_value: Path | None = None) -> Path | None:
    for env_name in env_names:
        raw = os.environ.get(env_name)
        if raw and raw.strip():
            return Path(raw.strip()).expanduser()
    if config_value is not None:
        return config_value.expanduser()
    return None


def _linux_flatpak_retroarch_root() -> Path:
    return Path.home() / ".var" / "app" / "org.libretro.RetroArch" / "config" / "retroarch"


def _linux_flatpak_pcsx2_root() -> Path:
    return Path.home() / ".var" / "app" / "net.pcsx2.PCSX2" / "config" / "PCSX2"


def _linux_flatpak_dolphin_root() -> Path:
    return Path.home() / ".var" / "app" / "org.DolphinEmu.dolphin-emu" / "data" / "dolphin-emu"


def _is_flatpak_command(path: Path, app_id: str) -> bool:
    value = path.as_posix().lower()
    app = app_id.casefold()
    return value.endswith(f"/{app}") or f"flatpak/exports/bin/{app}" in value


def _flatpak_visible_home_path(path: Path) -> Path:
    value = path.as_posix()
    if value.startswith("/var/home/"):
        return Path("/home") / value[len("/var/home/") :]
    return path


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


def _retroarch_cfg_candidates(config: GamehubConfig | None = None) -> list[Path]:
    values: list[Path] = []
    cfg_override = _override_path("GAMEHUB_RETROARCH_CFG_PATH", config_value=config.linux.retroarch_cfg_path if config else None)
    if cfg_override:
        values.append(cfg_override)
    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        values.append(Path(appdata) / "RetroArch" / "retroarch.cfg")
    home = Path.home()
    values.append(home / ".config" / "retroarch" / "retroarch.cfg")
    values.append(_linux_flatpak_retroarch_root() / "retroarch.cfg")
    return _unique_paths(values)


def _resolve_retroarch_system_dirs(config: GamehubConfig | None = None) -> list[Path]:
    values: list[Path] = []
    system_override = _override_path(
        "RETROARCH_SYSTEM_DIR",
        "GAMEHUB_RETROARCH_SYSTEM_DIR",
        config_value=config.linux.retroarch_system_dir if config else None,
    )
    if system_override:
        values.append(system_override)

    for cfg_path in _retroarch_cfg_candidates(config=config):
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

    retroarch_raw = resolve_emulator_executable("retroarch").strip('"')
    retroarch_exe = Path(retroarch_raw)
    prefer_flatpak = _is_flatpak_command(retroarch_exe, "org.libretro.RetroArch") or (
        "org.libretro.retroarch" in retroarch_raw.casefold()
    )
    if os.name == "nt" and retroarch_exe.exists():
        values.append(retroarch_exe.parent / "system")
    elif sys.platform.startswith("linux") and prefer_flatpak:
        values.append(_linux_flatpak_retroarch_root() / "system")

    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        values.append(Path(appdata) / "RetroArch" / "system")
    home = Path.home()
    native = home / ".config" / "retroarch" / "system"
    flatpak = _linux_flatpak_retroarch_root() / "system"
    if sys.platform.startswith("linux") and prefer_flatpak:
        values.append(flatpak)
        values.append(native)
    else:
        values.append(native)
        values.append(flatpak)
    return _unique_paths(values)


def _pcsx2_ini_candidates(config: GamehubConfig | None = None) -> list[Path]:
    values: list[Path] = []
    ini_override = _override_path("GAMEHUB_PCSX2_INI_PATH", config_value=config.linux.pcsx2_ini_path if config else None)
    if ini_override:
        values.append(ini_override)
    user_profile = os.environ.get("USERPROFILE")
    if os.name == "nt" and user_profile:
        values.append(Path(user_profile) / "Documents" / "PCSX2" / "inis" / "PCSX2.ini")
        values.append(Path(user_profile) / "Documents" / "PCSX2" / "PCSX2.ini")
    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        values.append(Path(appdata) / "PCSX2" / "inis" / "PCSX2.ini")
        values.append(Path(appdata) / "PCSX2" / "PCSX2.ini")
    home = Path.home()
    values.append(home / "Documents" / "PCSX2" / "inis" / "PCSX2.ini")
    values.append(home / "Documents" / "PCSX2" / "PCSX2.ini")
    values.append(home / ".config" / "PCSX2" / "inis" / "PCSX2.ini")
    values.append(home / ".config" / "PCSX2" / "PCSX2.ini")
    values.append(_linux_flatpak_pcsx2_root() / "inis" / "PCSX2.ini")
    return _unique_paths(values)


def _resolve_pcsx2_bios_dirs(config: GamehubConfig | None = None) -> list[Path]:
    values: list[Path] = []
    bios_override = _override_path(
        "PCSX2_BIOS_DIR",
        "GAMEHUB_PCSX2_BIOS_DIR",
        config_value=config.linux.pcsx2_bios_dir if config else None,
    )
    if bios_override:
        values.append(bios_override)

    for ini_path in _pcsx2_ini_candidates(config=config):
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
    if os.name == "nt" and appdata:
        values.append(Path(appdata) / "PCSX2" / "bios")
    user_profile = os.environ.get("USERPROFILE")
    if os.name == "nt" and user_profile:
        values.append(Path(user_profile) / "Documents" / "PCSX2" / "bios")
    home = Path.home()
    native = home / ".config" / "PCSX2" / "bios"
    flatpak = _linux_flatpak_pcsx2_root() / "bios"
    docs = home / "Documents" / "PCSX2" / "bios"
    pcsx2_raw = resolve_emulator_executable("pcsx2").strip('"')
    pcsx2_exe = Path(pcsx2_raw)
    prefer_flatpak = _is_flatpak_command(pcsx2_exe, "net.pcsx2.PCSX2") or ("net.pcsx2.pcsx2" in pcsx2_raw.casefold())
    if sys.platform.startswith("linux") and prefer_flatpak:
        values.extend((flatpak, native, docs))
    else:
        values.extend((docs, native, flatpak))
    return _unique_paths(values)


def _resolve_dolphin_user_dirs(config: GamehubConfig | None = None) -> list[Path]:
    values: list[Path] = []
    user_override = _override_path(
        "DOLPHIN_EMU_USERPATH",
        "GAMEHUB_DOLPHIN_EMU_USERPATH",
        config_value=config.linux.dolphin_user_path if config else None,
    )
    if user_override:
        values.append(user_override)
        return _unique_paths(values)

    appdata = os.environ.get("APPDATA")
    if os.name == "nt" and appdata:
        values.append(Path(appdata) / "Dolphin Emulator")

    home = Path.home()
    legacy = home / ".dolphin-emu"
    if legacy.exists():
        values.append(legacy)
    native = home / ".local" / "share" / "dolphin-emu"
    flatpak = _linux_flatpak_dolphin_root()
    existing_linux = [path for path in (flatpak, native, legacy) if path.exists()]
    if existing_linux:
        values.extend(existing_linux)
        return _unique_paths(values)

    dolphin_raw = resolve_emulator_executable("dolphin").strip('"')
    dolphin_exe = Path(dolphin_raw)
    if _is_flatpak_command(dolphin_exe, "org.DolphinEmu.dolphin-emu") or (
        "org.dolphinemu.dolphin-emu" in dolphin_raw.casefold()
    ):
        values.append(flatpak)
    else:
        values.append(native)
    return _unique_paths(values)


def _target_dirs_for_system(system_name: str, config: GamehubConfig | None = None) -> list[Path]:
    if system_name == "PSX":
        return _resolve_retroarch_system_dirs(config=config)
    if system_name == "PS2":
        return _resolve_pcsx2_bios_dirs(config=config)
    if system_name == "Wii":
        return [path / "Wii" for path in _resolve_dolphin_user_dirs(config=config)]
    if system_name == "GC":
        return [path / "GC" for path in _resolve_dolphin_user_dirs(config=config)]
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


def _default_pcsx2_ini_path(config: GamehubConfig | None = None) -> Path:
    override = _override_path("GAMEHUB_PCSX2_INI_PATH", config_value=config.linux.pcsx2_ini_path if config else None)
    if override is not None:
        return override

    if sys.platform.startswith("linux"):
        pcsx2_raw = resolve_emulator_executable("pcsx2").strip('"')
        pcsx2_exe = Path(pcsx2_raw)
        if _is_flatpak_command(pcsx2_exe, "net.pcsx2.PCSX2") or ("net.pcsx2.pcsx2" in pcsx2_raw.casefold()):
            return _linux_flatpak_pcsx2_root() / "inis" / "PCSX2.ini"

    candidates = _pcsx2_ini_candidates(config=config)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    if sys.platform.startswith("linux"):
        pcsx2_raw = resolve_emulator_executable("pcsx2").strip('"')
        pcsx2_exe = Path(pcsx2_raw)
        if _is_flatpak_command(pcsx2_exe, "net.pcsx2.PCSX2") or ("net.pcsx2.pcsx2" in pcsx2_raw.casefold()):
            return _linux_flatpak_pcsx2_root() / "inis" / "PCSX2.ini"
        return Path.home() / ".config" / "PCSX2" / "inis" / "PCSX2.ini"
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
    bios_dir = _override_path(
        "PCSX2_BIOS_DIR",
        "GAMEHUB_PCSX2_BIOS_DIR",
        config_value=config.linux.pcsx2_bios_dir,
    ) or (config.firmware_dir / "PS2")
    pcsx2_raw = resolve_emulator_executable("pcsx2").strip('"')
    pcsx2_exe = Path(pcsx2_raw)
    prefer_flatpak = _is_flatpak_command(pcsx2_exe, "net.pcsx2.PCSX2") or ("net.pcsx2.pcsx2" in pcsx2_raw.casefold())
    bios_dir_for_config = _flatpak_visible_home_path(bios_dir) if prefer_flatpak else bios_dir
    ini_path = _default_pcsx2_ini_path(config=config)
    if dry_run:
        if verbose:
            writer(f"pcsx2\tdry-run\tconfigure\t{ini_path}\tbios={bios_dir_for_config}")
        return

    lines = _read_ini_lines(ini_path)
    lines, changed_ui = _upsert_ini_key(lines, "UI", "SetupWizardIncomplete", "false")
    lines, changed_bios = _upsert_ini_key(lines, "Folders", "Bios", str(bios_dir_for_config))
    if changed_ui or changed_bios or not ini_path.exists():
        _write_ini_atomic(ini_path, lines)
    bios_dir.mkdir(parents=True, exist_ok=True)
    if verbose:
        writer(f"pcsx2\tconfigured\t{ini_path}\tbios={bios_dir_for_config}")


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
        target_dirs = _target_dirs_for_system(system.name, config=config)
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
