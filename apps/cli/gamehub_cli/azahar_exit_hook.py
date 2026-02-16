from __future__ import annotations

import argparse
import os
from pathlib import Path
import struct
import subprocess
import sys
import threading
import time

_JS_EVENT_FORMAT = "IhBB"
_JS_EVENT_SIZE = struct.calcsize(_JS_EVENT_FORMAT)
_JS_EVENT_TYPE_BUTTON = 0x01
_JS_EVENT_TYPE_INIT = 0x80


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        return default


def _discover_js_device() -> str | None:
    dev_input = Path("/dev/input")
    if not dev_input.exists():
        return None
    for candidate in sorted(dev_input.glob("js*")):
        if candidate.is_char_device() or candidate.exists():
            return str(candidate)
    return None


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


def _monitor_combo_and_terminate(
    process: subprocess.Popen[bytes],
    *,
    select_button: int,
    start_button: int,
    js_device: str | None,
) -> None:
    device_path = js_device or _discover_js_device()
    if not device_path:
        return
    try:
        handle = open(device_path, "rb", buffering=0)
    except OSError:
        return

    with handle:
        pressed_buttons: set[int] = set()
        triggered = False
        while process.poll() is None:
            data = handle.read(_JS_EVENT_SIZE)
            if len(data) != _JS_EVENT_SIZE:
                break
            _time_ms, value, event_type, number = struct.unpack(_JS_EVENT_FORMAT, data)
            if not _handle_js_event(
                pressed_buttons,
                event_type,
                value,
                number,
                select_button=select_button,
                start_button=start_button,
            ):
                continue
            if triggered:
                continue
            triggered = True
            process.terminate()
            deadline = time.monotonic() + 2.0
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            if process.poll() is None:
                process.kill()
            break


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
    select_button = _int_env("GAMEHUB_AZAHAR_EXIT_BUTTON_SELECT", 4)
    start_button = _int_env("GAMEHUB_AZAHAR_EXIT_BUTTON_START", 6)
    js_device = os.environ.get("GAMEHUB_AZAHAR_EXIT_JS_DEVICE")
    watcher = threading.Thread(
        target=_monitor_combo_and_terminate,
        args=(process,),
        kwargs={
            "select_button": select_button,
            "start_button": start_button,
            "js_device": js_device,
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
