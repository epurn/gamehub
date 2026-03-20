from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_PROC_INPUT_DEVICES_PATH = Path("/proc/bus/input/devices")
_INPUT_DEVICE_NAME_RE = re.compile(r'^N:\s+Name="(?P<name>.*)"$')
_INPUT_DEVICE_HANDLERS_RE = re.compile(r"^H:\s+Handlers=(?P<handlers>.+)$")
_INPUT_EVENT_HANDLER_RE = re.compile(r"\bevent(?P<index>\d+)\b")
_INPUT_JS_HANDLER_RE = re.compile(r"\bjs(?P<index>\d+)\b")
_INPUT_JS_BASENAME_RE = re.compile(r"^js(?P<index>\d+)$")


@dataclass(frozen=True)
class LinuxInputDeviceRecord:
    name: str
    js_indices: tuple[int, ...]
    event_indices: tuple[int, ...]


def parse_linux_input_device_records(raw: str) -> list[LinuxInputDeviceRecord]:
    records: list[LinuxInputDeviceRecord] = []
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
            LinuxInputDeviceRecord(
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


def read_linux_input_device_records() -> list[LinuxInputDeviceRecord]:
    raw = _PROC_INPUT_DEVICES_PATH.read_text(encoding="utf-8", errors="ignore")
    return parse_linux_input_device_records(raw)


def js_device_index(path_value: str) -> int | None:
    basename = Path(path_value).name
    match = _INPUT_JS_BASENAME_RE.match(basename)
    if match is None:
        return None
    return int(match.group("index"))
