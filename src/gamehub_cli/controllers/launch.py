from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import json
import logging
import os
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Literal, cast
from urllib.parse import urljoin

from gamehub_common.ids import make_save_id
from gamehub_common.models import LibraryIndex, SaveBindingCatalog, SaveBindingSpec, SaveSpec

from ..common.config import GamehubConfig, load_config
from ..common.save_sync import (
    build_save_lineage_record,
    canonical_suffix_for_save,
    classify_save_action,
    local_file_sha256,
    local_file_updated_at,
    save_binding_id_for_save,
    timestamp_now_utc,
    to_utc_timestamp,
)
from ..emulators.save_resolution import (
    canonical_suffix_for_learned_path,
    learn_binding_root,
    resolve_binding_local_root,
    resolve_exact_local_save_destination,
    resolve_local_save_destination,
    snapshot_binding_tree,
)
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
logger = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class _ShortcutTreeSnapshot:
    binding: SaveBindingSpec
    before: dict[str, str]


@dataclass(frozen=True)
class _ShortcutExactBindingSnapshot:
    binding: SaveBindingSpec
    local_sha256_by_suffix: dict[str, str | None]


@dataclass
class _ShortcutSaveContext:
    save_snapshots: dict[str, _ShortcutSaveSnapshot]
    exact_binding_snapshots: dict[str, _ShortcutExactBindingSnapshot]
    tree_snapshots: dict[str, _ShortcutTreeSnapshot]


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


def _load_shortcut_save_bindings(config: GamehubConfig, *, verbose: bool) -> SaveBindingCatalog | None:
    try:
        index_module = import_module("gamehub_cli.sync.index")
        fetch_save_bindings_with_retries = index_module.fetch_save_bindings_with_retries
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: save sync could not load save binding helper ({exc})")
        return None

    timeout_seconds = config.index_timeout_seconds if config.index_timeout_seconds is not None else 30.0
    bindings_url = urljoin(config.server_url.rstrip("/") + "/", "v1/save-bindings")
    try:
        raw_bindings = fetch_save_bindings_with_retries(
            bindings_url=bindings_url,
            timeout_seconds=timeout_seconds,
            attempts=config.index_fetch_attempts,
            retry_backoff_seconds=config.index_retry_backoff_seconds,
            verbose=verbose,
        )
        return SaveBindingCatalog.model_validate(raw_bindings)
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: save sync binding fetch failed ({exc})")
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
    save: SaveSpec,
    source: Path,
    timeout_seconds: float,
) -> SaveSpec:
    transfer_module = import_module("gamehub_cli.sync.transfer")
    payload = transfer_module.upload_file_to_server(
        server_url=server_url,
        url=f"/v1/saves/{save.save_id}",
        source=source,
        binding_id=save_binding_id_for_save(save),
        canonical_suffix=canonical_suffix_for_save(save),
        timeout_seconds=timeout_seconds,
        expected_remote_sha256=save.sha256,
    )
    return SaveSpec.model_validate(payload)


def _upload_new_save_from_path(
    *,
    server_url: str,
    save_id: str,
    binding: SaveBindingSpec,
    canonical_suffix: str,
    source: Path,
    timeout_seconds: float,
) -> SaveSpec:
    transfer_module = import_module("gamehub_cli.sync.transfer")
    payload = transfer_module.upload_file_to_server(
        server_url=server_url,
        url=f"/v1/saves/{save_id}",
        source=source,
        binding_id=binding.binding_id,
        canonical_suffix=canonical_suffix,
        timeout_seconds=timeout_seconds,
        expected_remote_sha256=None,
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


def _record_binding_root(state: Any, *, binding_id: str, canonical_root: str, materialized_root: str) -> None:
    state.save_binding_roots[binding_id] = {
        "canonical_root": canonical_root,
        "materialized_root": materialized_root,
    }


def _changed_tree_paths(before: dict[str, str], after: dict[str, str]) -> tuple[str, ...]:
    changed = {rel_path for rel_path, sha in after.items() if rel_path not in before or before[rel_path] != sha}
    return tuple(sorted(changed))


def _snapshot_exact_binding(
    binding: SaveBindingSpec,
    *,
    remote_save_ids: set[str],
) -> _ShortcutExactBindingSnapshot | None:
    if binding.strategy != "exact_files":
        return None
    root = resolve_binding_local_root(binding)
    if root is None:
        return None
    local_sha256_by_suffix: dict[str, str | None] = {}
    exact_kind = cast(Literal["battery", "memory_card"], binding.kind)
    for filename in binding.candidate_filenames:
        save_id = make_save_id(f"{binding.server_rel_dir}/{filename}")
        if save_id in remote_save_ids:
            continue
        destination = resolve_exact_local_save_destination(
            system=binding.system,
            kind=exact_kind,
            root=root,
            filename=filename,
        )
        local_sha256_by_suffix[filename] = local_file_sha256(destination)
    if not local_sha256_by_suffix:
        return None
    return _ShortcutExactBindingSnapshot(binding=binding, local_sha256_by_suffix=local_sha256_by_suffix)


def _run_shortcut_postexit_exact_binding_sync(
    *,
    state: Any,
    current_saves: dict[str, SaveSpec],
    exact_snapshots: dict[str, _ShortcutExactBindingSnapshot],
    server_url: str,
    timeout_seconds: float,
    verbose: bool,
    audit: bool,
) -> bool:
    state_changed = False
    for exact_snapshot in exact_snapshots.values():
        binding = exact_snapshot.binding
        root = resolve_binding_local_root(binding)
        if root is None:
            continue
        exact_kind = cast(Literal["battery", "memory_card"], binding.kind)
        for filename in binding.candidate_filenames:
            before_sha = exact_snapshot.local_sha256_by_suffix.get(filename)
            if filename not in exact_snapshot.local_sha256_by_suffix:
                continue
            destination = resolve_exact_local_save_destination(
                system=binding.system,
                kind=exact_kind,
                root=root,
                filename=filename,
            )
            local_sha = local_file_sha256(destination)
            if local_sha is None:
                continue
            save_id = make_save_id(f"{binding.server_rel_dir}/{filename}")
            save = current_saves.get(save_id)
            if save is not None:
                if local_sha == save.sha256:
                    _record_shortcut_save_sync(state, save, destination, local_sha256=local_sha)
                    state_changed = True
                    if verbose or audit:
                        print(f"shortcut-save\tpostexit\tskip\t{save_id}\talready-synced")
                    continue
                state.unresolved_save_conflicts[save_id] = "create-race-content-mismatch"
                state_changed = True
                if verbose or audit:
                    print(f"shortcut-save\tpostexit\tconflict\t{save_id}\tcreate-race-content-mismatch")
                continue
            try:
                created_save = _upload_new_save_from_path(
                    server_url=server_url,
                    save_id=save_id,
                    binding=binding,
                    canonical_suffix=filename,
                    source=destination,
                    timeout_seconds=timeout_seconds,
                )
                state.save_checksums[save_id] = local_sha
                state.save_lineage[save_id] = build_save_lineage_record(
                    local_sha256=local_sha,
                    remote_sha256=created_save.sha256,
                    local_updated_at=local_file_updated_at(destination),
                    remote_updated_at=to_utc_timestamp(created_save.updated_at),
                    synced_at=timestamp_now_utc(),
                )
                state.unresolved_save_conflicts.pop(save_id, None)
                state_changed = True
                action = "auto-create" if before_sha is None else "auto-create-existing-local"
                if verbose or audit:
                    print(f"shortcut-save\tpostexit\tupload\t{save_id}\t{action}")
            except Exception as exc:  # noqa: BLE001
                state.unresolved_save_conflicts[save_id] = "create-race-or-upload-failed"
                state_changed = True
                print(f"Warning: post-exit save upload failed for {save_id} ({exc})")
    return state_changed


def _ensure_managed_memory_card_paths(payload: ShortcutLaunchPayload, config: GamehubConfig) -> bool:
    if not payload.title_id or payload.system not in {"PSX", "PS2"}:
        return False

    if payload.system == "PS2":
        targets = {
            "Slot1_Filename": f"GH_{payload.title_id}_1.ps2",
            "Slot2_Filename": f"GH_{payload.title_id}_2.ps2",
        }
        targets["Slot1_Enable"] = "true"
        targets["Slot2_Enable"] = "true"
        firmware_targets = import_module("gamehub_cli.firmware.targets")
        pcsx2_ini = import_module("gamehub_cli.firmware.pcsx2_ini")
        fsops = import_module("gamehub_cli.common.fsops")
        path = firmware_targets.default_pcsx2_ini_path(config=config)
        lines = pcsx2_ini.read_ini_lines(path)
        changed = False
        for key, value in targets.items():
            lines, key_changed = pcsx2_ini.upsert_ini_key(lines, "MemoryCards", key, value)
            changed |= key_changed
        if changed or not path.exists():
            if path.exists():
                backup = fsops.backup_existing_file(path)
                if backup is not None:
                    logger.info("managed memory-card backup created path=%s backup=%s", path, backup)
            pcsx2_ini.write_ini_atomic(path, lines)
            logger.info(
                "managed memory-card config updated path=%s system=%s title_id=%s",
                path,
                payload.system,
                payload.title_id,
            )
        return changed

    if payload.system == "PSX":
        firmware_targets = import_module("gamehub_cli.firmware.targets")
        config_edit = import_module("gamehub_cli.common.config_edit")
        pcsx2_ini = import_module("gamehub_cli.firmware.pcsx2_ini")
        fsops = import_module("gamehub_cli.common.fsops")
        cfg_candidates = firmware_targets.retroarch_cfg_candidates_for_config(config=config)
        cfg_path = next(
            (candidate for candidate in cfg_candidates if candidate.exists()),
            cfg_candidates[0] if cfg_candidates else None,
        )
        if cfg_path is None:
            return False
        core_options_path = cfg_path.with_name("retroarch-core-options.cfg")
        lines = pcsx2_ini.read_ini_lines(core_options_path)
        changed = False
        for key, value in {
            "swanstation_MemoryCard1Path": f"GH_{payload.title_id}_1.mcd",
            "swanstation_MemoryCard2Path": f"GH_{payload.title_id}_2.mcd",
        }.items():
            lines, key_changed = config_edit.upsert_simple_cfg_key(lines, key, value)
            changed |= key_changed
        if changed or not core_options_path.exists():
            if core_options_path.exists():
                backup = fsops.backup_existing_file(core_options_path)
                if backup is not None:
                    logger.info("managed memory-card backup created path=%s backup=%s", core_options_path, backup)
            pcsx2_ini.write_ini_atomic(core_options_path, lines)
            logger.info(
                "managed memory-card config updated path=%s system=%s title_id=%s",
                core_options_path,
                payload.system,
                payload.title_id,
            )
        return changed

    return False


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
) -> tuple[_ShortcutSaveContext, bool]:
    context = _ShortcutSaveContext(save_snapshots={}, exact_binding_snapshots={}, tree_snapshots={})
    if not _should_sync_shortcut_saves(payload, config):
        return context, False

    index = _load_shortcut_index(config, verbose=verbose)
    if index is None or payload.title_id is None:
        return context, False

    save_bindings = _load_shortcut_save_bindings(config, verbose=verbose)
    title_saves = _iter_title_saves(index, payload.title_id)
    remote_save_ids = {save.save_id for save in title_saves}
    if save_bindings is not None and config.save_sync.mode == "bidirectional":
        for binding in save_bindings.bindings:
            if binding.title_id != payload.title_id:
                continue
            if binding.strategy == "learned_tree":
                context.tree_snapshots[binding.binding_id] = _ShortcutTreeSnapshot(
                    binding=binding,
                    before=snapshot_binding_tree(binding),
                )
                continue
            exact_snapshot = _snapshot_exact_binding(binding, remote_save_ids=remote_save_ids)
            if exact_snapshot is not None:
                context.exact_binding_snapshots[binding.binding_id] = exact_snapshot

    state_changed = False
    for save in title_saves:
        destination = resolve_local_save_destination(save, binding_roots=state.save_binding_roots)
        local_sha = local_file_sha256(destination) if destination is not None else None
        allow_postexit_upload = True
        if destination is None:
            reason = "save-path-unavailable"
            context.save_snapshots[save.save_id] = _ShortcutSaveSnapshot(
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
            action_label = "keep-local" if decision == "upload_existing" else decision
            print(f"shortcut-save\tprelaunch\t{action_label}\t{save.save_id}\t{reason}")
        context.save_snapshots[save.save_id] = _ShortcutSaveSnapshot(
            destination=destination,
            local_sha256=local_sha,
            remote_sha256=save.sha256,
            allow_postexit_upload=allow_postexit_upload,
        )
    return context, state_changed


def _run_shortcut_postexit_save_sync(
    *,
    payload: ShortcutLaunchPayload,
    config: GamehubConfig,
    state: Any,
    context: _ShortcutSaveContext,
    verbose: bool,
    audit: bool,
) -> bool:
    if config.save_sync.mode != "bidirectional" or (
        not context.save_snapshots and not context.exact_binding_snapshots and not context.tree_snapshots
    ):
        return False
    if not _should_sync_shortcut_saves(payload, config):
        return False

    index = _load_shortcut_index(config, verbose=verbose)
    if index is None or payload.title_id is None:
        return False

    current_saves = {save.save_id: save for save in _iter_title_saves(index, payload.title_id)}
    state_changed = False
    for save_id, snapshot in context.save_snapshots.items():
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
                save=save,
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

    exact_binding_changed = _run_shortcut_postexit_exact_binding_sync(
        state=state,
        current_saves=current_saves,
        exact_snapshots=context.exact_binding_snapshots,
        server_url=config.server_url,
        timeout_seconds=config.index_timeout_seconds if config.index_timeout_seconds is not None else 30.0,
        verbose=verbose,
        audit=audit,
    )
    state_changed = state_changed or exact_binding_changed

    for binding_id, tree_snapshot in context.tree_snapshots.items():
        binding = tree_snapshot.binding
        after = snapshot_binding_tree(binding)
        changed_paths = _changed_tree_paths(tree_snapshot.before, after)
        if not changed_paths:
            continue
        learned_root = learn_binding_root(binding, changed_paths)
        if learned_root is None:
            state.unresolved_save_conflicts[binding_id] = "save-binding-root-ambiguous"
            state_changed = True
            if verbose or audit:
                print(f"shortcut-save\tpostexit\tconflict\t{binding_id}\tsave-binding-root-ambiguous")
            continue
        canonical_root, materialized_root = learned_root
        _record_binding_root(
            state,
            binding_id=binding.binding_id,
            canonical_root=canonical_root,
            materialized_root=materialized_root,
        )
        state.unresolved_save_conflicts.pop(binding_id, None)
        state_changed = True
        root = resolve_binding_local_root(binding)
        if root is None:
            continue
        for rel_path in changed_paths:
            canonical_suffix = canonical_suffix_for_learned_path(
                binding,
                rel_path,
                materialized_root=materialized_root,
            )
            if canonical_suffix is None:
                continue
            save_id = make_save_id(f"{binding.server_rel_dir}/{canonical_suffix}")
            if save_id in current_saves:
                continue
            source = root / Path(*PurePosixPath(rel_path).parts)
            local_sha = local_file_sha256(source)
            if local_sha is None:
                continue
            try:
                created_save = _upload_new_save_from_path(
                    server_url=config.server_url,
                    save_id=save_id,
                    binding=binding,
                    canonical_suffix=canonical_suffix,
                    source=source,
                    timeout_seconds=config.index_timeout_seconds if config.index_timeout_seconds is not None else 30.0,
                )
                state.save_checksums[save_id] = local_sha
                state.save_lineage[save_id] = build_save_lineage_record(
                    local_sha256=local_sha,
                    remote_sha256=created_save.sha256,
                    local_updated_at=local_file_updated_at(source),
                    remote_updated_at=to_utc_timestamp(created_save.updated_at),
                    synced_at=timestamp_now_utc(),
                )
                state.unresolved_save_conflicts.pop(save_id, None)
                state_changed = True
                if verbose or audit:
                    print(f"shortcut-save\tpostexit\tupload\t{save_id}\tauto-create")
            except Exception as exc:  # noqa: BLE001
                state.unresolved_save_conflicts[save_id] = "create-race-or-upload-failed"
                state_changed = True
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
    if config.save_sync.enabled:
        try:
            _ensure_managed_memory_card_paths(payload, config)
        except Exception as exc:  # noqa: BLE001
            print(f"Warning: managed memory-card setup failed ({exc})")
    save_context = _ShortcutSaveContext(save_snapshots={}, exact_binding_snapshots={}, tree_snapshots={})
    if state is not None:
        try:
            save_context, prelaunch_changed = _run_shortcut_prelaunch_save_sync(
                payload=payload,
                config=config,
                state=state,
                verbose=False,
                audit=audit,
            )
            state_changed = state_changed or prelaunch_changed
        except Exception as exc:  # noqa: BLE001
            print(f"Warning: pre-launch save sync failed; continuing launch ({exc})")

    exit_code = _run_target_with_optional_exit_hook(payload)

    if state is not None:
        try:
            postexit_changed = _run_shortcut_postexit_save_sync(
                payload=payload,
                config=config,
                state=state,
                context=save_context,
                verbose=False,
                audit=audit,
            )
            state_changed = state_changed or postexit_changed
        except Exception as exc:  # noqa: BLE001
            print(f"Warning: post-exit save sync failed ({exc})")
        if state_changed and save_state is not None:
            save_state(config.state_path, state)
    return exit_code
