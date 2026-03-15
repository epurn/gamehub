from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

from ..common.config import GamehubConfig
from ..common.platform_paths import DOLPHIN_FLATPAK_APP_ID
from ..common.shortcut_payload import ShortcutLaunchPayload, unquote_executable
from ..controllers import azahar_exit_hook
from ..controllers.apply import apply_controller_profile, apply_named_controller_profile
from ..controllers.detection import detect_xbox_controllers, is_steam_deck_linux
from ..controllers.profiles import PROFILE_KBM, profile_name_for_controller_count
from ..controllers.sdl_guid import _AZAHAR_WINDOWS_SDL_DIR_ENV

_DOLPHIN_LINUX_EXIT_HOOK_ENV = "GAMEHUB_DOLPHIN_LINUX_EXIT_HOOK"
_DOLPHIN_EXIT_BUTTON_SELECT_ENV = "GAMEHUB_DOLPHIN_EXIT_BUTTON_SELECT"
_DOLPHIN_EXIT_BUTTON_START_ENV = "GAMEHUB_DOLPHIN_EXIT_BUTTON_START"
_DOLPHIN_EXIT_JS_DEVICE_ENV = "GAMEHUB_DOLPHIN_EXIT_JS_DEVICE"
_AZAHAR_WINDOWS_EXIT_HOOK_ENV = "GAMEHUB_AZAHAR_WINDOWS_EXIT_HOOK"
_AZAHAR_MACOS_EXIT_HOOK_ENV = "GAMEHUB_AZAHAR_MACOS_EXIT_HOOK"
_XINPUT_GAMEPAD_START = 0x0010
_XINPUT_GAMEPAD_BACK = 0x0020
_XINPUT_DLLS = ("xinput1_4", "xinput9_1_0", "xinput1_3")
_WM_CLOSE = 0x0010
_MACOS_OPEN_EXECUTABLE = "/usr/bin/open"
_AZAHAR_MACOS_DOCUMENT_EXTENSIONS = {".3dsx", ".cci", ".cxi", ".cia", ".3ds", ".elf", ".axf"}
_AZAHAR_FULLSCREEN_ARGS = {"-f", "--fullscreen"}


def warn_shortcut_runtime(message: str) -> None:
    rendered = f"Warning: {message}"
    try:
        sys.stderr.write(f"{rendered}\n")
        sys.stderr.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass


class ShortcutLaunchError(RuntimeError):
    """Raised when the managed shortcut target cannot be spawned."""


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


def _payload_targets_flatpak_app(payload: ShortcutLaunchPayload, *, app_id: str) -> bool:
    target_exe = unquote_executable(payload.target_exe).strip().casefold()
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


def _should_use_macos_azahar_exit_hook(payload: ShortcutLaunchPayload) -> bool:
    if sys.platform != "darwin":
        return False
    if "azahar" not in payload.emulator:
        return False
    return _env_enabled(_AZAHAR_MACOS_EXIT_HOOK_ENV, default=True)


def _should_use_linux_dolphin_exit_hook(payload: ShortcutLaunchPayload) -> bool:
    if not sys.platform.startswith("linux"):
        return False
    if "dolphin" not in payload.emulator:
        return False
    if not _env_enabled(_DOLPHIN_LINUX_EXIT_HOOK_ENV, default=True):
        return False
    return _payload_targets_flatpak_app(payload, app_id=DOLPHIN_FLATPAK_APP_ID)


def _run_linux_dolphin_target_with_exit_hook(payload: ShortcutLaunchPayload) -> int:
    executable = unquote_executable(payload.target_exe)
    command = [executable, *payload.target_args]
    cwd = None
    if payload.start_dir:
        candidate = Path(payload.start_dir)
        if candidate.exists():
            cwd = str(candidate)
    process = _spawn_shortcut_process(command, cwd=cwd)
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
            "app_id": DOLPHIN_FLATPAK_APP_ID,
        },
        daemon=True,
    )
    watcher.start()
    return int(azahar_exit_hook._wait_for_session_exit(process, DOLPHIN_FLATPAK_APP_ID))


def _run_windows_azahar_target_with_exit_hook(payload: ShortcutLaunchPayload) -> int:
    executable = unquote_executable(payload.target_exe)
    command = [executable, *payload.target_args]
    cwd = _resolve_launch_cwd(payload)
    process = _spawn_shortcut_process(command, cwd=cwd)
    watcher = threading.Thread(target=_monitor_windows_azahar_exit_combo, args=(process,), daemon=True)
    watcher.start()
    return int(process.wait())


def _run_macos_azahar_target_with_exit_hook(payload: ShortcutLaunchPayload) -> int:
    raw_app_bundle = payload.macos_open_app
    if raw_app_bundle is None:
        raise ShortcutLaunchError("launch failed (error=missing macOS app bundle target)")
    app_bundle = raw_app_bundle.strip().strip('"')
    if not app_bundle:
        raise ShortcutLaunchError("launch failed (error=missing macOS app bundle target)")
    documents, passthrough_args = _split_macos_azahar_launch_args(payload)
    if not documents:
        raise ShortcutLaunchError("launch failed (error=missing Azahar document target)")
    command = [_MACOS_OPEN_EXECUTABLE, "-W", "-a", app_bundle, *documents]
    if passthrough_args:
        command.extend(["--args", *passthrough_args])
    process_name = Path(unquote_executable(payload.target_exe)).name
    prelaunch_pids = azahar_exit_hook._discover_process_ids_by_name(process_name)
    process = _spawn_shortcut_process(command, cwd=None)
    select_button, start_button = azahar_exit_hook._resolve_select_and_start_buttons()
    controller_port = azahar_exit_hook._resolve_port_from_config()
    bundle_id = azahar_exit_hook._resolve_macos_bundle_identifier(app_bundle)
    watcher = threading.Thread(
        target=azahar_exit_hook._monitor_macos_combo_and_terminate,
        args=(process,),
        kwargs={
            "select_button": select_button,
            "start_button": start_button,
            "controller_port": controller_port,
            "bundle_id": bundle_id,
            "process_name": process_name,
            "prelaunch_pids": prelaunch_pids,
        },
        daemon=True,
    )
    watcher.start()
    return int(process.wait())


def _resolve_launch_cwd(payload: ShortcutLaunchPayload) -> str | None:
    if not payload.start_dir:
        return None
    candidate = Path(payload.start_dir)
    if not candidate.exists():
        return None
    return str(candidate)


def _render_launch_command(command: list[str]) -> str:
    if sys.platform.startswith("win"):
        return subprocess.list2cmdline(command)
    return shlex.join(command)


def _is_windows_frozen_runtime() -> bool:
    return sys.platform.startswith("win") and bool(getattr(sys, "frozen", False))


def _windows_meipass_root() -> str | None:
    raw = getattr(sys, "_MEIPASS", None)
    if not isinstance(raw, str):
        return None
    normalized = raw.strip()
    return normalized or None


def _sanitize_windows_path_for_external_process(path_value: str, *, meipass_root: str | None) -> str:
    if not path_value or not meipass_root:
        return path_value

    delimiter = ";"
    meipass_marker = meipass_root.replace("\\", "/").rstrip("/").casefold()
    sanitized_entries: list[str] = []
    for raw_entry in path_value.split(delimiter):
        entry = raw_entry.strip()
        if not entry:
            continue
        normalized = entry.strip('"').replace("\\", "/").rstrip("/").casefold()
        if normalized == meipass_marker or normalized.startswith(f"{meipass_marker}/"):
            continue
        sanitized_entries.append(raw_entry)
    return delimiter.join(sanitized_entries)


def _set_windows_dll_directory(path: str | None) -> bool:
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return False
    kernel32 = getattr(windll, "kernel32", None)
    if kernel32 is None:
        return False
    set_dll_directory = getattr(kernel32, "SetDllDirectoryW", None)
    if set_dll_directory is None:
        return False
    try:
        return bool(set_dll_directory(path))
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def _prepare_external_process_environment() -> tuple[dict[str, str] | None, str | None]:
    if not _is_windows_frozen_runtime():
        return None, None

    env = dict(os.environ)
    meipass_root = _windows_meipass_root()
    path_value = env.get("PATH", "")
    env["PATH"] = _sanitize_windows_path_for_external_process(path_value, meipass_root=meipass_root)

    restored_dll_directory: str | None = None
    if _set_windows_dll_directory(None):
        restored_dll_directory = meipass_root
    else:
        warn_shortcut_runtime("unable to reset frozen Windows DLL search path before emulator launch")
    return env, restored_dll_directory


def _spawn_shortcut_process(command: list[str], *, cwd: str | None) -> subprocess.Popen[bytes]:
    env, restored_dll_directory = _prepare_external_process_environment()
    try:
        if env is None:
            return subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL)
        return subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL, env=env)
    except OSError as exc:
        raise ShortcutLaunchError(f"launch failed (command={_render_launch_command(command)}, error={exc})") from exc
    finally:
        if restored_dll_directory is not None:
            _set_windows_dll_directory(restored_dll_directory)


def _run_macos_bundle_target(payload: ShortcutLaunchPayload) -> int:
    raw_app_bundle = payload.macos_open_app
    if raw_app_bundle is None:
        raise ShortcutLaunchError("launch failed (error=missing macOS app bundle target)")
    app_bundle = raw_app_bundle.strip().strip('"')
    if not app_bundle:
        raise ShortcutLaunchError("launch failed (error=missing macOS app bundle target)")
    command = [_MACOS_OPEN_EXECUTABLE, "-W"]
    if "azahar" in payload.emulator:
        command.append(app_bundle)
    else:
        command.extend(["-a", app_bundle])
    if payload.macos_open_args:
        command.extend(["--args", *payload.macos_open_args])
    process = _spawn_shortcut_process(command, cwd=_resolve_launch_cwd(payload))
    return int(process.wait())


def _split_macos_azahar_launch_args(payload: ShortcutLaunchPayload) -> tuple[list[str], list[str]]:
    documents: list[str] = []
    passthrough_args: list[str] = []
    for arg in payload.macos_open_args or payload.target_args:
        normalized = str(arg).strip()
        if not normalized:
            continue
        if normalized in _AZAHAR_FULLSCREEN_ARGS:
            continue
        if Path(normalized).suffix.casefold() in _AZAHAR_MACOS_DOCUMENT_EXTENSIONS:
            documents.append(normalized)
            continue
        passthrough_args.append(normalized)
    return documents, passthrough_args


def _run_macos_azahar_target_as_document(payload: ShortcutLaunchPayload) -> int:
    raw_app_bundle = payload.macos_open_app
    if raw_app_bundle is None:
        raise ShortcutLaunchError("launch failed (error=missing macOS app bundle target)")
    app_bundle = raw_app_bundle.strip().strip('"')
    if not app_bundle:
        raise ShortcutLaunchError("launch failed (error=missing macOS app bundle target)")
    documents, passthrough_args = _split_macos_azahar_launch_args(payload)
    if not documents:
        raise ShortcutLaunchError("launch failed (error=missing Azahar document target)")
    command = [_MACOS_OPEN_EXECUTABLE, "-W", "-a", app_bundle, *documents]
    if passthrough_args:
        command.extend(["--args", *passthrough_args])
    process = _spawn_shortcut_process(command, cwd=None)
    return int(process.wait())


def _run_macos_azahar_target_direct(payload: ShortcutLaunchPayload) -> int:
    executable = unquote_executable(payload.target_exe)
    if not executable:
        raise ShortcutLaunchError("launch failed (error=missing Azahar executable target)")
    candidate = Path(executable)
    cwd = _resolve_launch_cwd(payload)
    if candidate.exists():
        cwd = str(candidate.parent)
    command = [executable, *payload.target_args]
    process = _spawn_shortcut_process(command, cwd=cwd)
    return int(process.wait())


def _run_target(payload: ShortcutLaunchPayload) -> int:
    if sys.platform == "darwin" and payload.macos_open_app:
        if "azahar" in payload.emulator:
            try:
                return _run_macos_azahar_target_as_document(payload)
            except Exception as exc:
                warn_shortcut_runtime(f"Azahar document launch failed (error={exc}); falling back to direct launch")
            try:
                return _run_macos_azahar_target_direct(payload)
            except Exception as exc:
                warn_shortcut_runtime(f"Azahar direct launch failed (error={exc}); falling back to bundle launch")
        return _run_macos_bundle_target(payload)
    executable = unquote_executable(payload.target_exe)
    command = [executable, *payload.target_args]
    process = _spawn_shortcut_process(command, cwd=_resolve_launch_cwd(payload))
    return int(process.wait())


def _run_target_with_optional_exit_hook(payload: ShortcutLaunchPayload) -> int:
    if _should_use_windows_azahar_exit_hook(payload):
        try:
            return _run_windows_azahar_target_with_exit_hook(payload)
        except Exception as exc:
            warn_shortcut_runtime(f"Azahar exit hook failed (error={exc}); falling back to direct launch")
    if _should_use_macos_azahar_exit_hook(payload):
        try:
            return _run_macos_azahar_target_with_exit_hook(payload)
        except Exception as exc:
            warn_shortcut_runtime(f"Azahar macOS exit hook failed (error={exc}); falling back to managed launch")
    if _should_use_linux_dolphin_exit_hook(payload):
        try:
            return _run_linux_dolphin_target_with_exit_hook(payload)
        except Exception as exc:
            warn_shortcut_runtime(f"Dolphin exit hook failed (error={exc}); falling back to direct launch")
    return _run_target(payload)


def _detect_controller_count_once(*, max_devices: int = 2) -> tuple[int, Exception | None]:
    try:
        return len(detect_xbox_controllers(max_devices=max_devices)), None
    except Exception as exc:
        return 0, exc


def prepare_shortcut_runtime_environment(payload: ShortcutLaunchPayload) -> None:
    if "azahar" not in payload.emulator:
        return
    target_exe = unquote_executable(payload.target_exe)
    candidate = Path(target_exe)
    if target_exe and _AZAHAR_WINDOWS_SDL_DIR_ENV not in os.environ and candidate.exists():
        os.environ[_AZAHAR_WINDOWS_SDL_DIR_ENV] = str(candidate.parent)


def apply_shortcut_controller_configuration(
    *,
    payload: ShortcutLaunchPayload,
    config: GamehubConfig,
) -> str | None:
    if not config.controllers.launch_autoconfig:
        return None

    detected_controller_count, detect_error = _detect_controller_count_once(max_devices=2)
    controller_count = detected_controller_count
    if detect_error is not None:
        warn_shortcut_runtime(
            "controller detection failed "
            f"(emulator={payload.emulator}, error={detect_error}); using keyboard/mouse fallback profile selection"
        )
    if sys.platform.startswith("linux") and is_steam_deck_linux() and controller_count == 0:
        controller_count = 1
        warn_shortcut_runtime(
            "Steam Deck controller detection returned 0 controllers; forcing xbox_1p profile fallback"
        )

    selected_profile = profile_name_for_controller_count(controller_count)
    try:
        selected_profile = apply_controller_profile(
            config,
            emulator_name=payload.emulator,
            controller_count=controller_count,
        )
    except Exception as exc:
        warn_shortcut_runtime(
            "controller autoconfig failed "
            f"(emulator={payload.emulator}, profile={PROFILE_KBM}, error={exc}); using keyboard/mouse fallback"
        )
        try:
            selected_profile = apply_named_controller_profile(
                config,
                emulator_name=payload.emulator,
                profile_name=PROFILE_KBM,
            )
        except Exception as fallback_exc:
            warn_shortcut_runtime(
                "keyboard/mouse fallback profile application failed "
                f"(emulator={payload.emulator}, error={fallback_exc})"
            )
    return selected_profile


def run_target_with_optional_exit_hook(payload: ShortcutLaunchPayload) -> int:
    return _run_target_with_optional_exit_hook(payload)
