from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, cast

from gamehub_common.ids import make_save_binding_id, make_save_id
from gamehub_common.models import SaveBindingSpec, SaveKind, SaveSpec, TitleEntry

SAVES_ROOT_NAME = "saves"

SAVE_KIND_PORTABILITY: dict[SaveKind, bool] = {
    "battery": True,
    "memory_card": True,
    "per_game": False,
}

_BATTERY_SAVE_SUFFIXES: dict[str, tuple[str, ...]] = {
    "GB": (".srm",),
    "GBA": (".srm",),
    "GBC": (".srm",),
    "GEN_MD": (".srm",),
    "N64": (".srm", ".eep", ".fla", ".mpk"),
    "NDS": (".srm",),
    "NES": (".srm",),
    "SNES": (".srm",),
}

_SERVER_GENERATED_SAVE_BACKUP_NAME_RE = re.compile(r"^.+\.\d{14}(?:\.\d+)?\.bak$")


@dataclass(frozen=True)
class IndexedSaveBinding:
    title_id: str
    system: str


def is_server_generated_save_backup_name(filename: str) -> bool:
    return bool(_SERVER_GENERATED_SAVE_BACKUP_NAME_RE.match(filename))


def _raise_if_symlink(path: Path, *, context: str) -> None:
    if path.is_symlink():
        raise ValueError(f"Symlinked content is not allowed for {context}: {path}")


def build_save_bindings(titles: tuple[TitleEntry, ...]) -> tuple[SaveBindingSpec, ...]:
    bindings: list[SaveBindingSpec] = []
    for title in titles:
        system_name = title.system.upper()
        server_battery_dir = _server_save_binding_dir(
            system=title.system, title_rel_dir=title.title_rel_dir, kind="battery"
        )
        server_memory_dir = _server_save_binding_dir(
            system=title.system, title_rel_dir=title.title_rel_dir, kind="memory_card"
        )
        server_per_game_dir = _server_save_binding_dir(
            system=title.system, title_rel_dir=title.title_rel_dir, kind="per_game"
        )

        if system_name in _BATTERY_SAVE_SUFFIXES:
            bindings.append(
                SaveBindingSpec(
                    binding_id=make_save_binding_id(title.title_id, "battery"),
                    title_id=title.title_id,
                    system=title.system,
                    kind="battery",
                    server_rel_dir=server_battery_dir,
                    local_root="retroarch_saves",
                    strategy="exact_files",
                    candidate_filenames=tuple(
                        f"{title.title_name}{suffix}" for suffix in _BATTERY_SAVE_SUFFIXES[system_name]
                    ),
                    learn_rule=None,
                    portable=SAVE_KIND_PORTABILITY["battery"],
                )
            )

        if system_name == "PSX":
            bindings.append(
                SaveBindingSpec(
                    binding_id=make_save_binding_id(title.title_id, "memory_card"),
                    title_id=title.title_id,
                    system=title.system,
                    kind="memory_card",
                    server_rel_dir=server_memory_dir,
                    local_root="retroarch_saves_psx",
                    strategy="exact_files",
                    candidate_filenames=(
                        f"GH_{title.title_id}_1.mcd",
                        f"GH_{title.title_id}_2.mcd",
                        f"{title.title_name}.srm",
                        f"{title.title_name}_1.mcd",
                        f"{title.title_name}_2.mcd",
                    ),
                    learn_rule=None,
                    portable=SAVE_KIND_PORTABILITY["memory_card"],
                )
            )

        if system_name == "PS2":
            bindings.append(
                SaveBindingSpec(
                    binding_id=make_save_binding_id(title.title_id, "memory_card"),
                    title_id=title.title_id,
                    system=title.system,
                    kind="memory_card",
                    server_rel_dir=server_memory_dir,
                    local_root="pcsx2_memcards",
                    strategy="exact_files",
                    candidate_filenames=(f"GH_{title.title_id}_1.ps2", f"GH_{title.title_id}_2.ps2"),
                    learn_rule=None,
                    portable=SAVE_KIND_PORTABILITY["memory_card"],
                )
            )

        if system_name == "GC":
            bindings.append(
                SaveBindingSpec(
                    binding_id=make_save_binding_id(title.title_id, "per_game"),
                    title_id=title.title_id,
                    system=title.system,
                    kind="per_game",
                    server_rel_dir=server_per_game_dir,
                    local_root="dolphin_gc",
                    strategy="learned_tree",
                    candidate_filenames=(),
                    learn_rule="dolphin_gc_gci_tree",
                    portable=SAVE_KIND_PORTABILITY["per_game"],
                )
            )

        if system_name == "WII":
            bindings.append(
                SaveBindingSpec(
                    binding_id=make_save_binding_id(title.title_id, "per_game"),
                    title_id=title.title_id,
                    system=title.system,
                    kind="per_game",
                    server_rel_dir=server_per_game_dir,
                    local_root="dolphin_wii",
                    strategy="learned_tree",
                    candidate_filenames=(),
                    learn_rule="dolphin_wii_title_tree",
                    portable=SAVE_KIND_PORTABILITY["per_game"],
                )
            )

        if system_name == "N3DS":
            bindings.append(
                SaveBindingSpec(
                    binding_id=make_save_binding_id(title.title_id, "per_game"),
                    title_id=title.title_id,
                    system=title.system,
                    kind="per_game",
                    server_rel_dir=server_per_game_dir,
                    local_root="azahar_sdmc",
                    strategy="learned_tree",
                    candidate_filenames=(),
                    learn_rule="azahar_title_data_tree",
                    portable=SAVE_KIND_PORTABILITY["per_game"],
                )
            )

    return tuple(sorted(bindings, key=lambda item: (item.system, item.title_id, item.kind, item.binding_id)))


def save_binding_key_from_title_rel_dir(system: str, title_rel_dir: str) -> tuple[str, str]:
    return system, _save_title_dir_name(title_rel_dir)


def save_binding_key_from_layout(system: str, title_dir_name: str) -> tuple[str, str]:
    return system, title_dir_name


def scan_save_specs(
    *,
    data_root: Path,
    system_catalog: Mapping[str, object],
    title_bindings: Mapping[tuple[str, str], IndexedSaveBinding],
    hash_sha256: Callable[[Path, str, int, int], str],
    relative_unix: Callable[[Path, Path], str],
) -> tuple[list[SaveSpec], dict[str, Path]]:
    saves_root = data_root / SAVES_ROOT_NAME
    save_specs: list[SaveSpec] = []
    save_paths: dict[str, Path] = {}
    for system_dir in sorted(saves_root.iterdir(), key=lambda item: item.name.lower()):
        _raise_if_symlink(system_dir, context="save system directory")
        if not system_dir.is_dir():
            raise ValueError(f"Malformed save layout: expected system directory in {saves_root}, got {system_dir.name}")
        system_name = system_dir.name
        if system_name not in system_catalog:
            raise ValueError(f"Malformed save layout: unknown system in saves root: {system_name}")

        for title_dir in sorted(system_dir.iterdir(), key=lambda item: item.name.lower()):
            _raise_if_symlink(title_dir, context=f"save title directory for {system_name}")
            if not title_dir.is_dir():
                raise ValueError(
                    "Malformed save layout: expected title directory under "
                    f"{system_dir}, got file {title_dir.name}. Expected saves/<system>/<title_rel_stem>/<kind>/<file>"
                )
            binding_key = save_binding_key_from_layout(system_name, title_dir.name)
            binding = title_bindings.get(binding_key)
            if binding is None:
                raise ValueError(
                    "Malformed save layout: save title directory does not map to indexed title: "
                    f"{system_name}/{title_dir.name}"
                )

            for kind_dir in sorted(title_dir.iterdir(), key=lambda item: item.name.lower()):
                _raise_if_symlink(kind_dir, context=f"save kind directory for {system_name}/{title_dir.name}")
                if not kind_dir.is_dir():
                    raise ValueError(
                        "Malformed save layout: expected save kind directory under "
                        f"{title_dir}, got file {kind_dir.name}."
                    )
                save_kind = _parse_save_kind(kind_dir.name)
                if save_kind is None:
                    allowed = ", ".join(sorted(SAVE_KIND_PORTABILITY))
                    raise ValueError(
                        f"Malformed save layout: unknown save kind '{kind_dir.name}' in {kind_dir}. Allowed: {allowed}"
                    )
                portable = SAVE_KIND_PORTABILITY[save_kind]

                for save_path in _iter_save_files(kind_dir, save_kind):
                    save_rel = relative_unix(save_path, data_root)
                    save_stat = save_path.stat()
                    save_sha = hash_sha256(
                        save_path,
                        save_rel,
                        save_stat.st_size,
                        save_stat.st_mtime_ns,
                    )
                    save_id = make_save_id(save_rel)
                    save_paths[save_id] = save_path
                    save_specs.append(
                        SaveSpec(
                            save_id=save_id,
                            title_id=binding.title_id,
                            system=binding.system,
                            kind=save_kind,
                            rel_path=save_rel,
                            sha256=save_sha,
                            size_bytes=save_stat.st_size,
                            updated_at=datetime.fromtimestamp(save_stat.st_mtime, tz=timezone.utc),
                            portable=portable,
                        )
                    )
    return save_specs, save_paths


def _save_title_dir_name(title_rel_dir: str) -> str:
    return PurePosixPath(title_rel_dir).with_suffix("").name


def _parse_save_kind(value: str) -> SaveKind | None:
    if value not in SAVE_KIND_PORTABILITY:
        return None
    return cast(SaveKind, value)


def _server_save_binding_dir(*, system: str, title_rel_dir: str, kind: SaveKind) -> str:
    return f"{SAVES_ROOT_NAME}/{system}/{_save_title_dir_name(title_rel_dir)}/{kind}"


def _iter_save_files(kind_dir: Path, save_kind: SaveKind) -> list[Path]:
    files: list[Path] = []
    for child in sorted(kind_dir.iterdir(), key=lambda item: item.name.lower()):
        _raise_if_symlink(child, context=f"{save_kind} save entry")
        if child.is_dir():
            if save_kind != "per_game":
                raise ValueError(
                    f"Malformed save layout: nested directories are not allowed under {save_kind} saves: {child}"
                )
            files.extend(_iter_save_files(child, save_kind))
            continue
        if child.is_file():
            if is_server_generated_save_backup_name(child.name):
                continue
            files.append(child)
    return files
