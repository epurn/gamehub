from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import threading
import time

_JS_EVENT_FORMAT = "IhBB"
_JS_EVENT_SIZE = struct.calcsize(_JS_EVENT_FORMAT)
_JS_EVENT_TYPE_BUTTON = 0x01
_JS_EVENT_TYPE_INIT = 0x80
_INPUT_EVENT_FORMAT = "llHHI"
_INPUT_EVENT_SIZE = struct.calcsize(_INPUT_EVENT_FORMAT)
_EV_KEY = 0x01
_BTN_SELECT = 0x13A
_BTN_START = 0x13B
_BUTTON_PATTERN_TEMPLATE = r'^profiles\\\d+\\button_{name}="button:(\d+),'
_SELECT_BUTTON_ENV = "GAMEHUB_AZAHAR_EXIT_BUTTON_SELECT"
_START_BUTTON_ENV = "GAMEHUB_AZAHAR_EXIT_BUTTON_START"
_JS_DEVICE_ENV = "GAMEHUB_AZAHAR_EXIT_JS_DEVICE"


def _azahar_qt_config_candidates() -> list[Path]:
    home = Path.home()
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


def _extract_button_from_qt_config(text: str, *, name: str) -> int | None:
    match = re.search(_BUTTON_PATTERN_TEMPLATE.format(name=name), text, flags=re.MULTILINE)
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


def _resolve_select_and_start_buttons() -> tuple[int, int]:
    env_select = _int_env_optional(_SELECT_BUTTON_ENV)
    env_start = _int_env_optional(_START_BUTTON_ENV)
    if env_select is not None and env_start is not None:
        return env_select, env_start
    cfg_select, cfg_start = _resolve_button_pair_from_config()
    select_button = env_select if env_select is not None else (cfg_select if cfg_select is not None else 4)
    start_button = env_start if env_start is not None else (cfg_start if cfg_start is not None else 6)
    return select_button, start_button


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
            while process.poll() is None and not trigger_event.is_set():
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
            while process.poll() is None and not trigger_event.is_set():
                data = handle.read(_INPUT_EVENT_SIZE)
                if len(data) != _INPUT_EVENT_SIZE:
                    break
                _sec, _usec, event_type, code, value = struct.unpack(_INPUT_EVENT_FORMAT, data)
                if _handle_ev_key_event(pressed_codes, event_type, code, value):
                    trigger_event.set()
                    break

    threads: list[threading.Thread] = []
    if js_devices:
        for device_path in js_devices:
            watcher = threading.Thread(target=_watch, args=(device_path,), daemon=True)
            watcher.start()
            threads.append(watcher)
    else:
        for device_path in _discover_event_devices():
            watcher = threading.Thread(target=_watch_evdev, args=(device_path,), daemon=True)
            watcher.start()
            threads.append(watcher)
    if not threads:
        return

    while process.poll() is None:
        if not trigger_event.wait(0.1):
            continue
        try:
            subprocess.run(["flatpak", "kill", app_id], check=False, capture_output=True, text=True)
        except OSError:
            pass
        deadline = time.monotonic() + 2.0
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if process.poll() is None:
            process.terminate()
            deadline = time.monotonic() + 2.0
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
        if process.poll() is None:
            process.kill()
        return


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
    return process.wait()


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
