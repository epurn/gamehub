from __future__ import annotations

import ctypes
import sys
from typing import Any

_MACOS_OBJC_LIBRARY = "/usr/lib/libobjc.A.dylib"
_MACOS_FOUNDATION_FRAMEWORK = "/System/Library/Frameworks/Foundation.framework/Foundation"
_MACOS_GAMECONTROLLER_FRAMEWORK = "/System/Library/Frameworks/GameController.framework/GameController"


def load_macos_gamecontroller_runtime() -> ctypes.CDLL | None:
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


def objc_selector(objc: ctypes.CDLL, name: str) -> ctypes.c_void_p:
    return ctypes.c_void_p(objc.sel_registerName(name.encode("utf-8")))


def objc_class(objc: ctypes.CDLL, name: str) -> ctypes.c_void_p:
    return ctypes.c_void_p(objc.objc_getClass(name.encode("utf-8")))


def objc_msg_send(
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
    return objc.objc_msgSend(receiver, objc_selector(objc, selector), *args)


def macos_gc_button_pressed(
    objc: ctypes.CDLL,
    gamepad: ctypes.c_void_p,
    selector: str,
) -> bool:
    if not gamepad:
        return False
    responds = objc_msg_send(
        objc,
        gamepad,
        "respondsToSelector:",
        restype=ctypes.c_bool,
        argtypes=(ctypes.c_void_p,),
        args=(objc_selector(objc, selector),),
    )
    if not responds:
        return False
    button = objc_msg_send(objc, gamepad, selector)
    if not button:
        return False
    return bool(objc_msg_send(objc, button, "isPressed", restype=ctypes.c_bool))
