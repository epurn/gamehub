from __future__ import annotations

from types import SimpleNamespace

from gamehub_cli.controllers import detection as controller_detection
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


def test_linux_parse_xbox_devices_accepts_xbox_hyphenated_name() -> None:
    raw = "\n".join(
        [
            'N: Name="Microsoft X-Box 360 pad"',
            "H: Handlers=js0 event20",
            "",
        ]
    )

    devices = controller_detection._linux_parse_xbox_devices(raw, max_devices=2)

    assert devices == [XboxController(slot=0, name="Microsoft X-Box 360 pad", subtype=None)]


def test_detect_xbox_controllers_linux_reads_proc_file(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-controller-detection-") as temp_root:
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

        monkeypatch.setattr(controller_detection, "_is_steam_deck_linux", lambda: False)
        devices = detect_xbox_controllers(max_devices=2)

        assert devices == [XboxController(slot=0, name="Xbox Wireless Controller", subtype=None)]


def test_linux_parse_xbox_devices_includes_steam_deck_controller_when_enabled() -> None:
    raw = "\n".join(
        [
            'N: Name="Steam Deck Controller"',
            "H: Handlers=js0 event10",
            "",
            'N: Name="Steam Virtual Gamepad"',
            "H: Handlers=js1 event11",
            "",
        ]
    )

    devices = controller_detection._linux_parse_xbox_devices(raw, max_devices=2, include_steam_deck=True)

    assert devices == [
        XboxController(slot=0, name="Steam Deck Controller", subtype=None),
        XboxController(slot=1, name="Steam Virtual Gamepad", subtype=None),
    ]


def test_linux_parse_xbox_devices_ignores_steam_deck_controller_when_disabled() -> None:
    raw = "\n".join(
        [
            'N: Name="Steam Deck Controller"',
            "H: Handlers=js0 event10",
            "",
        ]
    )

    devices = controller_detection._linux_parse_xbox_devices(raw, max_devices=2, include_steam_deck=False)

    assert devices == []


def test_linux_parse_xbox_devices_excludes_steam_deck_motion_sensors() -> None:
    raw = "\n".join(
        [
            'N: Name="Steam Deck"',
            "H: Handlers=event15 js0",
            "",
            'N: Name="Steam Deck Motion Sensors"',
            "H: Handlers=event16 js1",
            "",
        ]
    )

    devices = controller_detection._linux_parse_xbox_devices(raw, max_devices=2, include_steam_deck=True)

    assert devices == [XboxController(slot=0, name="Steam Deck", subtype=None)]


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


def test_detect_xbox_controllers_macos_uses_sdl_probe(monkeypatch) -> None:
    observed: dict[str, int | None] = {}

    def _fake_probe(*, max_devices: int | None = None):
        observed["max_devices"] = max_devices
        return [
            SimpleNamespace(slot=0, name="Generic USB Joystick", guid="a" * 32),
            SimpleNamespace(slot=1, name="Motion Sensors", guid="b" * 32),
            SimpleNamespace(slot=2, name="Xbox Wireless Controller", guid="c" * 32),
            SimpleNamespace(slot=3, name="XInput Controller", guid="d" * 32),
        ]

    monkeypatch.setattr(controller_detection.sys, "platform", "darwin")
    monkeypatch.setattr(controller_detection, "_discover_host_sdl_joysticks", _fake_probe)

    devices = detect_xbox_controllers(max_devices=2)

    assert observed["max_devices"] is None
    assert devices == [
        XboxController(slot=2, name="Xbox Wireless Controller", subtype=None),
        XboxController(slot=3, name="XInput Controller", subtype=None),
    ]


def test_detect_xbox_controllers_macos_failure_returns_empty(monkeypatch) -> None:
    def _raise(*, max_devices: int | None = None):
        del max_devices
        raise RuntimeError("SDL unavailable")

    monkeypatch.setattr(controller_detection.sys, "platform", "darwin")
    monkeypatch.setattr(controller_detection, "_discover_host_sdl_joysticks", _raise)

    assert detect_xbox_controllers(max_devices=2) == []
