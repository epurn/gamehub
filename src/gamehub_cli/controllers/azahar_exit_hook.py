from __future__ import annotations

import argparse
import ctypes
import math
import os
import plistlib
import re
import signal
import struct
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from ..common.platform_paths import macos_azahar_qt_config_candidates
from .detection import XboxController, detect_xbox_controllers, is_steam_deck_linux
from .sdl_guid import _lookup_macos_embedded_sdl_mapping_for_port, _SDLControllerMapping

_JS_EVENT_FORMAT = "IhBB"
_JS_EVENT_SIZE = struct.calcsize(_JS_EVENT_FORMAT)
_JS_EVENT_TYPE_BUTTON = 0x01
_JS_EVENT_TYPE_INIT = 0x80
_INPUT_EVENT_FORMAT = "llHHI"
_INPUT_EVENT_SIZE = struct.calcsize(_INPUT_EVENT_FORMAT)
_EV_KEY = 0x01
_BTN_SELECT = 0x13A
_BTN_START = 0x13B
_BTN_TR2 = 0x139
_BUTTON_PATTERN_TEMPLATE = r'^profiles\\\d+\\button_{name}="button:(\d+),'
_PORT_PATTERN_TEMPLATE = r'^profiles\\\d+\\button_{name}="[^"]*port:(\d+)'
_SELECT_BUTTON_ENV = "GAMEHUB_AZAHAR_EXIT_BUTTON_SELECT"
_START_BUTTON_ENV = "GAMEHUB_AZAHAR_EXIT_BUTTON_START"
_JS_DEVICE_ENV = "GAMEHUB_AZAHAR_EXIT_JS_DEVICE"
_AZAHAR_MOUSE_BRIDGE_ENV = "GAMEHUB_AZAHAR_MOUSE_BRIDGE"
_AZAHAR_MOUSE_BRIDGE_EVENT_DEVICE_ENV = "GAMEHUB_AZAHAR_MOUSE_BRIDGE_EVENT_DEVICE"
_PROC_INPUT_DEVICES_PATH = Path("/proc/bus/input/devices")
_INPUT_DEVICE_NAME_RE = re.compile(r'^N:\s+Name="(?P<name>.*)"$')
_INPUT_DEVICE_HANDLERS_RE = re.compile(r"^H:\s+Handlers=(?P<handlers>.+)$")
_INPUT_EVENT_HANDLER_RE = re.compile(r"\bevent(?P<index>\d+)\b")
_INPUT_JS_HANDLER_RE = re.compile(r"\bjs(?P<index>\d+)\b")
_INPUT_JS_BASENAME_RE = re.compile(r"^js(?P<index>\d+)$")
_MACOS_HIDUTIL_EXECUTABLE = "/usr/bin/hidutil"
_MACOS_OSASCRIPT_EXECUTABLE = "/usr/bin/osascript"
_MACOS_OBJC_LIBRARY = "/usr/lib/libobjc.A.dylib"
_MACOS_FOUNDATION_FRAMEWORK = "/System/Library/Frameworks/Foundation.framework/Foundation"
_MACOS_GAMECONTROLLER_FRAMEWORK = "/System/Library/Frameworks/GameController.framework/GameController"
_MACOS_COREGRAPHICS_FRAMEWORK = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
_MACOS_COREFOUNDATION_FRAMEWORK = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
_MACOS_HIDUTIL_POLL_SECONDS = 0.1
_MACOS_XBOX_PLUGIN_NAME = "XboxOneHIDServicePlugin"
_MACOS_EVENT_TYPE_KEYBOARD = 3
_MACOS_CONSUMER_USAGE_PAGE = 12
_MACOS_XBOX_START_USAGE = 516
_MACOS_XBOX_SELECT_USAGE = 521
_MACOS_EVENT_TAP_HID = 0
_MACOS_EVENT_LEFT_MOUSE_DOWN = 1
_MACOS_EVENT_LEFT_MOUSE_UP = 2
_MACOS_MOUSE_BUTTON_LEFT = 0
_MACOS_GC_FIELD_TO_SELECTOR = {
    "a": "buttonA",
    "b": "buttonB",
    "x": "buttonX",
    "y": "buttonY",
    "back": "buttonOptions",
    "start": "buttonMenu",
    "guide": "buttonHome",
    "leftshoulder": "leftShoulder",
    "rightshoulder": "rightShoulder",
    "leftstick": "leftThumbstickButton",
    "rightstick": "rightThumbstickButton",
}
_MACOS_SDL_BUTTON_FIELD_RE = re.compile(r"^b(?P<button>\d+)$")
_AZAHAR_MOUSE_BRIDGE_POLL_SECONDS = 0.02
_AZAHAR_MOUSE_BRIDGE_AXIS_DEADZONE = 0.2
_AZAHAR_MOUSE_BRIDGE_MAX_MOUSE_DELTA = 24
_AZAHAR_MOUSE_BRIDGE_TRIGGER_THRESHOLD = 0.5
_AZAHAR_MOUSE_BRIDGE_MAX_DEVICES = 4
_XINPUT_DLLS = ("xinput1_4", "xinput9_1_0", "xinput1_3")
_WIN_MOUSEEVENTF_MOVE = 0x0001
_WIN_MOUSEEVENTF_LEFTDOWN = 0x0002
_WIN_MOUSEEVENTF_LEFTUP = 0x0004


class AzaharMouseBridgeUnavailable(RuntimeError):
    """Raised when the Azahar mouse bridge backend cannot be started."""


@dataclass(frozen=True)
class _AzaharMouseBridgeState:
    stick_x: float
    stick_y: float
    primary_down: bool


@dataclass(frozen=True)
class _LinuxInputDeviceRecord:
    name: str
    js_indices: tuple[int, ...]
    event_indices: tuple[int, ...]


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _AzaharMouseEmitter(Protocol):
    def move_relative(self, dx: int, dy: int) -> None: ...

    def press_left(self) -> None: ...

    def release_left(self) -> None: ...

    def close(self) -> None: ...


class _WindowsMouseEmitter:
    def __init__(self) -> None:
        windll = getattr(ctypes, "windll", None)
        user32 = getattr(windll, "user32", None) if windll is not None else None
        mouse_event = getattr(user32, "mouse_event", None)
        if mouse_event is None:
            raise AzaharMouseBridgeUnavailable("Windows mouse bridge backend unavailable")
        self._mouse_event = mouse_event

    def move_relative(self, dx: int, dy: int) -> None:
        if dx == 0 and dy == 0:
            return
        self._mouse_event(_WIN_MOUSEEVENTF_MOVE, dx, dy, 0, 0)

    def press_left(self) -> None:
        self._mouse_event(_WIN_MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)

    def release_left(self) -> None:
        self._mouse_event(_WIN_MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def close(self) -> None:
        return None


class _MacOSMouseEmitter:
    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise AzaharMouseBridgeUnavailable("macOS mouse bridge backend unavailable")
        try:
            self._coregraphics = ctypes.cdll.LoadLibrary(_MACOS_COREGRAPHICS_FRAMEWORK)
            self._corefoundation = ctypes.cdll.LoadLibrary(_MACOS_COREFOUNDATION_FRAMEWORK)
        except OSError as exc:
            raise AzaharMouseBridgeUnavailable("macOS mouse bridge backend unavailable") from exc
        self._configure_runtime()

    def _configure_runtime(self) -> None:
        self._coregraphics.CGEventCreate.argtypes = [ctypes.c_void_p]
        self._coregraphics.CGEventCreate.restype = ctypes.c_void_p
        self._coregraphics.CGEventGetLocation.argtypes = [ctypes.c_void_p]
        self._coregraphics.CGEventGetLocation.restype = _CGPoint
        self._coregraphics.CGWarpMouseCursorPosition.argtypes = [_CGPoint]
        self._coregraphics.CGWarpMouseCursorPosition.restype = ctypes.c_int
        self._coregraphics.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, _CGPoint, ctypes.c_uint]
        self._coregraphics.CGEventCreateMouseEvent.restype = ctypes.c_void_p
        self._coregraphics.CGEventPost.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        self._coregraphics.CGEventPost.restype = None
        self._corefoundation.CFRelease.argtypes = [ctypes.c_void_p]
        self._corefoundation.CFRelease.restype = None

    def _current_position(self) -> _CGPoint:
        event = self._coregraphics.CGEventCreate(None)
        if not event:
            return _CGPoint(0.0, 0.0)
        try:
            location = self._coregraphics.CGEventGetLocation(event)
            return _CGPoint(float(location.x), float(location.y))
        finally:
            self._corefoundation.CFRelease(event)

    def move_relative(self, dx: int, dy: int) -> None:
        if dx == 0 and dy == 0:
            return
        current = self._current_position()
        self._coregraphics.CGWarpMouseCursorPosition(_CGPoint(current.x + dx, current.y + dy))

    def _post_mouse_event(self, event_type: int) -> None:
        current = self._current_position()
        event = self._coregraphics.CGEventCreateMouseEvent(
            None,
            event_type,
            current,
            _MACOS_MOUSE_BUTTON_LEFT,
        )
        if not event:
            return
        try:
            self._coregraphics.CGEventPost(_MACOS_EVENT_TAP_HID, event)
        finally:
            self._corefoundation.CFRelease(event)

    def press_left(self) -> None:
        self._post_mouse_event(_MACOS_EVENT_LEFT_MOUSE_DOWN)

    def release_left(self) -> None:
        self._post_mouse_event(_MACOS_EVENT_LEFT_MOUSE_UP)

    def close(self) -> None:
        return None


class _LinuxMouseEmitter:
    def __init__(self, evdev_module: object) -> None:
        ecodes = getattr(evdev_module, "ecodes", None)
        uinput_type = getattr(evdev_module, "UInput", None)
        if ecodes is None or uinput_type is None:
            raise AzaharMouseBridgeUnavailable("evdev unavailable")
        capabilities = {
            ecodes.EV_REL: [ecodes.REL_X, ecodes.REL_Y],
            ecodes.EV_KEY: [ecodes.BTN_LEFT],
        }
        try:
            self._uinput = uinput_type(capabilities, name="GAMEHUB Azahar Mouse")
        except FileNotFoundError as exc:
            raise AzaharMouseBridgeUnavailable("/dev/uinput unavailable") from exc
        except PermissionError as exc:
            raise AzaharMouseBridgeUnavailable("permission denied opening /dev/uinput") from exc
        except OSError as exc:
            raise AzaharMouseBridgeUnavailable("virtual mouse creation failed") from exc
        self._ecodes = ecodes

    def move_relative(self, dx: int, dy: int) -> None:
        if dx == 0 and dy == 0:
            return
        self._uinput.write(self._ecodes.EV_REL, self._ecodes.REL_X, dx)
        self._uinput.write(self._ecodes.EV_REL, self._ecodes.REL_Y, dy)
        self._uinput.syn()

    def press_left(self) -> None:
        self._uinput.write(self._ecodes.EV_KEY, self._ecodes.BTN_LEFT, 1)
        self._uinput.syn()

    def release_left(self) -> None:
        self._uinput.write(self._ecodes.EV_KEY, self._ecodes.BTN_LEFT, 0)
        self._uinput.syn()

    def close(self) -> None:
        close = getattr(self._uinput, "close", None)
        if callable(close):
            close()


class _LinuxMouseBridgePoller:
    def __init__(self, device: object, *, evdev_module: object) -> None:
        ecodes = getattr(evdev_module, "ecodes", None)
        if ecodes is None:
            raise AzaharMouseBridgeUnavailable("evdev unavailable")
        self._device = device
        self._ecodes = ecodes
        set_blocking = getattr(device, "set_blocking", None)
        if callable(set_blocking):
            set_blocking(False)

        capabilities = getattr(device, "capabilities")(absinfo=True)
        abs_capabilities = _linux_abs_capability_map(capabilities.get(ecodes.EV_ABS, []))
        key_capabilities = _linux_key_capability_set(capabilities.get(ecodes.EV_KEY, []))
        self._stick_x_info = abs_capabilities.get(ecodes.ABS_RX)
        self._stick_y_info = abs_capabilities.get(ecodes.ABS_RY)
        if self._stick_x_info is None or self._stick_y_info is None:
            raise AzaharMouseBridgeUnavailable("missing right-stick axes")

        self._trigger_info = abs_capabilities.get(ecodes.ABS_RZ)
        self._digital_trigger_supported = ecodes.BTN_TR2 in key_capabilities
        if self._trigger_info is None and not self._digital_trigger_supported:
            raise AzaharMouseBridgeUnavailable("missing trigger input")

        self._stick_x_value = _linux_abs_default_value(self._stick_x_info)
        self._stick_y_value = _linux_abs_default_value(self._stick_y_info)
        self._trigger_value = _linux_abs_default_value(self._trigger_info) if self._trigger_info is not None else 0
        self._digital_trigger_down = False

    def __call__(self) -> _AzaharMouseBridgeState | None:
        read = getattr(self._device, "read", None)
        if read is None:
            return None
        try:
            events = list(read())
        except BlockingIOError:
            events = []
        except OSError:
            return None

        for event in events:
            event_type = getattr(event, "type", None)
            code = getattr(event, "code", None)
            value = getattr(event, "value", None)
            if not isinstance(event_type, int) or not isinstance(code, int):
                continue
            if event_type == self._ecodes.EV_ABS and isinstance(value, int):
                if code == self._ecodes.ABS_RX:
                    self._stick_x_value = value
                elif code == self._ecodes.ABS_RY:
                    self._stick_y_value = value
                elif self._trigger_info is not None and code == self._ecodes.ABS_RZ:
                    self._trigger_value = value
            elif (
                self._trigger_info is None
                and self._digital_trigger_supported
                and event_type == self._ecodes.EV_KEY
                and code == self._ecodes.BTN_TR2
                and isinstance(value, int)
            ):
                self._digital_trigger_down = value != 0

        primary_down = self._digital_trigger_down
        if self._trigger_info is not None:
            primary_down = (
                _normalize_linux_trigger(self._trigger_value, self._trigger_info)
                >= _AZAHAR_MOUSE_BRIDGE_TRIGGER_THRESHOLD
            )
        return _AzaharMouseBridgeState(
            stick_x=_normalize_linux_axis(self._stick_x_value, self._stick_x_info),
            stick_y=_normalize_linux_axis(self._stick_y_value, self._stick_y_info),
            primary_down=primary_down,
        )

    def close(self) -> None:
        close = getattr(self._device, "close", None)
        if callable(close):
            close()


def _azahar_qt_config_candidates() -> list[Path]:
    home = Path.home()
    if sys.platform == "darwin":
        return macos_azahar_qt_config_candidates()
    return [
        home / ".var" / "app" / "org.azahar_emu.Azahar" / "config" / "azahar-emu" / "qt-config.ini",
        home / ".var" / "app" / "org.azahar_emu.Azahar" / "config" / "azahar" / "qt-config.ini",
    ]


def _int_env_optional(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
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


def _azahar_mouse_bridge_disabled_reason() -> str | None:
    if not _env_enabled(_AZAHAR_MOUSE_BRIDGE_ENV, default=True):
        return f"disabled by {_AZAHAR_MOUSE_BRIDGE_ENV}"
    if sys.platform.startswith("linux") and is_steam_deck_linux():
        return "Linux Azahar mouse bridge is disabled on Steam Deck hosts"
    return None


def _linux_input_device_records(raw: str) -> list[_LinuxInputDeviceRecord]:
    records: list[_LinuxInputDeviceRecord] = []
    current_name: str | None = None
    current_handlers: str | None = None

    def _flush_entry() -> None:
        if not current_name or not current_handlers:
            return
        js_indices = tuple(
            sorted(int(match.group("index")) for match in _INPUT_JS_HANDLER_RE.finditer(current_handlers))
        )
        event_indices = tuple(
            sorted(int(match.group("index")) for match in _INPUT_EVENT_HANDLER_RE.finditer(current_handlers))
        )
        records.append(
            _LinuxInputDeviceRecord(
                name=current_name,
                js_indices=js_indices,
                event_indices=event_indices,
            )
        )

    for line in [*raw.splitlines(), ""]:
        stripped = line.strip()
        if not stripped:
            _flush_entry()
            current_name = None
            current_handlers = None
            continue
        name_match = _INPUT_DEVICE_NAME_RE.match(stripped)
        if name_match is not None:
            current_name = name_match.group("name")
            continue
        handlers_match = _INPUT_DEVICE_HANDLERS_RE.match(stripped)
        if handlers_match is not None:
            current_handlers = handlers_match.group("handlers")
    return records


def _read_linux_input_device_records() -> list[_LinuxInputDeviceRecord]:
    try:
        raw = _PROC_INPUT_DEVICES_PATH.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        raise AzaharMouseBridgeUnavailable("unable to inspect /proc/bus/input/devices") from exc
    return _linux_input_device_records(raw)


def _js_device_index(path_value: str) -> int | None:
    basename = Path(path_value).name
    match = _INPUT_JS_BASENAME_RE.match(basename)
    if match is None:
        return None
    return int(match.group("index"))


def _linux_record_for_controller(
    records: list[_LinuxInputDeviceRecord],
    *,
    controller: XboxController,
    js_device_hint: str | None,
) -> _LinuxInputDeviceRecord | None:
    normalized_name = controller.name.casefold()
    if js_device_hint:
        js_index = _js_device_index(js_device_hint)
        if js_index is not None:
            hint_matches = [record for record in records if js_index in record.js_indices]
            exact_hint = [record for record in hint_matches if record.name.casefold() == normalized_name]
            if exact_hint:
                return exact_hint[0]
            if hint_matches:
                return hint_matches[0]
    exact_matches = [
        record
        for record in records
        if controller.slot in record.js_indices and record.name.casefold() == normalized_name
    ]
    if exact_matches:
        return exact_matches[0]
    return None


def _linux_event_device_path_for_controller(controller: XboxController) -> str:
    override_path = os.environ.get(_AZAHAR_MOUSE_BRIDGE_EVENT_DEVICE_ENV)
    if override_path:
        return override_path
    records = _read_linux_input_device_records()
    record = _linux_record_for_controller(records, controller=controller, js_device_hint=os.environ.get(_JS_DEVICE_ENV))
    if record is None or not record.event_indices:
        raise AzaharMouseBridgeUnavailable("no matching event device")
    return str(Path("/dev/input") / f"event{record.event_indices[0]}")


def _linux_abs_capability_map(entries: object) -> dict[int, object]:
    if not isinstance(entries, list):
        return {}
    capabilities: dict[int, object] = {}
    for entry in entries:
        if isinstance(entry, tuple) and len(entry) >= 2 and isinstance(entry[0], int):
            capabilities[entry[0]] = entry[1]
        elif isinstance(entry, int):
            capabilities[entry] = None
    return capabilities


def _linux_key_capability_set(entries: object) -> set[int]:
    if not isinstance(entries, list):
        return set()
    keys: set[int] = set()
    for entry in entries:
        if isinstance(entry, tuple) and entry and isinstance(entry[0], int):
            keys.add(entry[0])
        elif isinstance(entry, int):
            keys.add(entry)
    return keys


def _linux_abs_bounds(absinfo: object) -> tuple[int, int] | None:
    if absinfo is None:
        return None
    minimum = getattr(absinfo, "min", None)
    maximum = getattr(absinfo, "max", None)
    if isinstance(minimum, int) and isinstance(maximum, int) and maximum > minimum:
        return minimum, maximum
    if (
        isinstance(absinfo, tuple)
        and len(absinfo) >= 3
        and isinstance(absinfo[1], int)
        and isinstance(absinfo[2], int)
        and absinfo[2] > absinfo[1]
    ):
        return absinfo[1], absinfo[2]
    return None


def _linux_abs_default_value(absinfo: object) -> int:
    value = getattr(absinfo, "value", None)
    if isinstance(value, int):
        return value
    if isinstance(absinfo, tuple) and absinfo and isinstance(absinfo[0], int):
        return absinfo[0]
    bounds = _linux_abs_bounds(absinfo)
    if bounds is None:
        return 0
    minimum, maximum = bounds
    return int(round((minimum + maximum) / 2.0))


def _normalize_linux_axis(value: int, absinfo: object) -> float:
    bounds = _linux_abs_bounds(absinfo)
    if bounds is None:
        return 0.0
    minimum, maximum = bounds
    center = (minimum + maximum) / 2.0
    half_range = max((maximum - minimum) / 2.0, 1.0)
    normalized = (value - center) / half_range
    return max(-1.0, min(1.0, normalized))


def _normalize_linux_trigger(value: int, absinfo: object) -> float:
    bounds = _linux_abs_bounds(absinfo)
    if bounds is None:
        return 0.0
    minimum, maximum = bounds
    normalized = (value - minimum) / max(maximum - minimum, 1)
    return max(0.0, min(1.0, normalized))


def _load_linux_evdev() -> object:
    try:
        import evdev
    except ImportError as exc:
        raise AzaharMouseBridgeUnavailable("evdev unavailable") from exc
    return evdev


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


def _warn_azahar_runtime(message: str) -> None:
    rendered = f"Warning: {message}"
    try:
        sys.stderr.write(f"{rendered}\n")
        sys.stderr.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass


def _load_windows_xinput() -> ctypes.CDLL | None:
    if not sys.platform.startswith("win"):
        return None
    win_dll_loader = getattr(ctypes, "WinDLL", None)
    if win_dll_loader is None:
        return None
    for dll_name in _XINPUT_DLLS:
        try:
            lib = win_dll_loader(dll_name)
        except OSError:
            continue
        try:
            lib.XInputGetState.argtypes = [ctypes.c_uint, ctypes.POINTER(_XInputState)]
            lib.XInputGetState.restype = ctypes.c_uint
        except AttributeError:
            continue
        return lib
    return None


def _normalize_signed_axis(value: int) -> float:
    if value >= 0:
        normalized = value / 32767.0
    else:
        normalized = value / 32768.0
    return max(-1.0, min(1.0, normalized))


def _mouse_bridge_axis_delta(value: float) -> int:
    clamped = max(-1.0, min(1.0, float(value)))
    magnitude = abs(clamped)
    if magnitude <= _AZAHAR_MOUSE_BRIDGE_AXIS_DEADZONE:
        return 0
    scaled = (magnitude - _AZAHAR_MOUSE_BRIDGE_AXIS_DEADZONE) / (1.0 - _AZAHAR_MOUSE_BRIDGE_AXIS_DEADZONE)
    if scaled <= 0.0:
        return 0
    delta = max(1, int(round(scaled * _AZAHAR_MOUSE_BRIDGE_MAX_MOUSE_DELTA)))
    return int(math.copysign(delta, clamped))


def _apply_azahar_mouse_bridge_state(
    state: _AzaharMouseBridgeState,
    *,
    primary_down: bool,
    emitter: _AzaharMouseEmitter,
) -> bool:
    dx = _mouse_bridge_axis_delta(state.stick_x)
    dy = -_mouse_bridge_axis_delta(state.stick_y)
    if dx or dy:
        emitter.move_relative(dx, dy)
    if state.primary_down and not primary_down:
        emitter.press_left()
        return True
    if primary_down and not state.primary_down:
        emitter.release_left()
        return False
    return primary_down


def _poll_windows_mouse_bridge_state(
    lib: ctypes.CDLL,
    *,
    controller_slot: int,
) -> _AzaharMouseBridgeState | None:
    state = _XInputState()
    if lib.XInputGetState(controller_slot, ctypes.byref(state)) != 0:
        return None
    gamepad = state.Gamepad
    trigger_value = float(int(gamepad.bRightTrigger)) / 255.0
    return _AzaharMouseBridgeState(
        stick_x=_normalize_signed_axis(int(gamepad.sThumbRX)),
        stick_y=_normalize_signed_axis(int(gamepad.sThumbRY)),
        primary_down=trigger_value >= _AZAHAR_MOUSE_BRIDGE_TRIGGER_THRESHOLD,
    )


def _discover_js_devices() -> list[str]:
    env_device = os.environ.get(_JS_DEVICE_ENV)
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


def _discover_event_devices() -> list[str]:
    dev_input = Path("/dev/input")
    if not dev_input.exists():
        return []
    devices: list[str] = []
    for candidate in sorted(dev_input.glob("event*")):
        if candidate.is_char_device() or candidate.exists():
            devices.append(str(candidate))
    return devices


def _is_flatpak_app_running(app_id: str) -> bool:
    try:
        completed = subprocess.run(
            ["flatpak", "ps", "--columns=application"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    if completed.returncode != 0:
        return False
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    for line in lines:
        if line.casefold() in {"application", "app"}:
            continue
        if line == app_id:
            return True
    return False


def _session_active(process: subprocess.Popen[bytes], app_id: str) -> bool:
    if process.poll() is None:
        return True
    return _is_flatpak_app_running(app_id)


def _extract_button_from_qt_config(text: str, *, name: str) -> int | None:
    match = re.search(_BUTTON_PATTERN_TEMPLATE.format(name=name), text, flags=re.MULTILINE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _extract_port_from_qt_config(text: str, *, name: str) -> int | None:
    match = re.search(_PORT_PATTERN_TEMPLATE.format(name=name), text, flags=re.MULTILINE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _resolve_button_pair_from_config() -> tuple[int | None, int | None]:
    for candidate in _azahar_qt_config_candidates():
        if not candidate.exists():
            continue
        try:
            contents = candidate.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        select_button = _extract_button_from_qt_config(contents, name="select")
        start_button = _extract_button_from_qt_config(contents, name="start")
        return select_button, start_button
    return None, None


def _resolve_port_from_config() -> int:
    for candidate in _azahar_qt_config_candidates():
        if not candidate.exists():
            continue
        try:
            contents = candidate.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        select_port = _extract_port_from_qt_config(contents, name="select")
        if select_port is not None:
            return select_port
        start_port = _extract_port_from_qt_config(contents, name="start")
        if start_port is not None:
            return start_port
    return 0


def _resolve_select_and_start_buttons() -> tuple[int, int]:
    env_select = _int_env_optional(_SELECT_BUTTON_ENV)
    env_start = _int_env_optional(_START_BUTTON_ENV)
    if env_select is not None and env_start is not None:
        return env_select, env_start
    cfg_select, cfg_start = _resolve_button_pair_from_config()
    select_button = env_select if env_select is not None else (cfg_select if cfg_select is not None else 4)
    start_button = env_start if env_start is not None else (cfg_start if cfg_start is not None else 6)
    return select_button, start_button


def _resolve_macos_button_selectors(
    *,
    port: int,
    select_button: int,
    start_button: int,
) -> tuple[str, str] | None:
    mapping: _SDLControllerMapping | None = _lookup_macos_embedded_sdl_mapping_for_port(port=port)
    if mapping is None:
        return None
    reverse_fields: dict[int, str] = {}
    for field_name, token in mapping.fields.items():
        match = _MACOS_SDL_BUTTON_FIELD_RE.match(token.strip().casefold())
        if match is None:
            continue
        reverse_fields[int(match.group("button"))] = field_name
    select_field = reverse_fields.get(select_button)
    start_field = reverse_fields.get(start_button)
    if select_field is None or start_field is None:
        return None
    select_selector = _MACOS_GC_FIELD_TO_SELECTOR.get(select_field)
    start_selector = _MACOS_GC_FIELD_TO_SELECTOR.get(start_field)
    if select_selector is None or start_selector is None:
        return None
    return select_selector, start_selector


def _load_macos_gamecontroller_runtime() -> ctypes.CDLL | None:
    if sys.platform != "darwin":
        return None
    try:
        ctypes.cdll.LoadLibrary(_MACOS_FOUNDATION_FRAMEWORK)
        ctypes.cdll.LoadLibrary(_MACOS_GAMECONTROLLER_FRAMEWORK)
        objc = ctypes.cdll.LoadLibrary(_MACOS_OBJC_LIBRARY)
    except OSError:
        return None
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    return objc


def _objc_selector(objc: ctypes.CDLL, name: str) -> ctypes.c_void_p:
    return ctypes.c_void_p(objc.sel_registerName(name.encode("utf-8")))


def _objc_class(objc: ctypes.CDLL, name: str) -> ctypes.c_void_p:
    return ctypes.c_void_p(objc.objc_getClass(name.encode("utf-8")))


def _objc_msg_send(
    objc: ctypes.CDLL,
    receiver: ctypes.c_void_p,
    selector: str,
    *,
    restype: Any = ctypes.c_void_p,
    argtypes: tuple[Any, ...] = (),
    args: tuple[Any, ...] = (),
) -> Any:
    objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, *argtypes]
    objc.objc_msgSend.restype = restype
    return objc.objc_msgSend(receiver, _objc_selector(objc, selector), *args)


def _macos_gc_button_pressed(
    objc: ctypes.CDLL,
    gamepad: ctypes.c_void_p,
    selector: str,
) -> bool:
    if not gamepad:
        return False
    responds = _objc_msg_send(
        objc,
        gamepad,
        "respondsToSelector:",
        restype=ctypes.c_bool,
        argtypes=(ctypes.c_void_p,),
        args=(_objc_selector(objc, selector),),
    )
    if not responds:
        return False
    button = _objc_msg_send(objc, gamepad, selector)
    if not button:
        return False
    return bool(_objc_msg_send(objc, button, "isPressed", restype=ctypes.c_bool))


def _macos_gc_float_value(
    objc: ctypes.CDLL,
    receiver: ctypes.c_void_p,
    selector: str,
) -> float | None:
    if not receiver:
        return None
    responds = _objc_msg_send(
        objc,
        receiver,
        "respondsToSelector:",
        restype=ctypes.c_bool,
        argtypes=(ctypes.c_void_p,),
        args=(_objc_selector(objc, selector),),
    )
    if not responds:
        return None
    return float(_objc_msg_send(objc, receiver, selector, restype=ctypes.c_float))


def _poll_macos_mouse_bridge_state(*, controller_slot: int) -> _AzaharMouseBridgeState | None:
    objc = _load_macos_gamecontroller_runtime()
    if objc is None:
        return None
    pool_class = _objc_class(objc, "NSAutoreleasePool")
    pool = _objc_msg_send(objc, pool_class, "new") if pool_class else None
    try:
        controller_class = _objc_class(objc, "GCController")
        if not controller_class:
            return None
        _objc_msg_send(
            objc,
            controller_class,
            "setShouldMonitorBackgroundEvents:",
            restype=None,
            argtypes=(ctypes.c_bool,),
            args=(True,),
        )
        controllers = _objc_msg_send(objc, controller_class, "controllers")
        if not controllers:
            return None
        count = int(_objc_msg_send(objc, controllers, "count", restype=ctypes.c_ulong))
        if controller_slot < 0 or controller_slot >= count:
            return None
        controller = _objc_msg_send(
            objc,
            controllers,
            "objectAtIndex:",
            argtypes=(ctypes.c_ulong,),
            args=(controller_slot,),
        )
        if not controller:
            return None
        gamepad = _objc_msg_send(objc, controller, "extendedGamepad")
        if not gamepad:
            return None
        right_thumbstick = _objc_msg_send(objc, gamepad, "rightThumbstick")
        if not right_thumbstick:
            return None
        x_axis = _objc_msg_send(objc, right_thumbstick, "xAxis")
        y_axis = _objc_msg_send(objc, right_thumbstick, "yAxis")
        right_trigger = _objc_msg_send(objc, gamepad, "rightTrigger")
        stick_x = _macos_gc_float_value(objc, x_axis, "value") or 0.0
        stick_y = _macos_gc_float_value(objc, y_axis, "value") or 0.0
        trigger_value = _macos_gc_float_value(objc, right_trigger, "value") or 0.0
        return _AzaharMouseBridgeState(
            stick_x=stick_x,
            stick_y=stick_y,
            primary_down=trigger_value >= _AZAHAR_MOUSE_BRIDGE_TRIGGER_THRESHOLD,
        )
    finally:
        if pool:
            _objc_msg_send(objc, pool, "drain", restype=None)


def _macos_controller_combo_pressed(
    *,
    controller_port: int,
    select_selector: str,
    start_selector: str,
) -> bool | None:
    objc = _load_macos_gamecontroller_runtime()
    if objc is None:
        return None
    pool_class = _objc_class(objc, "NSAutoreleasePool")
    pool = _objc_msg_send(objc, pool_class, "new") if pool_class else None
    try:
        controller_class = _objc_class(objc, "GCController")
        if not controller_class:
            return None
        _objc_msg_send(
            objc,
            controller_class,
            "setShouldMonitorBackgroundEvents:",
            restype=None,
            argtypes=(ctypes.c_bool,),
            args=(True,),
        )
        controllers = _objc_msg_send(objc, controller_class, "controllers")
        if not controllers:
            return None
        count = int(_objc_msg_send(objc, controllers, "count", restype=ctypes.c_ulong))
        if controller_port < 0 or controller_port >= count:
            return None
        controller = _objc_msg_send(
            objc,
            controllers,
            "objectAtIndex:",
            argtypes=(ctypes.c_ulong,),
            args=(controller_port,),
        )
        if not controller:
            return None
        gamepad = _objc_msg_send(objc, controller, "extendedGamepad")
        if not gamepad:
            return None
        return _macos_gc_button_pressed(objc, gamepad, select_selector) and _macos_gc_button_pressed(
            objc,
            gamepad,
            start_selector,
        )
    finally:
        if pool:
            _objc_msg_send(objc, pool, "drain", restype=None)


def _capture_macos_xbox_event_log() -> tuple[int | None, list[dict[str, object]]] | None:
    if sys.platform != "darwin":
        return None
    try:
        completed = subprocess.run(
            [_MACOS_HIDUTIL_EXECUTABLE, "dump", "services", "-f", "xml"],
            check=False,
            capture_output=True,
        )
    except OSError:
        return None
    if completed.returncode != 0 or not completed.stdout:
        return None
    try:
        payload = plistlib.loads(completed.stdout)
    except (plistlib.InvalidFileException, TypeError, ValueError):
        return None
    records = payload.get("ServiceRecords")
    if not isinstance(records, list):
        return None
    for record in records:
        if not isinstance(record, dict):
            continue
        plugin_debug = record.get("ServicePluginDebug")
        if not isinstance(plugin_debug, dict):
            continue
        if plugin_debug.get("PluginName") != _MACOS_XBOX_PLUGIN_NAME:
            continue
        if record.get("PrimaryUsagePage") != 1 or record.get("PrimaryUsage") != 5:
            continue
        registry_id = record.get("IORegistryEntryID")
        event_log = record.get("EventLog")
        normalized_log = (
            [entry for entry in event_log if isinstance(entry, dict)] if isinstance(event_log, list) else []
        )
        return (int(registry_id) if isinstance(registry_id, int) else None, normalized_log)
    return None


def _macos_consumer_usage_event_key(event: dict[str, object]) -> tuple[str | None, int, int, int, int] | None:
    event_type = event.get("EventType")
    usage_page = event.get("UsagePage")
    usage = event.get("Usage")
    down = event.get("Down")
    event_time = event.get("EventTime")
    if not isinstance(event_type, int) or not isinstance(usage_page, int) or not isinstance(usage, int):
        return None
    if event_type != _MACOS_EVENT_TYPE_KEYBOARD or usage_page != _MACOS_CONSUMER_USAGE_PAGE:
        return None
    if usage not in {_MACOS_XBOX_SELECT_USAGE, _MACOS_XBOX_START_USAGE}:
        return None
    if not isinstance(down, (int, bool)):
        return None
    if event_time is not None and not isinstance(event_time, str):
        event_time = str(event_time)
    return (event_time, event_type, usage_page, usage, int(bool(down)))


def _macos_pressed_consumer_usages_from_event_log(event_log: list[dict[str, object]]) -> set[int]:
    pressed: set[int] = set()
    for event in event_log:
        key = _macos_consumer_usage_event_key(event)
        if key is None:
            continue
        _event_time, _event_type, _usage_page, usage, down = key
        if down:
            pressed.add(usage)
        else:
            pressed.discard(usage)
    return pressed


def _monitor_macos_combo_and_terminate(
    process: subprocess.Popen[bytes],
    *,
    select_button: int,
    start_button: int,
    controller_port: int,
    bundle_id: str | None,
    process_name: str,
    prelaunch_pids: set[int],
) -> None:
    button_selectors = _resolve_macos_button_selectors(
        port=controller_port,
        select_button=select_button,
        start_button=start_button,
    )
    allow_hidutil_fallback = button_selectors is None
    active_registry_id: int | None = None
    seen_event_keys: set[tuple[str | None, int, int, int, int]] = set()
    pressed_usages: set[int] = set()
    while process.poll() is None:
        combo_pressed = False
        if button_selectors is not None:
            select_selector, start_selector = button_selectors
            combo_state = _macos_controller_combo_pressed(
                controller_port=controller_port,
                select_selector=select_selector,
                start_selector=start_selector,
            )
            if combo_state is None:
                allow_hidutil_fallback = True
            else:
                combo_pressed = combo_state
        if not combo_pressed and allow_hidutil_fallback:
            snapshot = _capture_macos_xbox_event_log()
            if snapshot is not None:
                registry_id, event_log = snapshot
                if registry_id != active_registry_id:
                    active_registry_id = registry_id
                    seen_event_keys.clear()
                    pressed_usages = _macos_pressed_consumer_usages_from_event_log(event_log)
                for event in event_log:
                    key = _macos_consumer_usage_event_key(event)
                    if key is None or key in seen_event_keys:
                        continue
                    seen_event_keys.add(key)
                    _event_time, _event_type, _usage_page, usage, down = key
                    if down:
                        pressed_usages.add(usage)
                    else:
                        pressed_usages.discard(usage)
            combo_pressed = {_MACOS_XBOX_SELECT_USAGE, _MACOS_XBOX_START_USAGE}.issubset(pressed_usages)
        if combo_pressed:
            _request_macos_application_quit(bundle_id=bundle_id)
            deadline = time.monotonic() + 2.0
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            if process.poll() is None:
                _terminate_named_processes(process_name=process_name, prelaunch_pids=prelaunch_pids, sig=signal.SIGTERM)
                deadline = time.monotonic() + 2.0
                while process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.05)
            if process.poll() is None:
                _terminate_named_processes(process_name=process_name, prelaunch_pids=prelaunch_pids, sig=signal.SIGKILL)
            return
        time.sleep(_MACOS_HIDUTIL_POLL_SECONDS)


def _request_macos_application_quit(*, bundle_id: str | None) -> None:
    if sys.platform != "darwin" or not bundle_id:
        return
    try:
        subprocess.run(
            [_MACOS_OSASCRIPT_EXECUTABLE, "-e", f'tell application id "{bundle_id}" to quit'],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return


def _discover_process_ids_by_name(process_name: str) -> set[int]:
    if not process_name:
        return set()
    try:
        completed = subprocess.run(
            ["pgrep", "-x", process_name],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return set()
    if completed.returncode not in {0, 1}:
        return set()
    pids: set[int] = set()
    for line in completed.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            pids.add(int(stripped))
        except ValueError:
            continue
    return pids


def _terminate_named_processes(*, process_name: str, prelaunch_pids: set[int], sig: int) -> None:
    current_pids = _discover_process_ids_by_name(process_name)
    target_pids = current_pids - prelaunch_pids
    if not target_pids:
        return
    for pid in target_pids:
        try:
            os.kill(pid, sig)
        except OSError:
            continue


def _resolve_macos_bundle_identifier(app_bundle: str) -> str | None:
    if sys.platform != "darwin":
        return None
    bundle_path = Path(app_bundle.strip().strip('"'))
    if bundle_path.suffix.casefold() != ".app":
        return None
    info_plist = bundle_path / "Contents" / "Info.plist"
    if not info_plist.is_file():
        return None
    try:
        with info_plist.open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None
    value = info.get("CFBundleIdentifier")
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _handle_js_event(
    pressed_buttons: set[int],
    event_type: int,
    event_value: int,
    button_index: int,
    *,
    select_button: int,
    start_button: int,
) -> bool:
    clean_type = event_type & ~_JS_EVENT_TYPE_INIT
    if clean_type != _JS_EVENT_TYPE_BUTTON:
        return False
    if event_value:
        pressed_buttons.add(button_index)
    else:
        pressed_buttons.discard(button_index)
    return select_button in pressed_buttons and start_button in pressed_buttons


def _handle_ev_key_event(
    pressed_codes: set[int],
    event_type: int,
    code: int,
    value: int,
) -> bool:
    if event_type != _EV_KEY:
        return False
    if code not in {_BTN_SELECT, _BTN_START}:
        return False
    if value:
        pressed_codes.add(code)
    else:
        pressed_codes.discard(code)
    return {_BTN_SELECT, _BTN_START}.issubset(pressed_codes)


def _monitor_combo_and_terminate(
    process: subprocess.Popen[bytes],
    *,
    select_button: int,
    start_button: int,
    js_devices: list[str],
    app_id: str,
) -> None:
    trigger_event = threading.Event()

    def _watch(device_path: str) -> None:
        try:
            handle = open(device_path, "rb", buffering=0)
        except OSError:
            return
        pressed_buttons: set[int] = set()
        with handle:
            while _session_active(process, app_id) and not trigger_event.is_set():
                data = handle.read(_JS_EVENT_SIZE)
                if len(data) != _JS_EVENT_SIZE:
                    break
                _time_ms, value, event_type, number = struct.unpack(_JS_EVENT_FORMAT, data)
                if _handle_js_event(
                    pressed_buttons,
                    event_type,
                    value,
                    number,
                    select_button=select_button,
                    start_button=start_button,
                ):
                    trigger_event.set()
                    break

    def _watch_evdev(device_path: str) -> None:
        try:
            handle = open(device_path, "rb", buffering=0)
        except OSError:
            return
        pressed_codes: set[int] = set()
        with handle:
            while _session_active(process, app_id) and not trigger_event.is_set():
                data = handle.read(_INPUT_EVENT_SIZE)
                if len(data) != _INPUT_EVENT_SIZE:
                    break
                _sec, _usec, event_type, code, value = struct.unpack(_INPUT_EVENT_FORMAT, data)
                if _handle_ev_key_event(pressed_codes, event_type, code, value):
                    trigger_event.set()
                    break

    threads: list[threading.Thread] = []
    for device_path in js_devices:
        watcher = threading.Thread(target=_watch, args=(device_path,), daemon=True)
        watcher.start()
        threads.append(watcher)
    for device_path in _discover_event_devices():
        watcher = threading.Thread(target=_watch_evdev, args=(device_path,), daemon=True)
        watcher.start()
        threads.append(watcher)
    if not threads:
        return

    while _session_active(process, app_id):
        if not trigger_event.wait(0.1):
            continue
        try:
            subprocess.run(["flatpak", "kill", app_id], check=False, capture_output=True, text=True)
        except OSError:
            pass
        deadline = time.monotonic() + 2.0
        while _session_active(process, app_id) and time.monotonic() < deadline:
            time.sleep(0.05)
        if process.poll() is None:
            process.terminate()
            deadline = time.monotonic() + 2.0
            while _session_active(process, app_id) and time.monotonic() < deadline:
                time.sleep(0.05)
        if process.poll() is None:
            process.kill()
        return


def _wait_for_session_exit(process: subprocess.Popen[bytes], app_id: str) -> int:
    while _session_active(process, app_id):
        time.sleep(0.1)
    code = process.poll()
    if code is None:
        return 0
    return code


def _create_azahar_mouse_bridge_poller(
    controller: XboxController,
) -> tuple[Callable[[], _AzaharMouseBridgeState | None], _AzaharMouseEmitter]:
    disabled_reason = _azahar_mouse_bridge_disabled_reason()
    if disabled_reason is not None:
        raise AzaharMouseBridgeUnavailable(disabled_reason)
    if sys.platform.startswith("win"):
        lib = _load_windows_xinput()
        if lib is None:
            raise AzaharMouseBridgeUnavailable("Windows XInput backend unavailable")
        return (
            lambda: _poll_windows_mouse_bridge_state(lib, controller_slot=controller.slot),
            _WindowsMouseEmitter(),
        )
    if sys.platform == "darwin":
        return (
            lambda: _poll_macos_mouse_bridge_state(controller_slot=controller.slot),
            _MacOSMouseEmitter(),
        )
    if sys.platform.startswith("linux"):
        evdev_module = _load_linux_evdev()
        event_device_path = _linux_event_device_path_for_controller(controller)
        input_device_type = getattr(evdev_module, "InputDevice", None)
        if input_device_type is None:
            raise AzaharMouseBridgeUnavailable("evdev unavailable")
        try:
            device = input_device_type(event_device_path)
        except FileNotFoundError as exc:
            raise AzaharMouseBridgeUnavailable("no matching event device") from exc
        except PermissionError as exc:
            raise AzaharMouseBridgeUnavailable(f"permission denied reading {event_device_path}") from exc
        except OSError as exc:
            raise AzaharMouseBridgeUnavailable(f"unable to read event device {event_device_path}") from exc
        try:
            poller = _LinuxMouseBridgePoller(device, evdev_module=evdev_module)
        except Exception:
            close = getattr(device, "close", None)
            if callable(close):
                close()
            raise
        try:
            emitter = _LinuxMouseEmitter(evdev_module)
        except Exception:
            poller.close()
            raise
        return poller, emitter
    raise AzaharMouseBridgeUnavailable(f"Azahar mouse bridge unsupported on platform {sys.platform}")


def _azahar_mouse_bridge_session_active(
    process: subprocess.Popen[bytes],
    *,
    app_id: str | None,
) -> bool:
    if app_id:
        return _session_active(process, app_id)
    return process.poll() is None


def _monitor_azahar_mouse_bridge(
    process: subprocess.Popen[bytes],
    *,
    poll_state: Callable[[], _AzaharMouseBridgeState | None],
    emitter: _AzaharMouseEmitter,
    app_id: str | None,
) -> None:
    primary_down = False
    try:
        while _azahar_mouse_bridge_session_active(process, app_id=app_id):
            state = poll_state()
            if state is not None:
                primary_down = _apply_azahar_mouse_bridge_state(state, primary_down=primary_down, emitter=emitter)
            time.sleep(_AZAHAR_MOUSE_BRIDGE_POLL_SECONDS)
    finally:
        if primary_down:
            try:
                emitter.release_left()
            except Exception:
                pass
        close_poller = getattr(poll_state, "close", None)
        if callable(close_poller):
            try:
                close_poller()
            except Exception:
                pass
        try:
            emitter.close()
        except Exception:
            pass


def _start_azahar_mouse_bridge(
    process: subprocess.Popen[bytes],
    *,
    controller: XboxController,
    app_id: str | None = None,
) -> threading.Thread:
    poll_state, emitter = _create_azahar_mouse_bridge_poller(controller)
    watcher = threading.Thread(
        target=_monitor_azahar_mouse_bridge,
        args=(process,),
        kwargs={"poll_state": poll_state, "emitter": emitter, "app_id": app_id},
        daemon=True,
    )
    watcher.start()
    return watcher


def _detect_azahar_mouse_bridge_controller() -> XboxController | None:
    if _azahar_mouse_bridge_disabled_reason() is not None:
        return None
    controllers = detect_xbox_controllers(max_devices=_AZAHAR_MOUSE_BRIDGE_MAX_DEVICES)
    if not controllers:
        return None
    return controllers[0]


def _launch_azahar_flatpak(*, rom: str, app_id: str) -> int:
    command = [
        "flatpak",
        "run",
        "--device=all",
        "--file-forwarding",
        app_id,
        "-f",
        "--",
        "@@",
        rom,
        "@@",
    ]
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL)
    try:
        controller = _detect_azahar_mouse_bridge_controller()
    except Exception as exc:
        _warn_azahar_runtime(
            f"Azahar mouse bridge controller detection failed (error={exc}); continuing without synthetic mouse input"
        )
        controller = None
    if controller is not None:
        try:
            _start_azahar_mouse_bridge(process, controller=controller, app_id=app_id)
        except AzaharMouseBridgeUnavailable as exc:
            _warn_azahar_runtime(
                f"Azahar mouse bridge unavailable (error={exc}); continuing without synthetic mouse input"
            )
        except Exception as exc:
            _warn_azahar_runtime(f"Azahar mouse bridge failed (error={exc}); continuing without synthetic mouse input")
    select_button, start_button = _resolve_select_and_start_buttons()
    js_devices = _discover_js_devices()
    watcher = threading.Thread(
        target=_monitor_combo_and_terminate,
        args=(process,),
        kwargs={
            "select_button": select_button,
            "start_button": start_button,
            "js_devices": js_devices,
            "app_id": app_id,
        },
        daemon=True,
    )
    watcher.start()
    return _wait_for_session_exit(process, app_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Launch Azahar and exit it when Select+Start is pressed on /dev/input/js*."
    )
    parser.add_argument("--rom", required=True, help="Absolute host path to ROM file.")
    parser.add_argument("--app-id", default="org.azahar_emu.Azahar", help="Flatpak app id for Azahar.")
    args = parser.parse_args(argv)
    return _launch_azahar_flatpak(rom=args.rom, app_id=args.app_id)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
