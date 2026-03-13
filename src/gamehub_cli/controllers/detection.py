from __future__ import annotations

import ctypes
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, cast

from .sdl_guid import _discover_host_sdl_joysticks

_PROC_INPUT_DEVICES_PATH = Path("/proc/bus/input/devices")
_INPUT_DEVICE_NAME_RE = re.compile(r'^N:\s+Name="(?P<name>.*)"$')
_INPUT_DEVICE_HANDLERS_RE = re.compile(r"^H:\s+Handlers=(?P<handlers>.+)$")
_INPUT_JS_HANDLER_RE = re.compile(r"\bjs(?P<index>\d+)\b")
_STEAMOS_RELEASE_PATH = Path("/etc/os-release")
_DMI_BOARD_VENDOR_PATH = Path("/sys/devices/virtual/dmi/id/board_vendor")
_LINUX_NON_GAMEPAD_NAME_MARKERS = (
    "motion sensor",
    "motion sensors",
    "accelerometer",
    "gyroscope",
    "gyro",
    "imu",
)

_ERROR_SUCCESS = 0
_XINPUT_FLAG_GAMEPAD = 0x00000001
_XINPUT_DLLS = ("xinput1_4", "xinput9_1_0", "xinput1_3")


@dataclass(frozen=True)
class XboxController:
    slot: int
    name: str
    subtype: int | None = None
    guid: str | None = None
    vendor_id: int | None = None
    product_id: int | None = None


def _is_steam_deck_linux() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        os_release = _STEAMOS_RELEASE_PATH.read_text(encoding="utf-8", errors="ignore").casefold()
    except OSError:
        os_release = ""
    if "id=steamos" in os_release or "steamdeck" in os_release or "holo" in os_release:
        return True
    try:
        vendor = _DMI_BOARD_VENDOR_PATH.read_text(encoding="utf-8", errors="ignore").strip().casefold()
    except OSError:
        vendor = ""
    return "valve" in vendor


def _is_supported_linux_controller_name(name: str, *, include_steam_deck: bool) -> bool:
    normalized = name.casefold()
    if any(marker in normalized for marker in _LINUX_NON_GAMEPAD_NAME_MARKERS):
        return False
    if any(marker in normalized for marker in ("xbox", "x-box", "xinput")):
        return True
    if not include_steam_deck:
        return False
    return any(
        marker in normalized
        for marker in (
            "steam deck",
            "steam virtual gamepad",
            "steam controller",
            "valve software",
            "neptune controller",
        )
    )


def _linux_parse_xbox_devices(raw: str, *, max_devices: int, include_steam_deck: bool = False) -> list[XboxController]:
    by_js_index: dict[int, str] = {}
    current_name: str | None = None
    current_handlers: str | None = None

    def _flush_entry() -> None:
        if not current_name or not current_handlers:
            return
        if not _is_supported_linux_controller_name(current_name, include_steam_deck=include_steam_deck):
            return
        for match in _INPUT_JS_HANDLER_RE.finditer(current_handlers):
            js_index = int(match.group("index"))
            by_js_index.setdefault(js_index, current_name)

    for line in [*raw.splitlines(), ""]:
        stripped = line.strip()
        if not stripped:
            _flush_entry()
            current_name = None
            current_handlers = None
            continue
        name_match = _INPUT_DEVICE_NAME_RE.match(stripped)
        if name_match:
            current_name = name_match.group("name")
            continue
        handlers_match = _INPUT_DEVICE_HANDLERS_RE.match(stripped)
        if handlers_match:
            current_handlers = handlers_match.group("handlers")

    controllers: list[XboxController] = []
    for js_index in sorted(by_js_index):
        controllers.append(XboxController(slot=js_index, name=by_js_index[js_index], subtype=None))
        if len(controllers) >= max_devices:
            break
    return controllers


def _detect_linux_xbox_controllers(*, max_devices: int) -> list[XboxController]:
    try:
        raw = _PROC_INPUT_DEVICES_PATH.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    return _linux_parse_xbox_devices(raw, max_devices=max_devices, include_steam_deck=_is_steam_deck_linux())


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


class _XInputCapabilities(ctypes.Structure):
    _fields_ = [
        ("Type", ctypes.c_ubyte),
        ("SubType", ctypes.c_ubyte),
        ("Flags", ctypes.c_ushort),
        ("Gamepad", _XInputGamepad),
        ("VibrationLeftMotorSpeed", ctypes.c_ushort),
        ("VibrationRightMotorSpeed", ctypes.c_ushort),
    ]


def _load_xinput_dll() -> ctypes.CDLL | None:
    win_dll_loader = cast(Callable[[str], ctypes.CDLL] | None, getattr(ctypes, "WinDLL", None))
    if win_dll_loader is None:
        return None
    for dll_name in _XINPUT_DLLS:
        try:
            return win_dll_loader(dll_name)
        except OSError:
            continue
    return None


def _detect_windows_xbox_controllers(*, max_devices: int) -> list[XboxController]:
    dll = _load_xinput_dll()
    if dll is None:
        return []

    get_state = dll.XInputGetState
    get_state.argtypes = [ctypes.c_ulong, ctypes.POINTER(_XInputState)]
    get_state.restype = ctypes.c_ulong

    get_capabilities = getattr(dll, "XInputGetCapabilities", None)
    if get_capabilities is not None:
        get_capabilities.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.POINTER(_XInputCapabilities)]
        get_capabilities.restype = ctypes.c_ulong

    controllers: list[XboxController] = []
    for slot in range(4):
        state = _XInputState()
        result = int(get_state(slot, ctypes.pointer(state)))
        if result != _ERROR_SUCCESS:
            continue
        subtype: int | None = None
        if get_capabilities is not None:
            caps = _XInputCapabilities()
            caps_result = int(get_capabilities(slot, _XINPUT_FLAG_GAMEPAD, ctypes.pointer(caps)))
            if caps_result == _ERROR_SUCCESS:
                subtype = int(caps.SubType)
        controllers.append(XboxController(slot=slot, name=f"XInput/{slot}", subtype=subtype))
        if len(controllers) >= max_devices:
            break
    return controllers


def _is_supported_macos_controller_name(name: str) -> bool:
    normalized = name.casefold()
    if any(marker in normalized for marker in _LINUX_NON_GAMEPAD_NAME_MARKERS):
        return False
    return any(marker in normalized for marker in ("xbox", "x-box", "xinput"))


def _is_supported_macos_controller(device: object) -> bool:
    name = str(getattr(device, "name", "")).strip()
    normalized = name.casefold()
    if any(marker in normalized for marker in _LINUX_NON_GAMEPAD_NAME_MARKERS):
        return False
    is_game_controller = getattr(device, "is_game_controller", None)
    if is_game_controller is True:
        return True
    return _is_supported_macos_controller_name(name)


def _detect_macos_xbox_controllers(*, max_devices: int) -> list[XboxController]:
    try:
        devices = _discover_host_sdl_joysticks()
    except Exception:
        return []
    controllers: list[XboxController] = []
    for device in devices:
        if not _is_supported_macos_controller(device):
            continue
        controllers.append(
            XboxController(
                slot=device.slot,
                name=device.name,
                subtype=None,
                guid=getattr(device, "guid", None),
                vendor_id=getattr(device, "vendor_id", None),
                product_id=getattr(device, "product_id", None),
            )
        )
        if len(controllers) >= max_devices:
            break
    return controllers


def is_steam_deck_linux() -> bool:
    return _is_steam_deck_linux()


def detect_xbox_controllers(*, max_devices: int = 2) -> list[XboxController]:
    if max_devices < 1:
        return []
    if sys.platform.startswith("linux"):
        return _detect_linux_xbox_controllers(max_devices=max_devices)
    if sys.platform.startswith("win"):
        return _detect_windows_xbox_controllers(max_devices=max_devices)
    if sys.platform == "darwin":
        return _detect_macos_xbox_controllers(max_devices=max_devices)
    return []
