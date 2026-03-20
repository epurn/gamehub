from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import Callable, cast

_ERROR_SUCCESS = 0
_XINPUT_FLAG_GAMEPAD = 0x00000001
_XINPUT_DLLS = ("xinput1_4", "xinput9_1_0", "xinput1_3")


@dataclass(frozen=True)
class XInputGamepadState:
    buttons: int


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


def load_xinput() -> ctypes.CDLL | None:
    win_dll_loader = cast(Callable[[str], ctypes.CDLL] | None, getattr(ctypes, "WinDLL", None))
    if win_dll_loader is None:
        return None
    for dll_name in _XINPUT_DLLS:
        try:
            return win_dll_loader(dll_name)
        except OSError:
            continue
    return None


def _configure_get_state(lib: ctypes.CDLL) -> Callable[[int, object], int] | None:
    get_state = getattr(lib, "XInputGetState", None)
    if get_state is None:
        return None
    get_state.argtypes = [ctypes.c_ulong, ctypes.POINTER(_XInputState)]
    get_state.restype = ctypes.c_ulong
    return cast(Callable[[int, object], int], get_state)


def _configure_get_capabilities(lib: ctypes.CDLL) -> Callable[[int, int, object], int] | None:
    get_capabilities = getattr(lib, "XInputGetCapabilities", None)
    if get_capabilities is None:
        return None
    get_capabilities.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.POINTER(_XInputCapabilities)]
    get_capabilities.restype = ctypes.c_ulong
    return cast(Callable[[int, int, object], int], get_capabilities)


def read_xinput_state(lib: ctypes.CDLL, *, slot: int) -> XInputGamepadState | None:
    get_state = _configure_get_state(lib)
    if get_state is None:
        return None
    state = _XInputState()
    result = int(get_state(slot, ctypes.pointer(state)))
    if result != _ERROR_SUCCESS:
        return None
    gamepad = state.Gamepad
    return XInputGamepadState(buttons=int(gamepad.wButtons))


def read_xinput_subtype(lib: ctypes.CDLL, *, slot: int) -> int | None:
    get_capabilities = _configure_get_capabilities(lib)
    if get_capabilities is None:
        return None
    caps = _XInputCapabilities()
    result = int(get_capabilities(slot, _XINPUT_FLAG_GAMEPAD, ctypes.pointer(caps)))
    if result != _ERROR_SUCCESS:
        return None
    return int(caps.SubType)
