from __future__ import annotations

import ctypes
import math
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from .detection import XboxController, detect_xbox_controllers, is_steam_deck_linux
from .linux_input_devices import LinuxInputDeviceRecord, js_device_index, read_linux_input_device_records
from .macos_gamecontroller import (
    load_macos_gamecontroller_runtime,
    macos_gc_float_value,
    objc_class,
    objc_msg_send,
)
from .xinput import load_xinput, read_xinput_state

_AZAHAR_MOUSE_BRIDGE_ENV = "GAMEHUB_AZAHAR_MOUSE_BRIDGE"
_AZAHAR_MOUSE_BRIDGE_EVENT_DEVICE_ENV = "GAMEHUB_AZAHAR_MOUSE_BRIDGE_EVENT_DEVICE"
_JS_DEVICE_ENV = "GAMEHUB_AZAHAR_EXIT_JS_DEVICE"
_AZAHAR_MOUSE_BRIDGE_POLL_SECONDS = 0.02
_AZAHAR_MOUSE_BRIDGE_AXIS_DEADZONE = 0.2
_AZAHAR_MOUSE_BRIDGE_MAX_MOUSE_DELTA = 24
_AZAHAR_MOUSE_BRIDGE_TRIGGER_THRESHOLD = 0.5
_AZAHAR_MOUSE_BRIDGE_MAX_DEVICES = 4
_BTN_TR2 = 0x139
_WIN_MOUSEEVENTF_MOVE = 0x0001
_WIN_MOUSEEVENTF_LEFTDOWN = 0x0002
_WIN_MOUSEEVENTF_LEFTUP = 0x0004
_MACOS_COREGRAPHICS_FRAMEWORK = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
_MACOS_COREFOUNDATION_FRAMEWORK = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
_MACOS_EVENT_TAP_HID = 0
_MACOS_EVENT_LEFT_MOUSE_DOWN = 1
_MACOS_EVENT_LEFT_MOUSE_UP = 2
_MACOS_MOUSE_BUTTON_LEFT = 0


class AzaharMouseBridgeUnavailable(RuntimeError):
    """Raised when the Azahar mouse bridge backend cannot be started."""


@dataclass(frozen=True)
class _AzaharMouseBridgeState:
    stick_x: float
    stick_y: float
    primary_down: bool


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


def azahar_mouse_bridge_disabled_reason() -> str | None:
    if not _env_enabled(_AZAHAR_MOUSE_BRIDGE_ENV, default=True):
        return f"disabled by {_AZAHAR_MOUSE_BRIDGE_ENV}"
    if sys.platform.startswith("linux") and is_steam_deck_linux():
        return "Linux Azahar mouse bridge is disabled on Steam Deck hosts"
    return None


def _linux_record_for_controller(
    records: list[LinuxInputDeviceRecord],
    *,
    controller: XboxController,
    js_device_hint: str | None,
) -> LinuxInputDeviceRecord | None:
    normalized_name = controller.name.casefold()
    if js_device_hint:
        js_index = js_device_index(js_device_hint)
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
    try:
        records = read_linux_input_device_records()
    except OSError as exc:
        raise AzaharMouseBridgeUnavailable("unable to inspect /proc/bus/input/devices") from exc
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
    state = read_xinput_state(lib, slot=controller_slot)
    if state is None:
        return None
    trigger_value = float(state.right_trigger) / 255.0
    return _AzaharMouseBridgeState(
        stick_x=_normalize_signed_axis(state.right_thumb_x),
        stick_y=_normalize_signed_axis(state.right_thumb_y),
        primary_down=trigger_value >= _AZAHAR_MOUSE_BRIDGE_TRIGGER_THRESHOLD,
    )


def _poll_macos_mouse_bridge_state(*, controller_slot: int) -> _AzaharMouseBridgeState | None:
    objc = load_macos_gamecontroller_runtime()
    if objc is None:
        return None
    pool_class = objc_class(objc, "NSAutoreleasePool")
    pool = objc_msg_send(objc, pool_class, "new") if pool_class else None
    try:
        controller_class = objc_class(objc, "GCController")
        if not controller_class:
            return None
        objc_msg_send(
            objc,
            controller_class,
            "setShouldMonitorBackgroundEvents:",
            restype=None,
            argtypes=(ctypes.c_bool,),
            args=(True,),
        )
        controllers = objc_msg_send(objc, controller_class, "controllers")
        if not controllers:
            return None
        count = int(objc_msg_send(objc, controllers, "count", restype=ctypes.c_ulong))
        if controller_slot < 0 or controller_slot >= count:
            return None
        controller = objc_msg_send(
            objc,
            controllers,
            "objectAtIndex:",
            argtypes=(ctypes.c_ulong,),
            args=(controller_slot,),
        )
        if not controller:
            return None
        gamepad = objc_msg_send(objc, controller, "extendedGamepad")
        if not gamepad:
            return None
        right_thumbstick = objc_msg_send(objc, gamepad, "rightThumbstick")
        if not right_thumbstick:
            return None
        x_axis = objc_msg_send(objc, right_thumbstick, "xAxis")
        y_axis = objc_msg_send(objc, right_thumbstick, "yAxis")
        right_trigger = objc_msg_send(objc, gamepad, "rightTrigger")
        stick_x = macos_gc_float_value(objc, x_axis, "value") or 0.0
        stick_y = macos_gc_float_value(objc, y_axis, "value") or 0.0
        trigger_value = macos_gc_float_value(objc, right_trigger, "value") or 0.0
        return _AzaharMouseBridgeState(
            stick_x=stick_x,
            stick_y=stick_y,
            primary_down=trigger_value >= _AZAHAR_MOUSE_BRIDGE_TRIGGER_THRESHOLD,
        )
    finally:
        if pool:
            objc_msg_send(objc, pool, "drain", restype=None)


def _create_azahar_mouse_bridge_poller(
    controller: XboxController,
) -> tuple[Callable[[], _AzaharMouseBridgeState | None], _AzaharMouseEmitter]:
    disabled_reason = azahar_mouse_bridge_disabled_reason()
    if disabled_reason is not None:
        raise AzaharMouseBridgeUnavailable(disabled_reason)
    if sys.platform.startswith("win"):
        lib = load_xinput()
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


def _azahar_mouse_bridge_session_active(
    process: subprocess.Popen[bytes],
    *,
    app_id: str | None,
) -> bool:
    if process.poll() is None:
        return True
    if not app_id:
        return False
    return _is_flatpak_app_running(app_id)


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


def detect_azahar_mouse_bridge_controller(
    *, max_devices: int = _AZAHAR_MOUSE_BRIDGE_MAX_DEVICES
) -> XboxController | None:
    if azahar_mouse_bridge_disabled_reason() is not None:
        return None
    controllers = detect_xbox_controllers(max_devices=max_devices)
    if not controllers:
        return None
    return controllers[0]


def start_azahar_mouse_bridge(
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
