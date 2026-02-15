from __future__ import annotations

import re
from pathlib import Path
import shlex
import sys

from gamehub_common.models import LibraryIndex

from .config import GamehubConfig
from .emulators import resolve_emulator_executable
from .paths import from_rel_path
from .platform_paths import PCSX2_FLATPAK_APP_ID, is_flatpak_command
from .retroarch_cores import resolve_retroarch_paths
from .steam import (
    SteamArtworkAssignment,
    SteamContext,
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
    update_cloud_collections,
    update_collections,
    upsert_shortcuts,
    wait_for_steam_exit,
)

_RETROARCH_CORE_TOKEN_RE = re.compile(r"(?P<prefix>-L\s+)(?P<token>[^\s]+)")


def _resolve_rom_path(base: Path, rel_path: str) -> Path:
    try:
        return from_rel_path(base, rel_path, preferred_root="roms")
    except TypeError:
        # Compatibility for patched resolvers in tests/extensions that still use the old 2-arg signature.
        return from_rel_path(base, rel_path)


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


def build_shortcut_specs(
    index: LibraryIndex,
    config: GamehubConfig,
) -> list[SteamShortcutSpec]:
    specs: list[SteamShortcutSpec] = []
    for title in sorted(index.titles, key=lambda item: (item.system, item.title_name.casefold(), item.title_id)):
        rom_path = _resolve_rom_path(config.library_dir, title.rom.rel_path)
        emulator_exe = resolve_emulator_executable(title.emulator)
        pcsx2_flatpak = (
            sys.platform.startswith("linux")
            and "pcsx2" in title.emulator.casefold()
            and is_flatpak_command(emulator_exe, PCSX2_FLATPAK_APP_ID)
        )
        if pcsx2_flatpak:
            rom_for_flatpak = rom_path.as_posix()
            specs.append(
                SteamShortcutSpec(
                    title_id=title.title_id,
                    system=title.system,
                    title_name=title.title_name,
                    exe="flatpak",
                    launch_options=(
                        f'run --file-forwarding {PCSX2_FLATPAK_APP_ID} '
                        f'-fullscreen -- @@ "{rom_for_flatpak}" @@'
                    ),
                    start_dir="",
                    icon_path="",
                )
            )
            continue
        launch_template = title.launch_template
        if "retroarch" in title.emulator.casefold():
            launch_template = _normalize_linux_retroarch_launch_template(launch_template, config)
        launch_line = launch_template.format(emulator=emulator_exe, rom=str(rom_path))
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


def resolve_steam_context(config: GamehubConfig) -> SteamContext | None:
    userdata_dir = discover_userdata_dir(config.steam_userdata_dir)
    if userdata_dir is None:
        print("Steam userdata directory not found; skipping Steam updates")
        return None

    steam_id = discover_steam_id(userdata_dir, preferred_steam_id=config.steam_id)
    if steam_id is None:
        print("No Steam ID found in userdata; skipping Steam updates")
        return None

    return build_context(userdata_dir, steam_id, config.steam_exe)


def apply_steam_updates(
    config: GamehubConfig,
    index: LibraryIndex,
    require_steam_closed: bool,
    artwork_by_title: dict[str, dict[str, Path]],
    reopen_steam_after_update: bool = True,
) -> None:
    context = resolve_steam_context(config)
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

    shortcut_specs = build_shortcut_specs(index, config)
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
    if not reopen_steam_after_update:
        print("Skipping Steam relaunch (--skip-steam-relaunch)")
        return
    reopened = reopen_steam(context)
    if not reopened:
        print("Warning: Steam relaunch command was not found; start Steam manually")
