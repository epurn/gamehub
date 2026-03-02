from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

from gamehub_common.models import LibraryIndex, SaveSpec

from ..common.config import GamehubConfig, load_config
from ..common.save_sync import (
    build_save_lineage_record,
    classify_save_action,
    local_file_sha256,
    local_file_updated_at,
    timestamp_now_utc,
    to_utc_timestamp,
)
from ..emulators.save_resolution import resolve_local_save_destination
from . import azahar_exit_hook
from .apply import apply_controller_profile, apply_named_controller_profile
from .detection import detect_xbox_controllers, is_steam_deck_linux
from .profiles import PROFILE_KBM, profile_name_for_controller_count, seed_default_profiles
from .sdl_guid import _AZAHAR_WINDOWS_SDL_DIR_ENV

_DOLPHIN_FLATPAK_APP_ID = "org.DolphinEmu.dolphin-emu"
_DOLPHIN_LINUX_EXIT_HOOK_ENV = "GAMEHUB_DOLPHIN_LINUX_EXIT_HOOK"
_DOLPHIN_EXIT_BUTTON_SELECT_ENV = "GAMEHUB_DOLPHIN_EXIT_BUTTON_SELECT"
_DOLPHIN_EXIT_BUTTON_START_ENV = "GAMEHUB_DOLPHIN_EXIT_BUTTON_START"
_DOLPHIN_EXIT_JS_DEVICE_ENV = "GAMEHUB_DOLPHIN_EXIT_JS_DEVICE"
_AZAHAR_WINDOWS_EXIT_HOOK_ENV = "GAMEHUB_AZAHAR_WINDOWS_EXIT_HOOK"
_XINPUT_GAMEPAD_START = 0x0010
_XINPUT_GAMEPAD_BACK = 0x0020
_XINPUT_DLLS = ("xinput1_4", "xinput9_1_0", "xinput1_3")
_WM_CLOSE = 0x0010


class _XInputGamepad(ctypes.Structure):
    _fields_ = [
        ("wButtons", ctypes.c_ushort),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class _XInputState(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_ulong), ("Gamepad", _XInputGamepad)]


def _load_xinput() -> ctypes.CDLL | None:
    if not sys.platform.startswith("win"):
        return None
    for dll_name in _XINPUT_DLLS:
        try:
            lib = ctypes.WinDLL(dll_name)
        except OSError:
            continue
        try:
            lib.XInputGetState.argtypes = [ctypes.c_uint, ctypes.POINTER(_XInputState)]
            lib.XInputGetState.restype = ctypes.c_uint
        except AttributeError:
            continue
        return lib
    return None


def _xinput_combo_pressed(lib: ctypes.CDLL) -> bool:
    for index in range(4):
        state = _XInputState()
        if lib.XInputGetState(index, ctypes.byref(state)) != 0:
            continue
        buttons = int(state.Gamepad.wButtons)
        if (buttons & _XINPUT_GAMEPAD_START) and (buttons & _XINPUT_GAMEPAD_BACK):
            return True
    return False


def _send_windows_close_by_pid(pid: int) -> bool:
    if not sys.platform.startswith("win"):
        return False
    user32 = ctypes.windll.user32
    hwnds: list[int] = []

    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

    @enum_proc
    def _enum_window(hwnd: ctypes.wintypes.HWND, _lparam: ctypes.wintypes.LPARAM) -> bool:
        proc_id = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
        if proc_id.value == pid:
            hwnds.append(int(hwnd))
        return True

    user32.EnumWindows(_enum_window, 0)
    if not hwnds:
        return False
    for hwnd in hwnds:
        user32.PostMessageW(ctypes.wintypes.HWND(hwnd), _WM_CLOSE, 0, 0)
    return True


def _monitor_windows_azahar_exit_combo(process: subprocess.Popen[bytes]) -> None:
    lib = _load_xinput()
    if lib is None:
        return
    while process.poll() is None:
        if _xinput_combo_pressed(lib):
            if _send_windows_close_by_pid(process.pid):
                deadline = time.monotonic() + 2.0
                while process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.05)
            if process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    pass
            return
        time.sleep(0.1)


@dataclass(frozen=True)
class ShortcutLaunchPayload:
    version: int
    emulator: str
    target_exe: str
    target_args: tuple[str, ...]
    start_dir: str = ""
    config_path: str | None = None
    title_id: str | None = None
    system: str | None = None
    rom_rel_path: str | None = None


def encode_shortcut_payload(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    token = base64.urlsafe_b64encode(raw).decode("ascii")
    return token.rstrip("=")


def _decode_payload_token(token: str) -> dict[str, object]:
    padded = token + ("=" * (-len(token) % 4))
    raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    decoded = json.loads(raw.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("Shortcut launch payload must decode to a JSON object")
    return decoded


def _parse_target_args(raw: object) -> tuple[str, ...]:
    if isinstance(raw, list):
        return tuple(_strip_wrapping_quotes(str(item)) for item in raw)
    if isinstance(raw, tuple):
        return tuple(_strip_wrapping_quotes(str(item)) for item in raw)
    if isinstance(raw, str):
        if not raw.strip():
            return ()
        return tuple(
            _strip_wrapping_quotes(token) for token in shlex.split(raw, posix=not sys.platform.startswith("win"))
        )
    return ()


def _parse_payload_version(raw: object) -> int:
    if isinstance(raw, bool):
        return 1
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if text and text.isdigit():
            return int(text)
    return 1


def parse_shortcut_payload(token: str) -> ShortcutLaunchPayload:
    payload = _decode_payload_token(token)
    version = _parse_payload_version(payload.get("v", 1))
    emulator = str(payload.get("emulator", "")).strip().casefold()
    target_exe = str(payload.get("target_exe", "")).strip()
    if not emulator:
        raise ValueError("Shortcut launch payload missing emulator")
    if not target_exe:
        raise ValueError("Shortcut launch payload missing target_exe")

    target_args = _parse_target_args(payload.get("target_args"))
    if not target_args and isinstance(payload.get("target_launch_options"), str):
        target_args = _parse_target_args(payload["target_launch_options"])
    start_dir = _strip_wrapping_quotes(str(payload.get("start_dir", "")).strip())
    config_path = payload.get("config_path")
    config_path_str = str(config_path).strip() if isinstance(config_path, str) and config_path.strip() else None
    title_id_raw = payload.get("title_id")
    system_raw = payload.get("system")
    rom_rel_path_raw = payload.get("rom_rel_path")
    title_id = str(title_id_raw).strip() if isinstance(title_id_raw, str) and title_id_raw.strip() else None
    system = str(system_raw).strip() if isinstance(system_raw, str) and system_raw.strip() else None
    rom_rel_path = (
        str(rom_rel_path_raw).strip() if isinstance(rom_rel_path_raw, str) and rom_rel_path_raw.strip() else None
    )
    return ShortcutLaunchPayload(
        version=version,
        emulator=emulator,
        target_exe=target_exe,
        target_args=target_args,
        start_dir=start_dir,
        config_path=config_path_str,
        title_id=title_id,
        system=system,
        rom_rel_path=rom_rel_path,
    )


def _unquote_executable(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {'"', "'"}:
        return stripped[1:-1]
    return stripped


def _strip_wrapping_quotes(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {'"', "'"}:
        return stripped[1:-1]
    return stripped


def _resolve_config_path(override_config_path: Path | None, payload: ShortcutLaunchPayload) -> Path | None:
    if override_config_path is not None:
        return override_config_path.expanduser()
    if payload.config_path:
        return Path(payload.config_path).expanduser()
    return None


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


def _int_env_optional(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        return None


def _discover_js_devices(env_name: str) -> list[str]:
    env_device = os.environ.get(env_name)
    if env_device:
        return [env_device]
    dev_input = Path("/dev/input")
    if not dev_input.exists():
        return []
    devices: list[str] = []
    for candidate in sorted(dev_input.glob("js*")):
        if candidate.is_char_device() or candidate.exists():
            devices.append(str(candidate))
    return devices


def _payload_targets_flatpak_app(payload: ShortcutLaunchPayload, *, app_id: str) -> bool:
    target_exe = _unquote_executable(payload.target_exe).strip().casefold()
    if target_exe != "flatpak":
        return False
    args_folded = [arg.casefold() for arg in payload.target_args]
    return "run" in args_folded and app_id.casefold() in args_folded


def _should_use_windows_azahar_exit_hook(payload: ShortcutLaunchPayload) -> bool:
    if not sys.platform.startswith("win"):
        return False
    if "azahar" not in payload.emulator:
        return False
    return _env_enabled(_AZAHAR_WINDOWS_EXIT_HOOK_ENV, default=True)


def _should_use_linux_dolphin_exit_hook(payload: ShortcutLaunchPayload) -> bool:
    if not sys.platform.startswith("linux"):
        return False
    if "dolphin" not in payload.emulator:
        return False
    if not _env_enabled(_DOLPHIN_LINUX_EXIT_HOOK_ENV, default=True):
        return False
    return _payload_targets_flatpak_app(payload, app_id=_DOLPHIN_FLATPAK_APP_ID)


def _run_linux_dolphin_target_with_exit_hook(payload: ShortcutLaunchPayload) -> int:
    executable = _unquote_executable(payload.target_exe)
    command = [executable, *payload.target_args]
    cwd = None
    if payload.start_dir:
        candidate = Path(payload.start_dir)
        if candidate.exists():
            cwd = str(candidate)
    process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL)
    select_button = _int_env_optional(_DOLPHIN_EXIT_BUTTON_SELECT_ENV)
    start_button = _int_env_optional(_DOLPHIN_EXIT_BUTTON_START_ENV)
    js_devices = _discover_js_devices(_DOLPHIN_EXIT_JS_DEVICE_ENV)
    watcher = threading.Thread(
        target=azahar_exit_hook._monitor_combo_and_terminate,
        args=(process,),
        kwargs={
            "select_button": select_button if select_button is not None else 6,
            "start_button": start_button if start_button is not None else 7,
            "js_devices": js_devices,
            "app_id": _DOLPHIN_FLATPAK_APP_ID,
        },
        daemon=True,
    )
    watcher.start()
    return int(azahar_exit_hook._wait_for_session_exit(process, _DOLPHIN_FLATPAK_APP_ID))


def _run_windows_azahar_target_with_exit_hook(payload: ShortcutLaunchPayload) -> int:
    executable = _unquote_executable(payload.target_exe)
    command = [executable, *payload.target_args]
    cwd = None
    if payload.start_dir:
        candidate = Path(payload.start_dir)
        if candidate.exists():
            cwd = str(candidate)
    process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL)
    watcher = threading.Thread(target=_monitor_windows_azahar_exit_combo, args=(process,), daemon=True)
    watcher.start()
    return int(process.wait())


def _run_target(payload: ShortcutLaunchPayload) -> int:
    executable = _unquote_executable(payload.target_exe)
    command = [executable, *payload.target_args]
    cwd = None
    if payload.start_dir:
        candidate = Path(payload.start_dir)
        if candidate.exists():
            cwd = str(candidate)
    process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL)
    return int(process.wait())


def _run_target_with_optional_exit_hook(payload: ShortcutLaunchPayload) -> int:
    if _should_use_windows_azahar_exit_hook(payload):
        try:
            return _run_windows_azahar_target_with_exit_hook(payload)
        except Exception as exc:
            print(f"Warning: Azahar exit hook failed (error={exc}); falling back to direct launch")
    if _should_use_linux_dolphin_exit_hook(payload):
        try:
            return _run_linux_dolphin_target_with_exit_hook(payload)
        except Exception as exc:
            print(f"Warning: Dolphin exit hook failed (error={exc}); falling back to direct launch")
    return _run_target(payload)


def _detect_controller_count_once(*, max_devices: int = 2) -> tuple[int, Exception | None]:
    try:
        return len(detect_xbox_controllers(max_devices=max_devices)), None
    except Exception as exc:
        return 0, exc


@dataclass(frozen=True)
class _ShortcutSaveSnapshot:
    destination: Path | None
    local_sha256: str | None
    remote_sha256: str
    allow_postexit_upload: bool


def _load_shortcut_index(config: GamehubConfig, *, verbose: bool) -> LibraryIndex | None:
    try:
        index_module = import_module("gamehub_cli.sync.index")
        fetch_index_with_retries = index_module.fetch_index_with_retries
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: save sync could not load index fetch helper ({exc})")
        return None

    timeout_seconds = config.index_timeout_seconds if config.index_timeout_seconds is not None else 30.0
    index_url = urljoin(config.server_url.rstrip("/") + "/", "v1/index")
    try:
        raw_index = fetch_index_with_retries(
            index_url=index_url,
            timeout_seconds=timeout_seconds,
            attempts=config.index_fetch_attempts,
            retry_backoff_seconds=config.index_retry_backoff_seconds,
            verbose=verbose,
        )
        return LibraryIndex.model_validate(raw_index)
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: save sync index fetch failed ({exc})")
        return None


def _load_shortcut_state(path: Path) -> Any:
    state_module = import_module("gamehub_cli.sync.state")
    return state_module.load_state(path)


def _save_shortcut_state(path: Path, state: Any) -> None:
    state_module = import_module("gamehub_cli.sync.state")
    state_module.save_state_atomic(path, state)


def _download_save_to_destination(
    *,
    server_url: str,
    save_id: str,
    destination: Path,
    expected_sha256: str,
    timeout_seconds: float,
) -> None:
    transfer_module = import_module("gamehub_cli.sync.transfer")
    transfer_module.stream_to_destination_atomic(
        server_url=server_url,
        url=f"/v1/saves/{save_id}",
        destination=destination,
        expected_sha256=expected_sha256,
        timeout_seconds=timeout_seconds,
    )


def _upload_save_from_path(
    *,
    server_url: str,
    save_id: str,
    source: Path,
    timeout_seconds: float,
) -> SaveSpec:
    transfer_module = import_module("gamehub_cli.sync.transfer")
    payload = transfer_module.upload_file_to_server(
        server_url=server_url,
        url=f"/v1/saves/{save_id}",
        source=source,
        timeout_seconds=timeout_seconds,
    )
    return SaveSpec.model_validate(payload)


def _iter_title_saves(index: LibraryIndex, title_id: str) -> tuple[SaveSpec, ...]:
    return tuple(
        sorted(
            (save for save in index.saves if save.title_id == title_id),
            key=lambda item: (item.system, item.rel_path, item.save_id),
        )
    )


def _record_shortcut_save_sync(state: Any, save: SaveSpec, destination: Path, *, local_sha256: str) -> None:
    state.save_checksums[save.save_id] = local_sha256
    state.save_lineage[save.save_id] = build_save_lineage_record(
        local_sha256=local_sha256,
        remote_sha256=save.sha256,
        local_updated_at=local_file_updated_at(destination),
        remote_updated_at=to_utc_timestamp(save.updated_at),
        synced_at=timestamp_now_utc(),
    )
    state.unresolved_save_conflicts.pop(save.save_id, None)


def _should_sync_shortcut_saves(payload: ShortcutLaunchPayload, config: GamehubConfig) -> bool:
    if not config.save_sync.enabled:
        return False
    if not payload.title_id:
        return False
    if config.save_sync.systems and payload.system and payload.system.upper() not in config.save_sync.systems:
        return False
    return True


def _run_shortcut_prelaunch_save_sync(
    *,
    payload: ShortcutLaunchPayload,
    config: GamehubConfig,
    state: Any,
    verbose: bool,
    audit: bool,
) -> tuple[dict[str, _ShortcutSaveSnapshot], bool]:
    snapshots: dict[str, _ShortcutSaveSnapshot] = {}
    if not _should_sync_shortcut_saves(payload, config):
        return snapshots, False

    index = _load_shortcut_index(config, verbose=verbose)
    if index is None or payload.title_id is None:
        return snapshots, False

    state_changed = False
    for save in _iter_title_saves(index, payload.title_id):
        destination = resolve_local_save_destination(save)
        local_sha = local_file_sha256(destination) if destination is not None else None
        allow_postexit_upload = True
        if destination is None:
            reason = "save-path-unavailable"
            snapshots[save.save_id] = _ShortcutSaveSnapshot(
                destination=None,
                local_sha256=None,
                remote_sha256=save.sha256,
                allow_postexit_upload=False,
            )
            if verbose or audit:
                print(f"shortcut-save\tprelaunch\tskip\t{save.save_id}\t{reason}")
            continue

        lineage = state.save_lineage.get(save.save_id, {})
        decision, reason = classify_save_action(
            save_sha256=save.sha256,
            local_sha256=local_sha,
            mode=config.save_sync.mode,
            conflict_policy=config.save_sync.conflict_policy,
            lineage_local_sha=lineage.get("local_sha256"),
            lineage_remote_sha=lineage.get("remote_sha256"),
        )
        if decision == "conflict":
            state.unresolved_save_conflicts[save.save_id] = reason
            allow_postexit_upload = False
            state_changed = True
        elif decision == "download":
            try:
                _download_save_to_destination(
                    server_url=config.server_url,
                    save_id=save.save_id,
                    destination=destination,
                    expected_sha256=save.sha256,
                    timeout_seconds=config.index_timeout_seconds if config.index_timeout_seconds is not None else 30.0,
                )
                local_sha = local_file_sha256(destination)
                if local_sha is not None:
                    _record_shortcut_save_sync(state, save, destination, local_sha256=local_sha)
                    state_changed = True
            except Exception as exc:  # noqa: BLE001
                print(f"Warning: pre-launch save sync failed for {save.save_id} ({exc})")
        if verbose or audit:
            action_label = "keep-local" if decision == "upload" else decision
            print(f"shortcut-save\tprelaunch\t{action_label}\t{save.save_id}\t{reason}")
        snapshots[save.save_id] = _ShortcutSaveSnapshot(
            destination=destination,
            local_sha256=local_sha,
            remote_sha256=save.sha256,
            allow_postexit_upload=allow_postexit_upload,
        )
    return snapshots, state_changed


def _run_shortcut_postexit_save_sync(
    *,
    payload: ShortcutLaunchPayload,
    config: GamehubConfig,
    state: Any,
    snapshots: dict[str, _ShortcutSaveSnapshot],
    verbose: bool,
    audit: bool,
) -> bool:
    if config.save_sync.mode != "bidirectional" or not snapshots:
        return False
    if not _should_sync_shortcut_saves(payload, config):
        return False

    index = _load_shortcut_index(config, verbose=verbose)
    if index is None or payload.title_id is None:
        return False

    current_saves = {save.save_id: save for save in _iter_title_saves(index, payload.title_id)}
    state_changed = False
    for save_id, snapshot in snapshots.items():
        if snapshot.destination is None or not snapshot.allow_postexit_upload:
            continue
        local_sha = local_file_sha256(snapshot.destination)
        if local_sha is None or local_sha == snapshot.local_sha256:
            continue
        save = current_saves.get(save_id)
        if save is None or save.sha256 != snapshot.remote_sha256:
            state.unresolved_save_conflicts[save_id] = "remote-changed-during-session"
            state_changed = True
            if verbose or audit:
                print(f"shortcut-save\tpostexit\tconflict\t{save_id}\tremote-changed-during-session")
            continue
        try:
            updated_save = _upload_save_from_path(
                server_url=config.server_url,
                save_id=save_id,
                source=snapshot.destination,
                timeout_seconds=config.index_timeout_seconds if config.index_timeout_seconds is not None else 30.0,
            )
            state.save_checksums[save_id] = local_sha
            state.save_lineage[save_id] = build_save_lineage_record(
                local_sha256=local_sha,
                remote_sha256=updated_save.sha256,
                local_updated_at=local_file_updated_at(snapshot.destination),
                remote_updated_at=to_utc_timestamp(updated_save.updated_at),
                synced_at=timestamp_now_utc(),
            )
            state.unresolved_save_conflicts.pop(save_id, None)
            state_changed = True
            if verbose or audit:
                print(f"shortcut-save\tpostexit\tupload\t{save_id}\tauto-upload")
        except Exception as exc:  # noqa: BLE001
            print(f"Warning: post-exit save upload failed for {save_id} ({exc})")
    return state_changed


def run_shortcut_launch(*, payload_token: str, config_path: Path | None = None, audit: bool = False) -> int:
    payload = parse_shortcut_payload(payload_token)
    resolved_config = _resolve_config_path(config_path, payload)
    config = load_config(resolved_config)
    state: Any = None
    save_state: Callable[[Path, Any], None] | None = None
    state_changed = False

    if _should_sync_shortcut_saves(payload, config):
        try:
            state = _load_shortcut_state(config.state_path)
            save_state = _save_shortcut_state
        except Exception as exc:  # noqa: BLE001
            print(f"Warning: save sync state helpers unavailable ({exc})")
            state = None
            save_state = None

    if "azahar" in payload.emulator:
        target_exe = _unquote_executable(payload.target_exe)
        candidate = Path(target_exe)
        if target_exe and _AZAHAR_WINDOWS_SDL_DIR_ENV not in os.environ:
            if candidate.exists():
                os.environ[_AZAHAR_WINDOWS_SDL_DIR_ENV] = str(candidate.parent)

    if config.controllers.launch_autoconfig:
        try:
            seed_default_profiles(config)
        except Exception as exc:
            print(f"Warning: failed to seed controller profile defaults (error={exc})")
        detected_controller_count, detect_error = _detect_controller_count_once(max_devices=2)
        controller_count = detected_controller_count
        if detect_error is not None:
            print(
                "Warning: controller detection failed "
                f"(emulator={payload.emulator}, error={detect_error}); using keyboard/mouse fallback profile selection"
            )
        zero_detect_policy = "none"
        native_shortcut_policy = "native-first"
        if sys.platform.startswith("linux") and is_steam_deck_linux() and controller_count == 0:
            zero_detect_policy = "xbox_1p"
            controller_count = 1
            print("Warning: Steam Deck controller detection returned 0 controllers; forcing xbox_1p profile fallback")
        effective_controller_count = controller_count
        if audit:
            detect_status = "ok" if detect_error is None else "error"
            print(
                "controller-autoconfig\t"
                f"detected_controller_count={detected_controller_count}\t"
                f"effective_controller_count={effective_controller_count}\t"
                f"detect_status={detect_status}\t"
                f"zero_detect_policy={zero_detect_policy}\t"
                f"native_shortcut_policy={native_shortcut_policy}"
            )

        selected_profile = profile_name_for_controller_count(controller_count)
        try:
            if audit:
                selected_profile = apply_controller_profile(
                    config,
                    emulator_name=payload.emulator,
                    controller_count=controller_count,
                    verbose=True,
                )
            else:
                selected_profile = apply_controller_profile(
                    config,
                    emulator_name=payload.emulator,
                    controller_count=controller_count,
                )
            if audit:
                print(f"controller-autoconfig\tselected_profile={selected_profile}")
        except Exception as exc:
            print(
                "Warning: controller autoconfig failed "
                f"(emulator={payload.emulator}, profile={PROFILE_KBM}, error={exc}); using keyboard/mouse fallback"
            )
            try:
                if audit:
                    selected_profile = apply_named_controller_profile(
                        config,
                        emulator_name=payload.emulator,
                        profile_name=PROFILE_KBM,
                        verbose=True,
                    )
                else:
                    selected_profile = apply_named_controller_profile(
                        config,
                        emulator_name=payload.emulator,
                        profile_name=PROFILE_KBM,
                    )
                if audit:
                    print(f"controller-autoconfig\tselected_profile={selected_profile}\tfallback=true")
            except Exception as fallback_exc:
                print(
                    "Warning: keyboard/mouse fallback profile application failed "
                    f"(emulator={payload.emulator}, error={fallback_exc})"
                )
    snapshots: dict[str, _ShortcutSaveSnapshot] = {}
    if state is not None:
        snapshots, prelaunch_changed = _run_shortcut_prelaunch_save_sync(
            payload=payload,
            config=config,
            state=state,
            verbose=False,
            audit=audit,
        )
        state_changed = state_changed or prelaunch_changed

    exit_code = _run_target_with_optional_exit_hook(payload)

    if state is not None:
        postexit_changed = _run_shortcut_postexit_save_sync(
            payload=payload,
            config=config,
            state=state,
            snapshots=snapshots,
            verbose=False,
            audit=audit,
        )
        state_changed = state_changed or postexit_changed
        if state_changed and save_state is not None:
            save_state(config.state_path, state)
    return exit_code
