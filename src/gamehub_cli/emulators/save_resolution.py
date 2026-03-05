from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path, PurePosixPath
from typing import Callable, Literal, Mapping, cast

from gamehub_common.ids import make_save_binding_id, make_save_id, sha256_file
from gamehub_common.models import SaveBindingSpec, SaveSpec

from .resolution import resolve_emulator_executable

_OS_NAME = os.name

_RETROARCH_FLATPAK_APP_ID = "org.libretro.RetroArch"
_PCSX2_FLATPAK_APP_ID = "net.pcsx2.PCSX2"
_DOLPHIN_FLATPAK_APP_ID = "org.DolphinEmu.dolphin-emu"
_AZAHAR_FLATPAK_APP_ID = "org.azahar_emu.Azahar"
_DOLPHIN_GC_REGIONS = {"USA", "EUR", "JAP"}
_DOLPHIN_GC_CARDS = {"Card A", "Card B"}
_RETROARCH_SORTED_CORE_DIR_BY_SYSTEM = {
    "GB": "Gambatte",
    "GBA": "mGBA",
    "GBC": "Gambatte",
    "GEN_MD": "Genesis Plus GX",
    "N64": "Mupen64Plus-Next",
    "NDS": "melonDS DS",
    "NES": "FCEUmm",
    "PSX": "SwanStation",
    "SNES": "Snes9x",
}

_SYSTEM_DEFAULT_EMULATOR = {
    "GB": "retroarch",
    "GBA": "retroarch",
    "GBC": "retroarch",
    "GEN_MD": "retroarch",
    "N64": "retroarch",
    "NDS": "retroarch",
    "N3DS": "azahar",
    "NES": "retroarch",
    "PSX": "retroarch",
    "SNES": "retroarch",
    "GC": "dolphin",
    "WII": "dolphin",
    "PS2": "pcsx2",
}


@dataclass(frozen=True)
class LocalSaveCandidate:
    binding_id: str
    title_id: str
    system: str
    kind: str
    save_id: str
    canonical_suffix: str
    path: Path
    sha256: str
    size_bytes: int


def _normalized_local_path(value: str | Path) -> Path:
    helper = import_module("gamehub_cli.common.paths")
    normalizer = cast(Callable[[str | Path], Path], helper.normalized_local_path)
    return normalizer(value)


def default_emulator_for_system(system: str) -> str | None:
    return _SYSTEM_DEFAULT_EMULATOR.get(system.strip().upper())


def _parse_simple_kv_config(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    parsed: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or raw.startswith(";") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        parsed[key.strip().lower()] = value.strip().strip('"').strip("'")
    return parsed


def _config_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().strip('"').strip("'").casefold() in {"1", "on", "true", "yes"}


def _resolve_retroarch_cfg_path_value(raw: str, *, cfg_path: Path) -> Path:
    value = raw.strip()
    if _OS_NAME == "nt" and value.startswith((":\\", ":/")):
        return _normalized_local_path(cfg_path.parent / value[2:])
    candidate = _normalized_local_path(value)
    if not candidate.is_absolute():
        candidate = _normalized_local_path(cfg_path.parent / candidate)
    return candidate


def _retroarch_cfg_candidates(resolve_executable: Callable[[str], str]) -> tuple[Path, ...]:
    values: list[Path] = []

    if _OS_NAME == "nt":
        exe_raw = resolve_executable("retroarch").strip().strip('"')
        if exe_raw:
            exe_path = _normalized_local_path(exe_raw)
            if exe_path.exists():
                values.append(exe_path.parent / "retroarch.cfg")
        appdata = os.environ.get("APPDATA")
        if appdata:
            values.append(_normalized_local_path(appdata) / "RetroArch" / "retroarch.cfg")
    else:
        home = _normalized_local_path(Path.home())
        native_cfg = home / ".config" / "retroarch" / "retroarch.cfg"
        flatpak_cfg = home / ".var" / "app" / _RETROARCH_FLATPAK_APP_ID / "config" / "retroarch" / "retroarch.cfg"
        resolved = resolve_executable("retroarch").strip().strip('"')
        if resolved and _is_flatpak_command(resolved, _RETROARCH_FLATPAK_APP_ID):
            values.append(flatpak_cfg)
            values.append(native_cfg)
        else:
            values.append(native_cfg)
            values.append(flatpak_cfg)

    deduped: list[Path] = []
    seen: set[Path] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return tuple(deduped)


def _is_flatpak_command(path_value: str | Path, app_id: str) -> bool:
    raw = str(path_value)
    normalized = raw.strip().strip('"').replace("\\", "/").casefold()
    app = app_id.casefold()
    return normalized.endswith(f"/{app}") or f"flatpak/exports/bin/{app}" in normalized


def _existing_dir(path: Path) -> Path | None:
    normalized = _normalized_local_path(path)
    return normalized if normalized.exists() else None


def _retroarch_save_root(resolve_executable: Callable[[str], str]) -> Path | None:
    resolved = resolve_executable("retroarch").strip().strip('"')
    if resolved and _is_flatpak_command(resolved, _RETROARCH_FLATPAK_APP_ID):
        home = _normalized_local_path(Path.home())
        return _existing_dir(home / ".var" / "app" / _RETROARCH_FLATPAK_APP_ID / "config" / "retroarch" / "saves")

    for cfg_path in _retroarch_cfg_candidates(resolve_executable=resolve_executable):
        cfg = _parse_simple_kv_config(cfg_path)
        save_dir = cfg.get("savefile_directory", "").strip()
        if save_dir and save_dir.casefold() != "default":
            resolved_path = _existing_dir(_resolve_retroarch_cfg_path_value(save_dir, cfg_path=cfg_path))
            if resolved_path is not None:
                return resolved_path
        portable = cfg_path.parent / "saves"
        existing = _existing_dir(portable)
        if existing is not None:
            return existing

    if _OS_NAME == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return _existing_dir(_normalized_local_path(appdata) / "RetroArch" / "saves")
        return None

    home = _normalized_local_path(Path.home())
    return _existing_dir(home / ".config" / "retroarch" / "saves")


def _retroarch_system_roots(resolve_executable: Callable[[str], str]) -> tuple[Path, ...]:
    values: list[Path] = []
    for cfg_path in _retroarch_cfg_candidates(resolve_executable=resolve_executable):
        cfg = _parse_simple_kv_config(cfg_path)
        system_dir = cfg.get("system_directory", "").strip()
        if system_dir:
            if system_dir.casefold() == "default":
                values.append(_normalized_local_path(cfg_path.parent / "system"))
            else:
                values.append(_resolve_retroarch_cfg_path_value(system_dir, cfg_path=cfg_path))
        values.append(_normalized_local_path(cfg_path.parent / "system"))

    if _OS_NAME == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            values.append(_normalized_local_path(appdata) / "RetroArch" / "system")
    else:
        home = _normalized_local_path(Path.home())
        values.append(home / ".config" / "retroarch" / "system")
        values.append(home / ".var" / "app" / _RETROARCH_FLATPAK_APP_ID / "config" / "retroarch" / "system")

    deduped: list[Path] = []
    seen: set[Path] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return tuple(deduped)


def _pcsx2_ini_candidates() -> tuple[Path, ...]:
    values: list[Path] = []
    if _OS_NAME == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            base = _normalized_local_path(appdata) / "PCSX2"
            values.append(base / "inis" / "PCSX2.ini")
            values.append(base / "PCSX2.ini")
        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            base = _normalized_local_path(user_profile) / "Documents" / "PCSX2"
            values.append(base / "inis" / "PCSX2.ini")
            values.append(base / "PCSX2.ini")
        if not appdata and not user_profile:
            home = _normalized_local_path(Path.home())
            values.append(home / "Documents" / "PCSX2" / "inis" / "PCSX2.ini")
            values.append(home / "Documents" / "PCSX2" / "PCSX2.ini")
    else:
        home = _normalized_local_path(Path.home())
        values.append(home / ".config" / "PCSX2" / "inis" / "PCSX2.ini")
        values.append(home / ".config" / "PCSX2" / "PCSX2.ini")
        values.append(home / ".var" / "app" / _PCSX2_FLATPAK_APP_ID / "config" / "PCSX2" / "inis" / "PCSX2.ini")

    deduped: list[Path] = []
    seen: set[Path] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return tuple(deduped)


def _resolve_pcsx2_folder_path(raw: str, *, ini_path: Path) -> Path:
    candidate = _normalized_local_path(raw)
    if candidate.is_absolute():
        return candidate
    root = ini_path.parent.parent if ini_path.parent.name.casefold() == "inis" else ini_path.parent
    return _normalized_local_path(root / candidate)


def _pcsx2_save_root(resolve_executable: Callable[[str], str]) -> Path | None:
    resolved = resolve_executable("pcsx2").strip().strip('"')
    if resolved and _is_flatpak_command(resolved, _PCSX2_FLATPAK_APP_ID):
        home = _normalized_local_path(Path.home())
        return _existing_dir(home / ".var" / "app" / _PCSX2_FLATPAK_APP_ID / "config" / "PCSX2" / "memcards")

    if _OS_NAME == "nt":
        for ini_path in _pcsx2_ini_candidates():
            parsed = _parse_simple_kv_config(ini_path)
            memcards_value = (
                parsed.get("memorycards")
                or parsed.get("folders.memorycards")
                or parsed.get("folders/memorycards")
                or ""
            ).strip()
            if memcards_value:
                configured = _existing_dir(_resolve_pcsx2_folder_path(memcards_value, ini_path=ini_path))
                if configured is not None:
                    return configured

        appdata = os.environ.get("APPDATA")
        if appdata:
            appdata_root = _existing_dir(_normalized_local_path(appdata) / "PCSX2" / "memcards")
            if appdata_root is not None:
                return appdata_root

        documents = os.environ.get("USERPROFILE")
        if documents:
            return _existing_dir(_normalized_local_path(documents) / "Documents" / "PCSX2" / "memcards")
        return None

    home = _normalized_local_path(Path.home())
    return _existing_dir(home / ".config" / "PCSX2" / "memcards")


def _dolphin_data_root(resolve_executable: Callable[[str], str]) -> Path | None:
    resolved = resolve_executable("dolphin").strip().strip('"')
    if resolved and _is_flatpak_command(resolved, _DOLPHIN_FLATPAK_APP_ID):
        home = _normalized_local_path(Path.home())
        return _existing_dir(home / ".var" / "app" / _DOLPHIN_FLATPAK_APP_ID / "data" / "dolphin-emu")

    if _OS_NAME == "nt":
        candidates: list[Path] = []
        if resolved:
            exe_path = _normalized_local_path(resolved)
            if exe_path.exists():
                candidates.append(exe_path.parent / "User")
        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            candidates.append(_normalized_local_path(user_profile) / "Documents" / "Dolphin Emulator")
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(_normalized_local_path(appdata) / "Dolphin Emulator")
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(_normalized_local_path(local_app_data) / "Dolphin Emulator")

        config_files = ("Dolphin.ini", "GCPadNew.ini", "WiimoteNew.ini", "Hotkeys.ini")
        for candidate in candidates:
            config_root = candidate / "Config"
            if any((config_root / filename).exists() for filename in config_files):
                return candidate
            if (candidate / "GC").exists() or (candidate / "Wii").exists():
                return candidate
        for candidate in candidates:
            existing = _existing_dir(candidate)
            if existing is not None:
                return existing
        return None

    home = _normalized_local_path(Path.home())
    native = _existing_dir(home / ".local" / "share" / "dolphin-emu")
    if native is not None:
        return native
    return _existing_dir(home / ".var" / "app" / _DOLPHIN_FLATPAK_APP_ID / "data" / "dolphin-emu")


def _dolphin_save_root(resolve_executable: Callable[[str], str]) -> Path | None:
    root = _dolphin_data_root(resolve_executable)
    if root is None:
        return None
    return _existing_dir(root / "GC")


def _azahar_save_root(resolve_executable: Callable[[str], str]) -> Path | None:
    resolved = resolve_executable("azahar").strip().strip('"')
    if resolved and _is_flatpak_command(resolved, _AZAHAR_FLATPAK_APP_ID):
        home = _normalized_local_path(Path.home())
        return _existing_dir(home / ".var" / "app" / _AZAHAR_FLATPAK_APP_ID / "data" / "azahar-emu" / "sdmc")

    if _OS_NAME == "nt":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None
        return _existing_dir(_normalized_local_path(appdata) / "Azahar" / "sdmc")

    home = _normalized_local_path(Path.home())
    return _existing_dir(home / ".local" / "share" / "azahar-emu" / "sdmc")


def resolve_local_save_destination(
    save: SaveSpec, *, binding_roots: Mapping[str, Mapping[str, object]] | None = None
) -> Path | None:
    root = resolve_system_save_root(save.system)
    if root is None:
        return None
    parts = tuple(part for part in PurePosixPath(save.rel_path).parts if part not in {"", "."})
    if len(parts) < 5:
        return None
    suffix_parts = parts[4:]
    if save.kind in {"battery", "memory_card"}:
        return resolve_exact_local_save_destination(
            system=save.system,
            kind=cast(Literal["battery", "memory_card"], save.kind),
            root=root,
            filename=suffix_parts[-1],
        )
    if save.system.strip().upper() == "N3DS":
        materialized_root = _resolve_n3ds_materialized_root(
            root=root,
            canonical_suffix_parts=suffix_parts,
            binding_root=(
                None if binding_roots is None else binding_roots.get(make_save_binding_id(save.title_id, save.kind))
            ),
        )
        if materialized_root is None:
            return None
        return root.joinpath(*materialized_root, *suffix_parts[4:])
    return root.joinpath(*suffix_parts)


def resolve_emulator_save_root(
    emulator: str,
    *,
    resolve_executable: Callable[[str], str] = resolve_emulator_executable,
) -> Path | None:
    name = emulator.strip().strip('"').lower()
    if not name:
        return None
    if name in {"retroarch"}:
        return _retroarch_save_root(resolve_executable)
    if name in {"pcsx2", "pcsx2-qt"}:
        return _pcsx2_save_root(resolve_executable)
    if name in {"dolphin", "dolphin-emu"}:
        return _dolphin_save_root(resolve_executable)
    if name in {"azahar", "azahar-qt"}:
        return _azahar_save_root(resolve_executable)
    return None


def resolve_system_save_root(
    system: str,
    *,
    resolve_executable: Callable[[str], str] = resolve_emulator_executable,
) -> Path | None:
    normalized = system.strip().upper()
    if normalized == "GC":
        root = _dolphin_data_root(resolve_executable)
        if root is None:
            return None
        return _existing_dir(root / "GC")
    if normalized == "WII":
        root = _dolphin_data_root(resolve_executable)
        if root is None:
            return None
        return _existing_dir(root / "Wii")
    default = default_emulator_for_system(normalized)
    if default is None:
        return None
    return resolve_emulator_save_root(default, resolve_executable=resolve_executable)


def _retroarch_prefers_core_subdirs(
    *,
    system: str,
    resolve_executable: Callable[[str], str],
) -> bool:
    if system.strip().upper() not in _RETROARCH_SORTED_CORE_DIR_BY_SYSTEM:
        return False
    for cfg_path in _retroarch_cfg_candidates(resolve_executable=resolve_executable):
        cfg = _parse_simple_kv_config(cfg_path)
        if not _config_truthy(cfg.get("sort_savefiles_enable")):
            continue
        if _config_truthy(cfg.get("sort_savefiles_by_content_enable")):
            return False
        core_name_flag = cfg.get("sort_savefiles_by_core_name_enable")
        if core_name_flag is not None and not _config_truthy(core_name_flag):
            return False
        return True
    return False


def _preferred_exact_path(
    binding: SaveBindingSpec,
    *,
    root: Path,
    filename: str,
    resolve_executable: Callable[[str], str],
) -> Path:
    if binding.local_root in {"retroarch_saves", "retroarch_saves_psx"} and _retroarch_prefers_core_subdirs(
        system=binding.system,
        resolve_executable=resolve_executable,
    ):
        subdir = _RETROARCH_SORTED_CORE_DIR_BY_SYSTEM.get(binding.system.strip().upper())
        if subdir:
            return root / subdir / filename
    return root / filename


def _exact_search_roots(
    binding: SaveBindingSpec,
    *,
    root: Path,
    resolve_executable: Callable[[str], str],
) -> tuple[Path, ...]:
    roots = [root]
    if binding.local_root == "retroarch_saves_psx":
        roots.extend(_retroarch_system_roots(resolve_executable))
    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in roots:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
    return tuple(deduped)


def _unique_recursive_match_roots(roots: tuple[Path, ...], filename: str) -> Path | None:
    matches = sorted({path for root in roots for path in root.rglob(filename) if path.is_file()})
    if len(matches) != 1:
        return None
    return matches[0]


def _existing_exact_path(
    binding: SaveBindingSpec,
    *,
    root: Path,
    filename: str,
    resolve_executable: Callable[[str], str],
) -> Path | None:
    roots = _exact_search_roots(binding, root=root, resolve_executable=resolve_executable)
    for search_root in roots:
        preferred = _preferred_exact_path(
            binding,
            root=search_root,
            filename=filename,
            resolve_executable=resolve_executable,
        )
        if preferred.exists() and preferred.is_file():
            return preferred
    return _unique_recursive_match_roots(roots, filename)


def resolve_binding_local_root(
    binding: SaveBindingSpec,
    *,
    resolve_executable: Callable[[str], str] = resolve_emulator_executable,
) -> Path | None:
    if binding.local_root == "retroarch_saves":
        return resolve_emulator_save_root("retroarch", resolve_executable=resolve_executable)
    if binding.local_root == "retroarch_saves_psx":
        save_root = resolve_emulator_save_root("retroarch", resolve_executable=resolve_executable)
        if save_root is not None:
            return save_root
        system_roots = _retroarch_system_roots(resolve_executable)
        for candidate in system_roots:
            existing = _existing_dir(candidate)
            if existing is not None:
                return existing
        if system_roots:
            return system_roots[0]
        return None
    if binding.local_root == "pcsx2_memcards":
        return resolve_emulator_save_root("pcsx2", resolve_executable=resolve_executable)
    if binding.local_root == "dolphin_gc":
        return resolve_system_save_root("GC", resolve_executable=resolve_executable)
    if binding.local_root == "dolphin_wii":
        return resolve_system_save_root("Wii", resolve_executable=resolve_executable)
    if binding.local_root == "azahar_sdmc":
        return resolve_system_save_root("N3DS", resolve_executable=resolve_executable)
    return None


def discover_local_exact_save_candidates(
    bindings: tuple[SaveBindingSpec, ...],
    *,
    resolve_executable: Callable[[str], str] = resolve_emulator_executable,
) -> tuple[LocalSaveCandidate, ...]:
    candidates: list[LocalSaveCandidate] = []
    for binding in bindings:
        if binding.strategy != "exact_files":
            continue
        root = resolve_binding_local_root(binding, resolve_executable=resolve_executable)
        if root is None:
            continue
        for filename in binding.candidate_filenames:
            path = _existing_exact_path(
                binding,
                root=root,
                filename=filename,
                resolve_executable=resolve_executable,
            )
            if path is None:
                continue
            rel_path = f"{binding.server_rel_dir}/{filename}"
            stat_result = path.stat()
            candidates.append(
                LocalSaveCandidate(
                    binding_id=binding.binding_id,
                    title_id=binding.title_id,
                    system=binding.system,
                    kind=binding.kind,
                    save_id=make_save_id(rel_path),
                    canonical_suffix=filename,
                    path=path,
                    sha256=sha256_file(path),
                    size_bytes=stat_result.st_size,
                )
            )
    return tuple(sorted(candidates, key=lambda item: (item.system, item.title_id, item.canonical_suffix, item.save_id)))


def snapshot_binding_tree(
    binding: SaveBindingSpec,
    *,
    resolve_executable: Callable[[str], str] = resolve_emulator_executable,
) -> dict[str, str]:
    root = resolve_binding_local_root(binding, resolve_executable=resolve_executable)
    if root is None:
        return {}
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file():
            continue
        rel_path = path.relative_to(root).as_posix()
        if not _matches_learned_tree_path(binding, rel_path):
            continue
        snapshot[rel_path] = sha256_file(path)
    return snapshot


def _matches_learned_tree_path(binding: SaveBindingSpec, rel_path: str) -> bool:
    if binding.strategy != "learned_tree":
        return True
    parts = tuple(part for part in PurePosixPath(rel_path).parts if part not in {"", "."})
    if binding.learn_rule == "dolphin_gc_gci_tree":
        return len(parts) >= 3 and parts[0] in _DOLPHIN_GC_REGIONS and parts[1] in _DOLPHIN_GC_CARDS
    if binding.learn_rule == "dolphin_wii_title_tree":
        return len(parts) >= 4 and parts[0] == "title" and _is_hex_segment(parts[1], 8) and _is_hex_segment(parts[2], 8)
    if binding.learn_rule == "azahar_title_data_tree":
        return (
            len(parts) >= 8
            and parts[0] == "Nintendo 3DS"
            and _is_hex_segment(parts[1], 32)
            and _is_hex_segment(parts[2], 32)
            and parts[3] == "title"
            and _is_hex_segment(parts[4], 8)
            and _is_hex_segment(parts[5], 8)
            and parts[6] == "data"
        )
    return False


def resolve_exact_local_save_destination(
    *,
    system: str,
    kind: Literal["battery", "memory_card"],
    root: Path,
    filename: str,
    resolve_executable: Callable[[str], str] = resolve_emulator_executable,
) -> Path:
    system_name = system.strip().upper()
    local_root: Literal["retroarch_saves", "retroarch_saves_psx", "pcsx2_memcards"] = "retroarch_saves"
    if system_name == "PS2":
        local_root = "pcsx2_memcards"
    elif system_name == "PSX":
        local_root = "retroarch_saves_psx"

    binding = SaveBindingSpec(
        binding_id="savebind_runtime_exact",
        title_id="title_runtime_exact",
        system=system,
        kind=kind,
        server_rel_dir=f"saves/{system}/runtime/{kind}",
        local_root=local_root,
        strategy="exact_files",
        candidate_filenames=(filename,),
        learn_rule=None,
        portable=True,
    )
    existing = _existing_exact_path(
        binding,
        root=root,
        filename=filename,
        resolve_executable=resolve_executable,
    )
    if existing is not None:
        return existing
    return _preferred_exact_path(
        binding,
        root=root,
        filename=filename,
        resolve_executable=resolve_executable,
    )


def learn_binding_root(
    binding: SaveBindingSpec,
    changed_relative_paths: tuple[str, ...],
) -> tuple[str, str] | None:
    if binding.strategy != "learned_tree" or not changed_relative_paths:
        return None
    canonical_roots: set[str] = set()
    materialized_roots: set[str] = set()
    for rel_path in changed_relative_paths:
        parts = tuple(part for part in PurePosixPath(rel_path).parts if part not in {"", "."})
        if binding.learn_rule == "dolphin_gc_gci_tree":
            if len(parts) < 3 or parts[0] not in _DOLPHIN_GC_REGIONS or parts[1] not in _DOLPHIN_GC_CARDS:
                return None
            canonical_roots.add(PurePosixPath(*parts[:2]).as_posix())
            materialized_roots.add(PurePosixPath(*parts[:2]).as_posix())
            continue
        if binding.learn_rule == "dolphin_wii_title_tree":
            if (
                len(parts) < 4
                or parts[0] != "title"
                or not _is_hex_segment(parts[1], 8)
                or not _is_hex_segment(parts[2], 8)
            ):
                return None
            canonical_roots.add(PurePosixPath(*parts[:3]).as_posix())
            materialized_roots.add(PurePosixPath(*parts[:3]).as_posix())
            continue
        if binding.learn_rule == "azahar_title_data_tree":
            if (
                len(parts) < 8
                or parts[0] != "Nintendo 3DS"
                or not _is_hex_segment(parts[1], 32)
                or not _is_hex_segment(parts[2], 32)
                or parts[3] != "title"
                or not _is_hex_segment(parts[4], 8)
                or not _is_hex_segment(parts[5], 8)
                or parts[6] != "data"
            ):
                return None
            canonical_roots.add(PurePosixPath(*parts[3:7]).as_posix())
            materialized_roots.add(PurePosixPath(*parts[:7]).as_posix())
            continue
        return None
    if len(canonical_roots) != 1 or len(materialized_roots) != 1:
        return None
    return next(iter(canonical_roots)), next(iter(materialized_roots))


def canonical_suffix_for_learned_path(binding: SaveBindingSpec, rel_path: str, *, materialized_root: str) -> str | None:
    parts = tuple(part for part in PurePosixPath(rel_path).parts if part not in {"", "."})
    root_parts = tuple(part for part in PurePosixPath(materialized_root).parts if part not in {"", "."})
    if len(parts) <= len(root_parts) or parts[: len(root_parts)] != root_parts:
        return None
    remainder = parts[len(root_parts) :]
    if binding.learn_rule == "dolphin_gc_gci_tree":
        return PurePosixPath(*root_parts, *remainder).as_posix()
    if binding.learn_rule == "dolphin_wii_title_tree":
        return PurePosixPath(*root_parts, *remainder).as_posix()
    if binding.learn_rule == "azahar_title_data_tree":
        if len(root_parts) < 7:
            return None
        return PurePosixPath(*root_parts[3:], *remainder).as_posix()
    return None


def _is_hex_segment(value: str, length: int) -> bool:
    if len(value) != length:
        return False
    return all(char.isdigit() or char.casefold() in "abcdef" for char in value)


def _single_n3ds_profile_prefix(root: Path) -> tuple[str, ...] | None:
    base = root / "Nintendo 3DS"
    if not base.exists() or not base.is_dir():
        return None
    prefixes: list[tuple[str, ...]] = []
    for id0_dir in sorted(base.iterdir(), key=lambda item: item.name.casefold()):
        if not id0_dir.is_dir() or not _is_hex_segment(id0_dir.name, 32):
            continue
        for id1_dir in sorted(id0_dir.iterdir(), key=lambda item: item.name.casefold()):
            if not id1_dir.is_dir() or not _is_hex_segment(id1_dir.name, 32):
                continue
            prefixes.append(("Nintendo 3DS", id0_dir.name, id1_dir.name))
    if len(prefixes) != 1:
        return None
    return prefixes[0]


def _resolve_n3ds_materialized_root(
    *,
    root: Path,
    canonical_suffix_parts: tuple[str, ...],
    binding_root: Mapping[str, object] | None,
) -> tuple[str, ...] | None:
    if (
        len(canonical_suffix_parts) < 5
        or canonical_suffix_parts[0] != "title"
        or not _is_hex_segment(canonical_suffix_parts[1], 8)
        or not _is_hex_segment(canonical_suffix_parts[2], 8)
        or canonical_suffix_parts[3] != "data"
    ):
        return None
    canonical_root = PurePosixPath(*canonical_suffix_parts[:4]).as_posix()
    if binding_root is not None:
        stored_canonical = binding_root.get("canonical_root")
        stored_materialized = binding_root.get("materialized_root")
        if not isinstance(stored_canonical, str) or not isinstance(stored_materialized, str):
            return None
        if stored_canonical != canonical_root:
            return None
        return tuple(part for part in PurePosixPath(stored_materialized).parts if part not in {"", "."})
    profile_prefix = _single_n3ds_profile_prefix(root)
    if profile_prefix is None:
        return None
    return tuple((*profile_prefix, *canonical_suffix_parts[:4]))
