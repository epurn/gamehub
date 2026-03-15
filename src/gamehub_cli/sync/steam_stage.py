from __future__ import annotations

import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path, PurePosixPath

from gamehub_common.models import LibraryIndex

from ..common.config import GamehubConfig
from ..common.paths import resolve_rom_destination
from ..common.platform_paths import (
    AZAHAR_FLATPAK_APP_ID,
    DOLPHIN_FLATPAK_APP_ID,
    PCSX2_FLATPAK_APP_ID,
    RETROARCH_FLATPAK_APP_ID,
    is_flatpak_command,
)
from ..common.shortcut_payload import encode_shortcut_payload
from ..common.shortcut_payload import strip_wrapping_quotes as _strip_wrapping_quotes
from ..common.shortcut_payload_registry import (
    save_shortcut_payload_registry_atomic,
    shortcut_payload_registry_path,
)
from ..controllers.detection import is_steam_deck_linux
from ..emulators import resolve_emulator_executable
from ..emulators.resolution import resolve_macos_preferred_bundle_executable
from ..firmware.retroarch_cores import resolve_retroarch_paths
from ..firmware.targets import resolve_dolphin_runtime_user_dir
from ..steam import (
    SteamArtworkAssignment,
    SteamContext,
    SteamShortcutSpec,
    apply_deck_steam_input_templates,
    backup_steam_configs,
    build_context,
    close_steam_best_effort,
    copy_grid_art,
    discover_steam_id,
    discover_userdata_dir,
    is_steam_running,
    prune_grid_noncanonical_variants,
    reopen_steam,
    repair_managed_steam_input_overrides,
    update_cloud_collections,
    update_collections,
    upsert_shortcuts,
)

_RETROARCH_CORE_TOKEN_RE = re.compile(r"(?P<prefix>-L\s+)(?P<token>[^\s]+)")
_RETROARCH_FULLSCREEN_TOKEN_RE = re.compile(r"(^|\s)-f(\s|$)")
_PCSX2_FULLSCREEN_TOKEN_RE = re.compile(r"(^|\s)-fullscreen(\s|$)")
_AZAHAR_FULLSCREEN_TOKEN_RE = re.compile(r"(^|\s)(-f|--fullscreen)(\s|$)")
_EMULATOR_TEMPLATE_TOKEN_RE = re.compile(r'^\s*"\{emulator\}"')
_DOLPHIN_FULLSCREEN_CONFIG_TOKEN = "Dolphin.Display.Fullscreen=True"
_DOLPHIN_FULLSCREEN_CONFIG_ARG_RE = re.compile(r"\s-C\s+Dolphin\.Display\.Fullscreen=True")
_DOLPHIN_EXEC_TOKEN_RE = re.compile(r"\s(-e|--exec)(\s|=)")
_DOLPHIN_USER_ARG_RE = re.compile(r"\s(-u|--user)(\s|=)")
_AZAHAR_LINUX_EXIT_HOOK_ENV = "GAMEHUB_AZAHAR_LINUX_EXIT_HOOK"
_STEAM_ALLOW_DESKTOP_CONFIG_ENV = "GAMEHUB_STEAM_ALLOW_DESKTOP_CONFIG"
_WRAPPED_EMULATORS = {"pcsx2", "dolphin", "azahar", "retroarch"}
_MACOS_ARCH_EXECUTABLE = "/usr/bin/arch"


def _env_enabled(name: str, *, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().casefold()
    if normalized in {"0", "false", "no", "off"}:
        return False
    if normalized in {"1", "true", "yes", "on"}:
        return True
    return default


@lru_cache(maxsize=1)
def _machine_name() -> str:
    return platform.machine().strip().casefold()


def _env_optional_bool(name: str) -> bool | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def _managed_shortcut_allow_desktop_config(*, steam_deck_linux: bool, emulator_name: str) -> bool | None:
    override = _env_optional_bool(_STEAM_ALLOW_DESKTOP_CONFIG_ENV)
    if override is not None:
        return override
    if steam_deck_linux:
        del emulator_name
        # Deck-managed shortcuts default to native-first controller behavior.
        return False
    return None


def _is_windows_style_runtime_path(value: str) -> bool:
    token = value.strip().strip('"')
    if not token:
        return False
    normalized = token.replace("/", "\\")
    # Drive-letter absolute path (C:\...), UNC path, or explicit .exe path.
    if re.match(r"^[A-Za-z]:\\", normalized):
        return True
    if normalized.startswith("\\\\"):
        return True
    return normalized.casefold().endswith(".exe")


def _normalize_linux_retroarch_launch_template(
    launch_template: str,
    config: GamehubConfig,
    emulator_exe: str,
) -> str:
    if _is_windows_style_runtime_path(emulator_exe):
        return launch_template
    if sys.platform.startswith("linux"):
        core_suffix = ".so"
    elif sys.platform == "darwin":
        core_suffix = ".dylib"
    else:
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

    core_filename = f"{core_name}{core_suffix}"
    core_token = f"cores/{core_filename}"
    explicit_cores_dir = config.linux.retroarch_cores_dir
    explicit_info_dir = config.linux.retroarch_info_dir
    explicit_cfg_path = config.linux.retroarch_cfg_path
    if sys.platform == "darwin":
        explicit_cores_dir = config.macos.retroarch_cores_dir
        explicit_info_dir = config.macos.retroarch_info_dir
        explicit_cfg_path = config.macos.retroarch_cfg_path
    paths = resolve_retroarch_paths(
        explicit_cores_dir=explicit_cores_dir,
        explicit_info_dir=explicit_info_dir,
        explicit_cfg_path=explicit_cfg_path,
    )
    if paths is not None:
        core_token = (paths.cores_dir / core_filename).as_posix()

    replacement = f'{match.group("prefix")}"{core_token}"'
    return f"{launch_template[: match.start()]}{replacement}{launch_template[match.end() :]}"


def _inject_after_emulator_token(launch_template: str, token: str) -> str:
    match = _EMULATOR_TEMPLATE_TOKEN_RE.search(launch_template)
    if not match:
        return f"{launch_template}{token}"
    return f"{launch_template[: match.end()]}{token}{launch_template[match.end() :]}"


def _normalize_retroarch_fullscreen_launch_template(launch_template: str) -> str:
    if _RETROARCH_FULLSCREEN_TOKEN_RE.search(launch_template):
        return launch_template
    return _inject_after_emulator_token(launch_template, " -f")


def _normalize_pcsx2_launch_template(launch_template: str) -> str:
    if _PCSX2_FULLSCREEN_TOKEN_RE.search(launch_template):
        return launch_template
    return _inject_after_emulator_token(launch_template, " -fullscreen")


def _normalize_azahar_launch_template(launch_template: str) -> str:
    if _AZAHAR_FULLSCREEN_TOKEN_RE.search(launch_template):
        return launch_template
    return _inject_after_emulator_token(launch_template, " -f")


@lru_cache(maxsize=8)
def _supports_dolphin_inline_config(emulator_exe: str) -> bool:
    token = emulator_exe.strip().strip('"')
    if not token:
        return True
    # Avoid probing on Windows-style executables; some Dolphin builds print help text
    # directly to the active console even when subprocess output is captured.
    if sys.platform.startswith("win") or _is_windows_style_runtime_path(token):
        return True

    executable = token
    candidate_path = Path(token)
    if not candidate_path.exists():
        resolved = shutil.which(token)
        if resolved:
            executable = resolved

    try:
        completed = subprocess.run(
            [executable, "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        # Best effort only; keep fullscreen injection when probing is unavailable.
        return True

    help_text = f"{completed.stdout}\n{completed.stderr}"
    lowered = help_text.casefold()
    if "--config" in lowered or " -c <config>" in lowered:
        return True
    if "usage: dolphin [/" in lowered:
        return False
    if re.search(r"(?m)^\s*/[a-z]", help_text):
        return False
    return True


def _resolve_dolphin_user_dir_for_launch(emulator_exe: str, config: GamehubConfig) -> Path:
    return resolve_dolphin_runtime_user_dir(config=config)


def _normalize_dolphin_launch_template(launch_template: str, emulator_exe: str, config: GamehubConfig) -> str:
    user_dir = str(_resolve_dolphin_user_dir_for_launch(emulator_exe, config))
    if not _DOLPHIN_USER_ARG_RE.search(launch_template):
        user_token = f' -u "{user_dir}"'
        match = _DOLPHIN_EXEC_TOKEN_RE.search(launch_template)
        if match:
            launch_template = f"{launch_template[: match.start()]}{user_token}{launch_template[match.start() :]}"
        else:
            launch_template = f"{launch_template}{user_token}"
    if not _supports_dolphin_inline_config(emulator_exe):
        return _DOLPHIN_FULLSCREEN_CONFIG_ARG_RE.sub("", launch_template)
    if _DOLPHIN_FULLSCREEN_CONFIG_TOKEN in launch_template:
        return launch_template
    match = _DOLPHIN_EXEC_TOKEN_RE.search(launch_template)
    inject = f" -C {_DOLPHIN_FULLSCREEN_CONFIG_TOKEN}"
    if match:
        return f"{launch_template[: match.start()]}{inject}{launch_template[match.start() :]}"
    return f"{launch_template}{inject}"


def _should_wrap_shortcut(emulator_name: str, config: GamehubConfig) -> bool:
    if not (config.controllers.launch_autoconfig or config.save_sync.enabled):
        return False
    normalized = emulator_name.casefold()
    for token in _WRAPPED_EMULATORS:
        if token in normalized:
            return True
    return False


def _maybe_quote_executable(value: str) -> str:
    stripped = value.strip().strip('"')
    if not stripped:
        return value
    # Keep Windows executable invocation stable for Steam shortcuts.
    if stripped.casefold().endswith(".exe"):
        return f'"{stripped}"'
    if any(ch.isspace() for ch in stripped):
        return f'"{stripped}"'
    return stripped


def _is_python_executable_name(value: str) -> bool:
    normalized = value.casefold()
    if normalized.endswith(".exe"):
        normalized = normalized[:-4]
    return normalized == "python" or normalized.startswith("python") or normalized.startswith("pypy")


def _gamehub_wrapper_command_names() -> tuple[str, ...]:
    if sys.platform.startswith("win"):
        return ("gamehub.exe", "gamehub-windows-amd64.exe", "gamehub")
    return ("gamehub",)


def _is_gamehub_wrapper_name(value: str) -> bool:
    normalized = _strip_wrapping_quotes(value).replace("\\", "/").rsplit("/", 1)[-1].casefold()
    return normalized in {name.casefold() for name in _gamehub_wrapper_command_names()}


def _resolved_existing_path(path: Path) -> str | None:
    candidate = path.expanduser()
    if not candidate.exists():
        return None
    return str(candidate.absolute())


def _is_absolute_runtime_path(value: str) -> bool:
    if value.startswith("/"):
        return True
    path = Path(value).expanduser()
    return path.is_absolute()


def _normalize_wrapper_candidate(value: str) -> str | None:
    normalized = _strip_wrapping_quotes(value)
    if not normalized:
        return None
    if _is_windows_style_runtime_path(normalized):
        return normalized
    path = Path(normalized).expanduser()
    if path.exists():
        return _resolved_existing_path(path)
    if _is_absolute_runtime_path(normalized):
        return str(path)
    return None


def _resolve_invoked_gamehub_wrapper_executable() -> str | None:
    if sys.argv and sys.argv[0]:
        argv0 = _strip_wrapping_quotes(sys.argv[0])
        argv_name = Path(argv0).name.casefold()
        if _is_gamehub_wrapper_name(argv_name):
            path = Path(argv0)
            resolved = _resolved_existing_path(path)
            if resolved:
                return resolved
            if not path.is_absolute():
                resolved = shutil.which(argv0)
                if resolved:
                    return _normalize_wrapper_candidate(resolved) or resolved

    exe_path = Path(sys.executable)
    exe_name = exe_path.name.casefold()
    if _is_gamehub_wrapper_name(exe_name):
        resolved = _resolved_existing_path(exe_path)
        if resolved:
            return resolved
    return None


def _resolve_adjacent_gamehub_wrapper_executable() -> str | None:
    base_path = Path(sys.executable)
    for sibling_name in _gamehub_wrapper_command_names():
        if sibling_name.casefold() == base_path.name.casefold():
            continue
        resolved = _resolved_existing_path(base_path.with_name(sibling_name))
        if resolved:
            return resolved
    return None


def _resolve_gamehub_wrapper_executable() -> str | None:
    candidates: list[str] = []

    invoked_wrapper = _resolve_invoked_gamehub_wrapper_executable()
    if invoked_wrapper:
        candidates.append(invoked_wrapper)

    adjacent_wrapper = _resolve_adjacent_gamehub_wrapper_executable()
    if adjacent_wrapper:
        candidates.append(adjacent_wrapper)

    for command in _gamehub_wrapper_command_names():
        resolved = shutil.which(command)
        if resolved:
            candidates.append(str(resolved))

    for candidate in candidates:
        normalized = _normalize_wrapper_candidate(candidate)
        if normalized:
            return normalized
    return None


def _wrapper_executable_and_args() -> tuple[str, list[str]]:
    resolved_executable = _normalize_wrapper_candidate(str(sys.executable)) or str(sys.executable)
    executable_name = resolved_executable.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    is_frozen = bool(getattr(sys, "frozen", False))

    if is_frozen:
        return resolved_executable, ["shortcut-launch"]

    wrapper_executable = _resolve_gamehub_wrapper_executable()
    if wrapper_executable:
        return wrapper_executable, ["shortcut-launch"]

    if not _is_python_executable_name(executable_name) and executable_name.endswith(".exe"):
        return resolved_executable, ["shortcut-launch"]
    if sys.platform.startswith("win"):
        candidate = Path(sys.executable).with_name("pythonw.exe")
        if candidate.exists():
            return str(candidate), ["-m", "gamehub_cli.main", "shortcut-launch"]
    return resolved_executable, ["-m", "gamehub_cli.main", "shortcut-launch"]


def _split_launch_options(value: str, *, windows_style: bool | None = None) -> list[str]:
    if not value.strip():
        return []
    if windows_style is None:
        windows_style = sys.platform.startswith("win")
    return shlex.split(value, posix=not windows_style)


def _join_launch_options(args: list[str], *, windows_style: bool | None = None) -> str:
    if not args:
        return ""
    if windows_style is None:
        windows_style = sys.platform.startswith("win")
    if windows_style:
        return subprocess.list2cmdline(args)
    return shlex.join(args)


def _macos_app_bundle_for_executable(executable: str) -> str | None:
    token = _strip_wrapping_quotes(executable).replace("\\", "/")
    if not token:
        return None
    path = PurePosixPath(token)
    candidates = (path, *path.parents)
    for candidate in candidates:
        if candidate.name.casefold().endswith(".app"):
            return candidate.as_posix()
    return None


def _managed_shortcut_payload_ref(spec: SteamShortcutSpec) -> str:
    return spec.title_id


def _start_dir_for_launch_executable(executable: str) -> str:
    normalized = executable.replace("\\", "/").strip().strip('"')
    if "/" not in normalized:
        return ""
    return normalized.rsplit("/", 1)[0]


def _macos_managed_shortcut_executable_and_args() -> tuple[str, list[str], str]:
    wrapper_exe, wrapper_args = _wrapper_executable_and_args()
    launch_exe = wrapper_exe
    launch_args = list(wrapper_args)
    start_dir = _start_dir_for_launch_executable(wrapper_exe)

    if _machine_name() in {"arm64", "aarch64"}:
        launch_args = ["-arm64", launch_exe, *launch_args]
        launch_exe = _MACOS_ARCH_EXECUTABLE

    return launch_exe, launch_args, start_dir


def _build_managed_shortcut_payload(
    spec: SteamShortcutSpec,
    *,
    emulator_name: str,
    config: GamehubConfig,
    rom_rel_path: str,
) -> dict[str, object]:
    target_exe = spec.exe
    if sys.platform == "darwin" and emulator_name.casefold() == "azahar":
        preferred_executable = resolve_macos_preferred_bundle_executable("azahar", user_only=True)
        if preferred_executable is not None:
            target_exe = preferred_executable
    windows_style = _is_windows_style_runtime_path(spec.exe)
    target_args = _split_launch_options(spec.launch_options, windows_style=windows_style)
    payload: dict[str, object] = {
        "v": 1,
        "emulator": emulator_name.casefold(),
        "title_id": spec.title_id,
        "system": spec.system,
        "rom_rel_path": rom_rel_path,
        "target_exe": target_exe,
        "target_args": target_args,
        "start_dir": spec.start_dir,
    }
    if sys.platform == "darwin":
        app_bundle = _macos_app_bundle_for_executable(target_exe)
        if app_bundle:
            payload["macos_open_app"] = app_bundle
            payload["macos_open_args"] = target_args
    if config.config_path is not None:
        payload["config_path"] = str(config.config_path)
    return payload


def _wrap_shortcut_for_managed_launch(
    spec: SteamShortcutSpec,
    *,
    emulator_name: str,
    config: GamehubConfig,
    rom_rel_path: str,
) -> tuple[SteamShortcutSpec, str | None, str | None]:
    payload = _build_managed_shortcut_payload(
        spec,
        emulator_name=emulator_name,
        config=config,
        rom_rel_path=rom_rel_path,
    )
    payload_token = encode_shortcut_payload(payload)

    payload_ref: str | None = None
    if sys.platform == "darwin" and isinstance(payload.get("macos_open_app"), str):
        payload_ref = _managed_shortcut_payload_ref(spec)
        wrapper_exe, wrapper_args, start_dir = _macos_managed_shortcut_executable_and_args()
        launch_args = [
            *wrapper_args,
            "--payload-registry",
            str(shortcut_payload_registry_path(config.state_path)),
            "--payload-ref",
            payload_ref,
        ]
        return (
            SteamShortcutSpec(
                title_id=spec.title_id,
                system=spec.system,
                title_name=spec.title_name,
                exe=_maybe_quote_executable(wrapper_exe),
                launch_options=_join_launch_options(launch_args),
                start_dir=start_dir,
                icon_path=spec.icon_path,
                allow_desktop_config=spec.allow_desktop_config,
            ),
            payload_ref,
            payload_token,
        )
    wrapper_exe, wrapper_args = _wrapper_executable_and_args()
    launch_args = [*wrapper_args, "--payload", payload_token]
    start_dir = ""
    normalized_wrapper = wrapper_exe.replace("\\", "/").strip().strip('"')
    if "/" in normalized_wrapper:
        start_dir = normalized_wrapper.rsplit("/", 1)[0]
    return (
        SteamShortcutSpec(
            title_id=spec.title_id,
            system=spec.system,
            title_name=spec.title_name,
            exe=_maybe_quote_executable(wrapper_exe),
            launch_options=_join_launch_options(launch_args, windows_style=_is_windows_style_runtime_path(wrapper_exe)),
            start_dir=start_dir,
            icon_path=spec.icon_path,
            allow_desktop_config=spec.allow_desktop_config,
        ),
        payload_ref,
        None,
    )


def _strip_launch_line_tokens_for_flatpak(
    parts: list[str],
    *,
    emulator_exe: str,
    rom_path: Path,
) -> list[str]:
    tokens = list(parts)
    emulator_token = _strip_wrapping_quotes(emulator_exe)
    if tokens and _strip_wrapping_quotes(tokens[0]) == emulator_token:
        tokens = tokens[1:]
    rom_token = str(rom_path)
    for index in range(len(tokens) - 1, -1, -1):
        if _strip_wrapping_quotes(tokens[index]) == rom_token:
            del tokens[index]
            break
    return tokens


def _normalize_retroarch_flatpak_tokens(tokens: list[str]) -> list[str]:
    normalized = list(tokens)
    for index, token in enumerate(normalized[:-1]):
        if token != "-L":
            continue
        core_token = normalized[index + 1].strip().strip('"').replace("\\", "/")
        if core_token.endswith(".dll"):
            core_token = f"{core_token[:-4]}.so"
        normalized[index + 1] = core_token
    return normalized


def _build_shortcut_specs_and_payloads(
    index: LibraryIndex,
    config: GamehubConfig,
) -> tuple[list[SteamShortcutSpec], dict[str, str]]:
    specs: list[SteamShortcutSpec] = []
    payload_tokens_by_ref: dict[str, str] = {}
    steam_deck_linux = sys.platform.startswith("linux") and is_steam_deck_linux()
    for title in sorted(index.titles, key=lambda item: (item.system, item.title_name.casefold(), item.title_id)):
        allow_desktop_config = _managed_shortcut_allow_desktop_config(
            steam_deck_linux=steam_deck_linux,
            emulator_name=title.emulator,
        )
        rom_path = resolve_rom_destination(
            library_dir=config.library_dir,
            roms_dir=config.roms_dir,
            rel_path=title.rom.rel_path,
        )
        emulator_exe = resolve_emulator_executable(title.emulator)
        dolphin_flatpak = (
            sys.platform.startswith("linux")
            and "dolphin" in title.emulator.casefold()
            and is_flatpak_command(emulator_exe, DOLPHIN_FLATPAK_APP_ID)
        )
        pcsx2_flatpak = (
            sys.platform.startswith("linux")
            and "pcsx2" in title.emulator.casefold()
            and is_flatpak_command(emulator_exe, PCSX2_FLATPAK_APP_ID)
        )
        azahar_flatpak = (
            sys.platform.startswith("linux")
            and "azahar" in title.emulator.casefold()
            and is_flatpak_command(emulator_exe, AZAHAR_FLATPAK_APP_ID)
        )
        retroarch_flatpak = (
            sys.platform.startswith("linux")
            and "retroarch" in title.emulator.casefold()
            and is_flatpak_command(emulator_exe, RETROARCH_FLATPAK_APP_ID)
        )
        if retroarch_flatpak:
            launch_template = _normalize_retroarch_fullscreen_launch_template(title.launch_template)
            launch_template = _normalize_linux_retroarch_launch_template(launch_template, config, emulator_exe)
            launch_line = launch_template.format(emulator=emulator_exe, rom=str(rom_path))
            parts = shlex.split(launch_line, posix=True)
            forwarded_tokens = _normalize_retroarch_flatpak_tokens(
                _strip_launch_line_tokens_for_flatpak(
                    parts,
                    emulator_exe=emulator_exe,
                    rom_path=rom_path,
                )
            )
            launch_args = [
                "run",
                "--file-forwarding",
                RETROARCH_FLATPAK_APP_ID,
                *forwarded_tokens,
                "@@",
                rom_path.as_posix(),
                "@@",
            ]
            spec = SteamShortcutSpec(
                title_id=title.title_id,
                system=title.system,
                title_name=title.title_name,
                exe="flatpak",
                launch_options=_join_launch_options(launch_args),
                start_dir="",
                icon_path="",
                allow_desktop_config=allow_desktop_config,
            )
            if _should_wrap_shortcut(title.emulator, config):
                spec, payload_ref, payload_token = _wrap_shortcut_for_managed_launch(
                    spec,
                    emulator_name=title.emulator,
                    config=config,
                    rom_rel_path=title.rom.rel_path,
                )
                if payload_ref is not None and payload_token is not None:
                    payload_tokens_by_ref[payload_ref] = payload_token
            specs.append(spec)
            continue
        if dolphin_flatpak:
            rom_for_flatpak = rom_path.as_posix()
            dolphin_user_dir = resolve_dolphin_runtime_user_dir(config=config).as_posix()
            spec = SteamShortcutSpec(
                title_id=title.title_id,
                system=title.system,
                title_name=title.title_name,
                exe="flatpak",
                launch_options=(
                    f"run --device=all --file-forwarding {DOLPHIN_FLATPAK_APP_ID} "
                    f'-b -u "{dolphin_user_dir}" -e @@ "{rom_for_flatpak}" @@'
                ),
                start_dir="",
                icon_path="",
                allow_desktop_config=allow_desktop_config,
            )
            if _should_wrap_shortcut(title.emulator, config):
                spec, payload_ref, payload_token = _wrap_shortcut_for_managed_launch(
                    spec,
                    emulator_name=title.emulator,
                    config=config,
                    rom_rel_path=title.rom.rel_path,
                )
                if payload_ref is not None and payload_token is not None:
                    payload_tokens_by_ref[payload_ref] = payload_token
            specs.append(spec)
            continue
        if pcsx2_flatpak:
            rom_for_flatpak = rom_path.as_posix()
            spec = SteamShortcutSpec(
                title_id=title.title_id,
                system=title.system,
                title_name=title.title_name,
                exe="flatpak",
                launch_options=(
                    f'run --file-forwarding {PCSX2_FLATPAK_APP_ID} -fullscreen -- @@ "{rom_for_flatpak}" @@'
                ),
                start_dir="",
                icon_path="",
                allow_desktop_config=allow_desktop_config,
            )
            if _should_wrap_shortcut(title.emulator, config):
                spec, payload_ref, payload_token = _wrap_shortcut_for_managed_launch(
                    spec,
                    emulator_name=title.emulator,
                    config=config,
                    rom_rel_path=title.rom.rel_path,
                )
                if payload_ref is not None and payload_token is not None:
                    payload_tokens_by_ref[payload_ref] = payload_token
            specs.append(spec)
            continue
        if azahar_flatpak:
            rom_for_flatpak = rom_path.as_posix()
            use_exit_hook = _env_enabled(_AZAHAR_LINUX_EXIT_HOOK_ENV, default=True)
            if use_exit_hook:
                python_exe = str(sys.executable).replace("\\", "/")
                spec = SteamShortcutSpec(
                    title_id=title.title_id,
                    system=title.system,
                    title_name=title.title_name,
                    exe=f'"{python_exe}"',
                    launch_options=(
                        f"-m gamehub_cli.controllers.azahar_exit_hook "
                        f'--app-id {AZAHAR_FLATPAK_APP_ID} --rom "{rom_for_flatpak}"'
                    ),
                    start_dir="",
                    icon_path="",
                    allow_desktop_config=allow_desktop_config,
                )
                if _should_wrap_shortcut(title.emulator, config):
                    spec, payload_ref, payload_token = _wrap_shortcut_for_managed_launch(
                        spec,
                        emulator_name=title.emulator,
                        config=config,
                        rom_rel_path=title.rom.rel_path,
                    )
                    if payload_ref is not None and payload_token is not None:
                        payload_tokens_by_ref[payload_ref] = payload_token
                specs.append(spec)
                continue
            spec = SteamShortcutSpec(
                title_id=title.title_id,
                system=title.system,
                title_name=title.title_name,
                exe="flatpak",
                launch_options=(
                    f'run --device=all --file-forwarding {AZAHAR_FLATPAK_APP_ID} -f -- @@ "{rom_for_flatpak}" @@'
                ),
                start_dir="",
                icon_path="",
                allow_desktop_config=allow_desktop_config,
            )
            if _should_wrap_shortcut(title.emulator, config):
                spec, payload_ref, payload_token = _wrap_shortcut_for_managed_launch(
                    spec,
                    emulator_name=title.emulator,
                    config=config,
                    rom_rel_path=title.rom.rel_path,
                )
                if payload_ref is not None and payload_token is not None:
                    payload_tokens_by_ref[payload_ref] = payload_token
            specs.append(spec)
            continue
        launch_template = title.launch_template
        if "retroarch" in title.emulator.casefold():
            launch_template = _normalize_retroarch_fullscreen_launch_template(launch_template)
            launch_template = _normalize_linux_retroarch_launch_template(launch_template, config, emulator_exe)
        if "pcsx2" in title.emulator.casefold():
            launch_template = _normalize_pcsx2_launch_template(launch_template)
        if "azahar" in title.emulator.casefold():
            launch_template = _normalize_azahar_launch_template(launch_template)
        if "dolphin" in title.emulator.casefold():
            launch_template = _normalize_dolphin_launch_template(launch_template, emulator_exe, config)
        launch_line = launch_template.format(emulator=emulator_exe, rom=str(rom_path))
        windows_style = _is_windows_style_runtime_path(emulator_exe)
        parts = _split_launch_options(launch_line, windows_style=windows_style)
        if parts:
            exe = parts[0]
            if windows_style:
                launch_options = " ".join(parts[1:])
            else:
                launch_options = _join_launch_options(parts[1:], windows_style=False)
        else:
            exe = emulator_exe
            if windows_style:
                launch_options = f'"{rom_path}"'
            else:
                launch_options = _join_launch_options([str(rom_path)], windows_style=False)
        start_dir = ""
        exe_path = Path(exe.strip('"'))
        if exe_path.parent != Path("."):
            start_dir = str(exe_path.parent)
        spec = SteamShortcutSpec(
            title_id=title.title_id,
            system=title.system,
            title_name=title.title_name,
            exe=exe,
            launch_options=launch_options,
            start_dir=start_dir,
            icon_path="",
            allow_desktop_config=allow_desktop_config,
        )
        if _should_wrap_shortcut(title.emulator, config):
            spec, payload_ref, payload_token = _wrap_shortcut_for_managed_launch(
                spec,
                emulator_name=title.emulator,
                config=config,
                rom_rel_path=title.rom.rel_path,
            )
            if payload_ref is not None and payload_token is not None:
                payload_tokens_by_ref[payload_ref] = payload_token
        specs.append(spec)
    return specs, payload_tokens_by_ref


def build_shortcut_specs(
    index: LibraryIndex,
    config: GamehubConfig,
) -> list[SteamShortcutSpec]:
    specs, _ = _build_shortcut_specs_and_payloads(index, config)
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
    reseed_profiles: bool = False,
) -> None:
    context = resolve_steam_context(config)
    if context is None:
        return
    was_running = is_steam_running()
    if was_running:
        close_result = close_steam_best_effort()
        if not close_result.closed:
            reason = close_result.detail or "Steam is still running after close attempt"
            if sys.platform == "darwin":
                reason = f"{reason}; not force-killing Steam"
            if require_steam_closed:
                raise RuntimeError(f"{reason}; Steam must be closed before writing config files")
            print(f"{reason}; skipping Steam updates for safety")
            return

    backups = backup_steam_configs(context, keep_limit=config.backups.keep_limit)
    if backups:
        print(f"Backed up Steam config files: {', '.join(str(item) for item in backups)}")

    shortcut_specs, payload_tokens_by_ref = _build_shortcut_specs_and_payloads(index, config)
    if sys.platform == "darwin":
        save_shortcut_payload_registry_atomic(
            shortcut_payload_registry_path(config.state_path),
            payload_tokens_by_ref,
            keep_limit=config.backups.keep_limit,
        )
    shortcut_result = upsert_shortcuts(context, shortcut_specs)
    print(
        "Steam shortcuts synced: "
        f"managed_titles={len(shortcut_result.app_ids_by_title)} total_shortcuts={shortcut_result.total_shortcuts}"
    )
    if sys.platform.startswith("linux") and is_steam_deck_linux():
        template_sync = apply_deck_steam_input_templates(
            context,
            index,
            shortcut_result,
            overwrite_existing=reseed_profiles,
        )
        systems = ",".join(template_sync.systems_applied) if template_sync.systems_applied else "-"
        print(
            "steam-input-template-sync "
            f"systems={systems} "
            f"written={template_sync.written} "
            f"unchanged={template_sync.unchanged}"
        )
    if not shortcut_result.app_ids_by_system:
        print("Warning: no GAMEHUB appids were derived from persisted shortcuts")
    local_update_count = update_collections(context, shortcut_result.app_ids_by_system)
    cloud_update_count = update_cloud_collections(context, shortcut_result.app_ids_by_system)
    deck_repair_count = 0
    if sys.platform.startswith("linux") and is_steam_deck_linux():
        template_managed_app_ids = [
            *shortcut_result.app_ids_by_system.get("Wii", []),
            *shortcut_result.app_ids_by_system.get("N3DS", []),
        ]
        if not template_managed_app_ids:
            template_managed_app_ids = list(shortcut_result.app_ids_by_title.values())
        template_managed_app_ids = list(
            dict.fromkeys(str(app_id).strip() for app_id in template_managed_app_ids if str(app_id).strip())
        )
        deck_repair_count = repair_managed_steam_input_overrides(
            context,
            template_managed_app_ids,
            disable_cloud=True,
        )
    update_count = local_update_count + cloud_update_count + deck_repair_count
    if update_count:
        details: list[str] = []
        if local_update_count:
            details.append(f"localconfig={local_update_count}")
        if cloud_update_count:
            details.append(f"cloud={cloud_update_count}")
        if deck_repair_count:
            details.append(f"steam-input={deck_repair_count}")
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
