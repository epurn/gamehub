from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Callable

from ..common.config import GamehubConfig
from ..common.fsops import replace_file
from ..firmware.pcsx2_ini import pcsx2_pad_bindings

PROFILE_KBM = "kbm"
PROFILE_XBOX_1P = "xbox_1p"
PROFILE_XBOX_2P = "xbox_2p"
VALID_PROFILES = (PROFILE_KBM, PROFILE_XBOX_1P, PROFILE_XBOX_2P)


def profile_name_for_controller_count(controller_count: int) -> str:
    if controller_count <= 0:
        return PROFILE_KBM
    if controller_count == 1:
        return PROFILE_XBOX_1P
    return PROFILE_XBOX_2P


def resolve_profiles_root(config: GamehubConfig) -> Path:
    if config.controllers.profiles_dir is not None:
        return config.controllers.profiles_dir.expanduser()
    return config.library_dir / "controller_profiles"


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp") as tmp:
        tmp.write(text)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = path.parent / os.path.basename(tmp.name)
    replace_file(tmp_path, path)


def _build_ini_text(sections: dict[str, dict[str, str]]) -> str:
    lines: list[str] = []
    for section, values in sections.items():
        if lines:
            lines.append("")
        lines.append(f"[{section}]")
        for key, value in values.items():
            lines.append(f"{key} = {value}")
    return "\n".join(lines).rstrip() + "\n"


def _pcsx2_keyboard_pad_bindings(pad_number: int) -> dict[str, str]:
    if pad_number == 1:
        return {
            "Up": "Keyboard/W",
            "Right": "Keyboard/D",
            "Down": "Keyboard/S",
            "Left": "Keyboard/A",
            "Triangle": "Keyboard/I",
            "Circle": "Keyboard/L",
            "Cross": "Keyboard/K",
            "Square": "Keyboard/J",
            "Select": "Keyboard/Backspace",
            "Start": "Keyboard/Return",
            "L1": "Keyboard/Q",
            "L2": "Keyboard/1",
            "R1": "Keyboard/E",
            "R2": "Keyboard/3",
            "L3": "Keyboard/Z",
            "R3": "Keyboard/C",
            "LUp": "Keyboard/Up",
            "LRight": "Keyboard/Right",
            "LDown": "Keyboard/Down",
            "LLeft": "Keyboard/Left",
            "RUp": "Keyboard/T",
            "RRight": "Keyboard/H",
            "RDown": "Keyboard/G",
            "RLeft": "Keyboard/F",
            "LargeMotor": "None",
            "SmallMotor": "None",
        }
    return {
        "Up": "Keyboard/Num8",
        "Right": "Keyboard/Num6",
        "Down": "Keyboard/Num5",
        "Left": "Keyboard/Num4",
        "Triangle": "Keyboard/PageUp",
        "Circle": "Keyboard/PageDown",
        "Cross": "Keyboard/Num0",
        "Square": "Keyboard/Num7",
        "Select": "Keyboard/Delete",
        "Start": "Keyboard/NumEnter",
        "L1": "Keyboard/Home",
        "L2": "Keyboard/Insert",
        "R1": "Keyboard/End",
        "R2": "Keyboard/Num9",
        "L3": "Keyboard/Num1",
        "R3": "Keyboard/Num3",
        "LUp": "Keyboard/Num8",
        "LRight": "Keyboard/Num6",
        "LDown": "Keyboard/Num5",
        "LLeft": "Keyboard/Num4",
        "RUp": "Keyboard/PageUp",
        "RRight": "Keyboard/PageDown",
        "RDown": "Keyboard/Num0",
        "RLeft": "Keyboard/Num7",
        "LargeMotor": "None",
        "SmallMotor": "None",
    }


def _pcsx2_pad_mapping_dict(pad_index: int) -> dict[str, str]:
    return {key: value for key, value in pcsx2_pad_bindings(pad_index)}


def _pcsx2_profile_text(profile_name: str) -> str:
    if profile_name == PROFILE_KBM:
        pad1 = _pcsx2_keyboard_pad_bindings(1)
        pad2 = _pcsx2_keyboard_pad_bindings(2)
        open_pause_menu = "Keyboard/Escape"
    elif profile_name == PROFILE_XBOX_1P:
        pad1 = _pcsx2_pad_mapping_dict(0)
        # Keep xbox_1p fallback deterministic: P2 uses primary keyboard layout.
        pad2 = _pcsx2_keyboard_pad_bindings(1)
        open_pause_menu = "SDL-0/Back & SDL-0/Start"
    else:
        pad1 = _pcsx2_pad_mapping_dict(0)
        pad2 = _pcsx2_pad_mapping_dict(1)
        open_pause_menu = "SDL-0/Back & SDL-0/Start"
    sections = {
        "InputSources": {"SDL": "true"},
        "Pad1": {"Type": "DualShock2", **pad1},
        "Pad2": {"Type": "DualShock2", **pad2},
        "Hotkeys": {"OpenPauseMenu": open_pause_menu},
    }
    return _build_ini_text(sections)


_DOLPHIN_XBOX_GCPAD_BINDINGS: tuple[tuple[str, str], ...] = (
    ("Buttons/A", "SOUTH | `Button A`"),
    ("Buttons/B", "EAST | `Button B`"),
    ("Buttons/X", "WEST | `Button X`"),
    ("Buttons/Y", "NORTH | `Button Y`"),
    ("Buttons/Z", "`Trigger R`"),
    ("Buttons/Start", "START | Start"),
    ("Main Stick/Up", "`Axis 1-` | `Left Y+`"),
    ("Main Stick/Down", "`Axis 1+` | `Left Y-`"),
    ("Main Stick/Left", "`Axis 0-` | `Left X-`"),
    ("Main Stick/Right", "`Axis 0+` | `Left X+`"),
    ("Main Stick/Modifier", "`Thumb L`"),
    ("Main Stick/Modifier/Range", "50.000000000000000"),
    ("C-Stick/Up", "`Axis 3-` | `Right Y+`"),
    ("C-Stick/Down", "`Axis 3+` | `Right Y-`"),
    ("C-Stick/Left", "`Axis 2-` | `Right X-`"),
    ("C-Stick/Right", "`Axis 2+` | `Right X+`"),
    ("C-Stick/Modifier", "`Thumb R`"),
    ("C-Stick/Modifier/Range", "50.000000000000000"),
    ("Triggers/L", "`Shoulder L`"),
    ("Triggers/R", "`Shoulder R`"),
    ("Rumble/Motor", "`Motor L` | `Motor R`"),
    ("D-Pad/Up", "`Pad N`"),
    ("D-Pad/Down", "`Pad S`"),
    ("D-Pad/Left", "`Pad W`"),
    ("D-Pad/Right", "`Pad E`"),
)

_DOLPHIN_XBOX_WIIMOTE_BINDINGS: tuple[tuple[str, str], ...] = (
    ("Buttons/A", "SOUTH | `Button A`"),
    ("Buttons/B", "EAST | `Button B`"),
    ("Buttons/1", "WEST | `Button X`"),
    ("Buttons/2", "NORTH | `Button Y`"),
    ("Buttons/-", "BACK | Back"),
    ("Buttons/+", "START | Start"),
    ("Buttons/Home", "GUIDE | `Thumb R`"),
    ("D-Pad/Up", "`Pad N`"),
    ("D-Pad/Down", "`Pad S`"),
    ("D-Pad/Left", "`Pad W`"),
    ("D-Pad/Right", "`Pad E`"),
    ("IR/Up", "`Axis 3-` | `Right Y-`"),
    ("IR/Down", "`Axis 3+` | `Right Y+`"),
    ("IR/Left", "`Axis 2-` | `Right X-`"),
    ("IR/Right", "`Axis 2+` | `Right X+`"),
    ("IR/Auto-Hide", "False"),
    ("Nunchuk/Stick/Up", "`Axis 1-` | `Left Y+`"),
    ("Nunchuk/Stick/Down", "`Axis 1+` | `Left Y-`"),
    ("Nunchuk/Stick/Left", "`Axis 0-` | `Left X-`"),
    ("Nunchuk/Stick/Right", "`Axis 0+` | `Left X+`"),
    ("Nunchuk/Buttons/C", "`Shoulder L`"),
    ("Nunchuk/Buttons/Z", "`Trigger L`"),
    ("Rumble/Motor", "`Motor L` | `Motor R`"),
)

_DOLPHIN_KBM_GCPAD_BINDINGS: tuple[tuple[str, str], ...] = (
    ("Buttons/A", "X"),
    ("Buttons/B", "`Z`"),
    ("Buttons/X", "`C`"),
    ("Buttons/Y", "`S`"),
    ("Buttons/Z", "`D`"),
    ("Buttons/Start", "`RETURN`"),
    ("Main Stick/Up", "UP"),
    ("Main Stick/Down", "DOWN"),
    ("Main Stick/Left", "LEFT"),
    ("Main Stick/Right", "RIGHT"),
    ("Main Stick/Modifier", "`Shift`"),
    ("Main Stick/Calibration", "100.00 141.42 100.00 141.42 100.00 141.42 100.00 141.42"),
    ("C-Stick/Up", "`I`"),
    ("C-Stick/Down", "`K`"),
    ("C-Stick/Left", "`J`"),
    ("C-Stick/Right", "`L`"),
    ("C-Stick/Modifier", "`Ctrl`"),
    ("C-Stick/Calibration", "100.00 141.42 100.00 141.42 100.00 141.42 100.00 141.42"),
    ("Triggers/L", "`Q`"),
    ("Triggers/R", "`W`"),
    ("D-Pad/Up", "`T`"),
    ("D-Pad/Down", "`G`"),
    ("D-Pad/Left", "`F`"),
    ("D-Pad/Right", "`H`"),
)

_DOLPHIN_KBM_WIIMOTE_BINDINGS: tuple[tuple[str, str], ...] = (
    ("Buttons/A", "`Click 0`"),
    ("Buttons/B", "`Click 1`"),
    ("Buttons/1", "`1`"),
    ("Buttons/2", "`2`"),
    ("Buttons/-", "Q"),
    ("Buttons/+", "E"),
    ("Buttons/Home", "RETURN"),
    ("D-Pad/Up", "UP"),
    ("D-Pad/Down", "DOWN"),
    ("D-Pad/Left", "LEFT"),
    ("D-Pad/Right", "RIGHT"),
    ("IR/Up", "`Cursor Y-`"),
    ("IR/Down", "`Cursor Y+`"),
    ("IR/Left", "`Cursor X-`"),
    ("IR/Right", "`Cursor X+`"),
    ("Shake/X", "`Click 2`"),
    ("Shake/Y", "`Click 2`"),
    ("Shake/Z", "`Click 2`"),
    ("IRPassthrough/Object 1 X", "`IR Object 1 X`"),
    ("IRPassthrough/Object 1 Y", "`IR Object 1 Y`"),
    ("IRPassthrough/Object 1 Size", "`IR Object 1 Size`"),
    ("IRPassthrough/Object 2 X", "`IR Object 2 X`"),
    ("IRPassthrough/Object 2 Y", "`IR Object 2 Y`"),
    ("IRPassthrough/Object 2 Size", "`IR Object 2 Size`"),
    ("IRPassthrough/Object 3 X", "`IR Object 3 X`"),
    ("IRPassthrough/Object 3 Y", "`IR Object 3 Y`"),
    ("IRPassthrough/Object 3 Size", "`IR Object 3 Size`"),
    ("IRPassthrough/Object 4 X", "`IR Object 4 X`"),
    ("IRPassthrough/Object 4 Y", "`IR Object 4 Y`"),
    ("IRPassthrough/Object 4 Size", "`IR Object 4 Size`"),
    ("IMUAccelerometer/Up", "`Accel Up`"),
    ("IMUAccelerometer/Down", "`Accel Down`"),
    ("IMUAccelerometer/Left", "`Accel Left`"),
    ("IMUAccelerometer/Right", "`Accel Right`"),
    ("IMUAccelerometer/Forward", "`Accel Forward`"),
    ("IMUAccelerometer/Backward", "`Accel Backward`"),
    ("IMUGyroscope/Pitch Up", "`Gyro Pitch Up`"),
    ("IMUGyroscope/Pitch Down", "`Gyro Pitch Down`"),
    ("IMUGyroscope/Roll Left", "`Gyro Roll Left`"),
    ("IMUGyroscope/Roll Right", "`Gyro Roll Right`"),
    ("IMUGyroscope/Yaw Left", "`Gyro Yaw Left`"),
    ("IMUGyroscope/Yaw Right", "`Gyro Yaw Right`"),
    ("Extension", "Nunchuk"),
    ("Nunchuk/Buttons/C", "LCONTROL"),
    ("Nunchuk/Buttons/Z", "LSHIFT"),
    ("Nunchuk/Stick/Up", "W"),
    ("Nunchuk/Stick/Down", "S"),
    ("Nunchuk/Stick/Left", "A"),
    ("Nunchuk/Stick/Right", "D"),
    ("Nunchuk/Stick/Calibration", "100.00 141.42 100.00 141.42 100.00 141.42 100.00 141.42"),
    ("Nunchuk/Shake/X", "`Click 2`"),
    ("Nunchuk/Shake/Y", "`Click 2`"),
    ("Nunchuk/Shake/Z", "`Click 2`"),
)


def _dolphin_device_pair(profile_name: str) -> tuple[str, str]:
    if profile_name == PROFILE_KBM:
        if sys.platform.startswith("linux"):
            return "XInput2/0/Virtual core pointer", "None"
        return "DInput/0/Keyboard Mouse", "None"
    if sys.platform.startswith("linux"):
        # Linux Dolphin controller device roots are SDL/evdev-style, not XInput.
        if profile_name == PROFILE_XBOX_1P:
            return "SDL/0/Gamepad", "DInput/0/Keyboard Mouse"
        return "SDL/0/Gamepad", "SDL/1/Gamepad"
    if profile_name == PROFILE_XBOX_1P:
        return "XInput/0/Gamepad", "DInput/0/Keyboard Mouse"
    return "XInput/0/Gamepad", "XInput/1/Gamepad"


def _dolphin_profile_files(profile_name: str) -> dict[str, str]:
    device0, device1 = _dolphin_device_pair(profile_name)
    general_hotkeys: dict[str, str] = {}
    if profile_name == PROFILE_KBM:
        gcpad_bindings_1 = _DOLPHIN_KBM_GCPAD_BINDINGS
        gcpad_bindings_2 = _DOLPHIN_KBM_GCPAD_BINDINGS
        wiimote_bindings_1 = _DOLPHIN_KBM_WIIMOTE_BINDINGS
        wiimote_bindings_2 = _DOLPHIN_KBM_WIIMOTE_BINDINGS
        hotkey_value = "ESCAPE"
        general_stop = "ESCAPE"
        general_exit = "ESCAPE"
        general_hotkeys = {
            "General/Open": "@(Ctrl+O)",
            "General/Toggle Pause": "F10",
            "General/Toggle Fullscreen": "@(Alt+RETURN)",
            "General/Take Screenshot": "F9",
        }
        if sys.platform.startswith("linux"):
            hotkey_device0, hotkey_device1 = "XInput2/0/Virtual core pointer", "XInput2/0/Virtual core pointer"
        else:
            hotkey_device0, hotkey_device1 = device0, device1
    elif profile_name == PROFILE_XBOX_1P:
        gcpad_bindings_1 = _DOLPHIN_XBOX_GCPAD_BINDINGS
        gcpad_bindings_2 = _DOLPHIN_KBM_GCPAD_BINDINGS
        wiimote_bindings_1 = _DOLPHIN_XBOX_WIIMOTE_BINDINGS
        wiimote_bindings_2 = _DOLPHIN_KBM_WIIMOTE_BINDINGS
        hotkey_value = "((`BACK` | `Back` | `SELECT` | `Select` | `Button 6`) & (`START` | `Start` | `Button 7`))"
        general_stop = "@(SELECT+START)"
        general_exit = "@(SELECT+START)"
        hotkey_device0, hotkey_device1 = device0, device1
    else:
        gcpad_bindings_1 = _DOLPHIN_XBOX_GCPAD_BINDINGS
        gcpad_bindings_2 = _DOLPHIN_XBOX_GCPAD_BINDINGS
        wiimote_bindings_1 = _DOLPHIN_XBOX_WIIMOTE_BINDINGS
        wiimote_bindings_2 = _DOLPHIN_XBOX_WIIMOTE_BINDINGS
        hotkey_value = "((`BACK` | `Back` | `SELECT` | `Select` | `Button 6`) & (`START` | `Start` | `Button 7`))"
        general_stop = "@(SELECT+START)"
        general_exit = "@(SELECT+START)"
        hotkey_device0, hotkey_device1 = device0, device1

    gcpad_sections: dict[str, dict[str, str]] = {}
    for pad_number, device, bindings in (
        (1, device0, gcpad_bindings_1),
        (2, device1, gcpad_bindings_2),
    ):
        section = f"GCPad{pad_number}"
        gcpad_sections[section] = {"Device": device}
        for key, value in bindings:
            gcpad_sections[section][key] = value

    wiimote_sections: dict[str, dict[str, str]] = {}
    for wiimote_number, device, bindings in (
        (1, device0, wiimote_bindings_1),
        (2, device1, wiimote_bindings_2),
    ):
        section = f"Wiimote{wiimote_number}"
        wiimote_sections[section] = {"Device": device, "Source": "1", "Extension": "Nunchuk"}
        for key, value in bindings:
            wiimote_sections[section][key] = value

    hotkey_sections = {
        "Hotkeys1": {"Device": hotkey_device0, "Keys/Stop": hotkey_value, "Keys/Exit": hotkey_value},
        "Hotkeys2": {"Device": hotkey_device1, "Keys/Stop": hotkey_value, "Keys/Exit": hotkey_value},
        "Hotkeys": {
            "Device": hotkey_device0,
            "General/Stop": general_stop,
            "General/Exit": general_exit,
            **general_hotkeys,
        },
    }

    return {
        "GCPadNew.ini": _build_ini_text(gcpad_sections),
        "WiimoteNew.ini": _build_ini_text(wiimote_sections),
        "Hotkeys.ini": _build_ini_text(hotkey_sections),
    }


_AZAHAR_KBM_QT_CONFIG = (
    "[Controls]\n"
    "profile=0\n"
    r"profile\default=true"
    "\n"
    r'profiles\1\button_a="code:65,engine:keyboard"'
    "\n"
    r"profiles\1\button_a\default=false"
    "\n"
    r'profiles\1\button_b="code:83,engine:keyboard"'
    "\n"
    r"profiles\1\button_b\default=false"
    "\n"
    r'profiles\1\button_x="code:68,engine:keyboard"'
    "\n"
    r"profiles\1\button_x\default=false"
    "\n"
    r'profiles\1\button_y="code:87,engine:keyboard"'
    "\n"
    r"profiles\1\button_y\default=false"
    "\n"
    r'profiles\1\button_select="code:16777219,engine:keyboard"'
    "\n"
    r"profiles\1\button_select\default=false"
    "\n"
    r'profiles\1\button_start="code:16777220,engine:keyboard"'
    "\n"
    r"profiles\1\button_start\default=false"
    "\n"
    r'profiles\1\button_l="code:81,engine:keyboard"'
    "\n"
    r"profiles\1\button_l\default=false"
    "\n"
    r'profiles\1\button_r="code:69,engine:keyboard"'
    "\n"
    r"profiles\1\button_r\default=false"
    "\n"
    r'profiles\1\button_zl="code:49,engine:keyboard"'
    "\n"
    r"profiles\1\button_zl\default=false"
    "\n"
    r'profiles\1\button_zr="code:50,engine:keyboard"'
    "\n"
    r"profiles\1\button_zr\default=false"
    "\n"
    r'profiles\1\button_home="code:66,engine:keyboard"'
    "\n"
    r"profiles\1\button_home\default=false"
    "\n"
    r'profiles\1\button_up="code:16777235,engine:keyboard"'
    "\n"
    r"profiles\1\button_up\default=false"
    "\n"
    r'profiles\1\button_down="code:16777237,engine:keyboard"'
    "\n"
    r"profiles\1\button_down\default=false"
    "\n"
    r'profiles\1\button_left="code:16777234,engine:keyboard"'
    "\n"
    r"profiles\1\button_left\default=false"
    "\n"
    r'profiles\1\button_right="code:16777236,engine:keyboard"'
    "\n"
    r"profiles\1\button_right\default=false"
    "\n"
    r'profiles\1\circle_pad="down:code$016777237$1engine$0keyboard,left:code$016777234$1engine$0keyboard,modifier:code$068$1engine$0keyboard,modifier_scale:0.500000,right:code$016777236$1engine$0keyboard,up:code$016777235$1engine$0keyboard"'
    "\n"
    r"profiles\1\circle_pad\default=false"
    "\n"
    r'profiles\1\c_stick="down:code$083$1engine$0keyboard,left:code$065$1engine$0keyboard,modifier:code$068$1engine$0keyboard,modifier_scale:0.500000,right:code$068$1engine$0keyboard,up:code$087$1engine$0keyboard"'
    "\n"
    r"profiles\1\c_stick\default=false"
    "\n"
)


def _azahar_sdl_qt_config(*, port: int) -> str:
    return (
        "[Controls]\n"
        "profile=0\n"
        r"profile\default=true"
        "\n"
        rf'profiles\1\button_a="button:0,engine:sdl,port:{port}"'
        "\n"
        r"profiles\1\button_a\default=false"
        "\n"
        rf'profiles\1\button_b="button:1,engine:sdl,port:{port}"'
        "\n"
        r"profiles\1\button_b\default=false"
        "\n"
        rf'profiles\1\button_x="button:2,engine:sdl,port:{port}"'
        "\n"
        r"profiles\1\button_x\default=false"
        "\n"
        rf'profiles\1\button_y="button:3,engine:sdl,port:{port}"'
        "\n"
        r"profiles\1\button_y\default=false"
        "\n"
        rf'profiles\1\button_select="button:4,engine:sdl,port:{port}"'
        "\n"
        r"profiles\1\button_select\default=false"
        "\n"
        rf'profiles\1\button_start="button:6,engine:sdl,port:{port}"'
        "\n"
        r"profiles\1\button_start\default=false"
        "\n"
        rf'profiles\1\button_l="button:9,engine:sdl,port:{port}"'
        "\n"
        r"profiles\1\button_l\default=false"
        "\n"
        rf'profiles\1\button_r="button:10,engine:sdl,port:{port}"'
        "\n"
        r"profiles\1\button_r\default=false"
        "\n"
        rf'profiles\1\button_zl="axis:4,direction:+,engine:sdl,port:{port},threshold:0.5"'
        "\n"
        r"profiles\1\button_zl\default=false"
        "\n"
        rf'profiles\1\button_zr="axis:5,direction:+,engine:sdl,port:{port},threshold:0.5"'
        "\n"
        r"profiles\1\button_zr\default=false"
        "\n"
        rf'profiles\1\button_home="button:15,engine:sdl,port:{port}"'
        "\n"
        r"profiles\1\button_home\default=false"
        "\n"
        rf'profiles\1\button_up="button:11,engine:sdl,port:{port}"'
        "\n"
        r"profiles\1\button_up\default=false"
        "\n"
        rf'profiles\1\button_down="button:12,engine:sdl,port:{port}"'
        "\n"
        r"profiles\1\button_down\default=false"
        "\n"
        rf'profiles\1\button_left="button:13,engine:sdl,port:{port}"'
        "\n"
        r"profiles\1\button_left\default=false"
        "\n"
        rf'profiles\1\button_right="button:14,engine:sdl,port:{port}"'
        "\n"
        r"profiles\1\button_right\default=false"
        "\n"
        rf'profiles\1\circle_pad="down:axis$01$1direction$0+$1engine$0sdl$1port$0{port}$1threshold$00.5,engine:analog_from_button,left:axis$00$1direction$0-$1engine$0sdl$1port$0{port}$1threshold$00-0.5,modifier:code$068$1engine$0keyboard,modifier_scale:0.500000,right:axis$00$1direction$0+$1engine$0sdl$1port$0{port}$1threshold$00.5,up:axis$01$1direction$0-$1engine$0sdl$1port$0{port}$1threshold$00-0.5"'
        "\n"
        r"profiles\1\circle_pad\default=false"
        "\n"
        rf'profiles\1\c_stick="down:axis$03$1direction$0+$1engine$0sdl$1port$0{port}$1threshold$00.5,engine:analog_from_button,left:axis$02$1direction$0-$1engine$0sdl$1port$0{port}$1threshold$00-0.5,modifier:code$068$1engine$0keyboard,modifier_scale:0.500000,right:axis$02$1direction$0+$1engine$0sdl$1port$0{port}$1threshold$00.5,up:axis$03$1direction$0-$1engine$0sdl$1port$0{port}$1threshold$00-0.5"'
        "\n"
        r"profiles\1\c_stick\default=false"
        "\n"
    )


def _azahar_profile_files(profile_name: str) -> dict[str, str]:
    if profile_name == PROFILE_KBM:
        return {"qt-config.ini": _AZAHAR_KBM_QT_CONFIG}
    return {"qt-config.ini": _azahar_sdl_qt_config(port=0)}


def _default_profile_texts() -> dict[str, dict[str, dict[str, str]]]:
    data: dict[str, dict[str, dict[str, str]]] = {"pcsx2": {}, "dolphin": {}, "azahar": {}}
    for profile_name in VALID_PROFILES:
        data["pcsx2"][profile_name] = {"PCSX2.ini": _pcsx2_profile_text(profile_name)}
        data["dolphin"][profile_name] = _dolphin_profile_files(profile_name)
        data["azahar"][profile_name] = _azahar_profile_files(profile_name)
    return data


DEFAULT_PROFILE_TEXTS = _default_profile_texts()


def seed_default_profiles(
    config: GamehubConfig,
    *,
    verbose: bool = False,
    writer: Callable[[str], None] = print,
    force: bool = False,
    allow_custom: bool = False,
) -> list[Path]:
    if config.controllers.profiles_dir is not None and not allow_custom:
        if verbose:
            writer("controller-profile\tseeded\tskip\tcustom_profiles_dir=true")
        return []
    root = resolve_profiles_root(config)
    created: list[Path] = []
    for emulator_name, profiles in DEFAULT_PROFILE_TEXTS.items():
        for profile_name, files in profiles.items():
            for filename, payload in files.items():
                target = root / emulator_name / profile_name / filename
                if target.exists() and not force:
                    continue
                _atomic_write_text(target, payload)
                created.append(target)
                if verbose:
                    writer(f"controller-profile\tseeded\t{target}")
    return created


def load_profile_file(
    config: GamehubConfig,
    *,
    emulator_name: str,
    profile_name: str,
    filename: str,
) -> list[str]:
    emulator_key = emulator_name.casefold()
    selected_profile = profile_name if profile_name in VALID_PROFILES else PROFILE_KBM
    defaults = DEFAULT_PROFILE_TEXTS.get(emulator_key, {}).get(selected_profile, {})
    default_payload = defaults.get(filename)
    path = resolve_profiles_root(config) / emulator_key / selected_profile / filename
    if path.exists():
        return path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if default_payload is None:
        return []
    return default_payload.splitlines()
