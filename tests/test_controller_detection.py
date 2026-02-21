from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import shutil
from uuid import uuid4

from gamehub_cli import controller_detection
from gamehub_cli.controllers.detection import XboxController, detect_xbox_controllers


def test_linux_parse_xbox_devices_filters_and_orders_by_js() -> None:
    raw = "\n".join(
        [
            'N: Name="Generic USB Joystick"',
            "H: Handlers=js2 event24",
            "",
            'N: Name="Xbox Wireless Controller"',
            "H: Handlers=kbd event18 js1",
            "",
            'N: Name="XBOX 360 Controller"',
            "H: Handlers=kbd event12 js0",
            "",
        ]
    )

    devices = controller_detection._linux_parse_xbox_devices(raw, max_devices=2)

    assert devices == [
        XboxController(slot=0, name="XBOX 360 Controller", subtype=None),
        XboxController(slot=1, name="Xbox Wireless Controller", subtype=None),
    ]


def test_detect_xbox_controllers_linux_reads_proc_file(monkeypatch) -> None:
    with _workspace_tempdir("gamehub-controller-detection-") as temp_root:
        raw = "\n".join(
            [
                'N: Name="Xbox Wireless Controller"',
                "H: Handlers=kbd event18 js0",
                "",
            ]
        )
        proc_path = temp_root / "input-devices.txt"
        proc_path.write_text(raw, encoding="utf-8")
        monkeypatch.setattr(controller_detection.sys, "platform", "linux")
        monkeypatch.setattr(controller_detection, "_PROC_INPUT_DEVICES_PATH", proc_path)

        devices = detect_xbox_controllers(max_devices=2)

        assert devices == [XboxController(slot=0, name="Xbox Wireless Controller", subtype=None)]


class _Callable:
    def __init__(self, func):
        self.func = func
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.func(*args)


def test_detect_xbox_controllers_windows_uses_xinput_slots_and_subtypes(monkeypatch) -> None:
    def fake_get_state(slot, state_ptr):
        del state_ptr
        slot_index = int(slot)
        return 0 if slot_index in {0, 2} else 1167

    def fake_get_capabilities(slot, flags, caps_ptr):
        del flags
        slot_index = int(slot)
        if slot_index not in {0, 2}:
            return 1167
        caps_ptr.contents.SubType = 7 + slot_index
        return 0

    fake_dll = type("FakeDll", (), {})()
    fake_dll.XInputGetState = _Callable(fake_get_state)
    fake_dll.XInputGetCapabilities = _Callable(fake_get_capabilities)

    monkeypatch.setattr(controller_detection.sys, "platform", "win32")
    monkeypatch.setattr(controller_detection, "_load_xinput_dll", lambda: fake_dll)

    devices = detect_xbox_controllers(max_devices=2)

    assert devices == [
        XboxController(slot=0, name="XInput/0", subtype=7),
        XboxController(slot=2, name="XInput/2", subtype=9),
    ]


@contextmanager
def _workspace_tempdir(prefix: str):
    temp_root = Path(".pytest_tmp_local") / f"{prefix}{uuid4().hex}"
    temp_root.mkdir(parents=True, exist_ok=False)
    try:
        yield temp_root
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
