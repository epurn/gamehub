from __future__ import annotations

import json
from types import SimpleNamespace

from gamehub_cli.controllers import detection as controller_detection
from gamehub_cli.controllers import sdl_guid as controller_sdl_guid
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
            SimpleNamespace(slot=0, name="Generic USB Joystick", guid="a" * 32, is_game_controller=False),
            SimpleNamespace(slot=1, name="Motion Sensors", guid="b" * 32, is_game_controller=True),
            SimpleNamespace(slot=2, name="Wireless Controller", guid="c" * 32, is_game_controller=True),
            SimpleNamespace(slot=3, name="XInput Controller", guid="d" * 32, is_game_controller=True),
        ]

    monkeypatch.setattr(controller_detection.sys, "platform", "darwin")
    monkeypatch.setattr(controller_detection, "_discover_host_sdl_joysticks", _fake_probe)

    devices = detect_xbox_controllers(max_devices=2)

    assert observed["max_devices"] is None
    assert devices == [
        XboxController(slot=2, name="Wireless Controller", subtype=None, guid="c" * 32),
        XboxController(slot=3, name="XInput Controller", subtype=None, guid="d" * 32),
    ]


def test_detect_xbox_controllers_macos_failure_returns_empty(monkeypatch) -> None:
    def _raise(*, max_devices: int | None = None):
        del max_devices
        raise RuntimeError("SDL unavailable")

    monkeypatch.setattr(controller_detection.sys, "platform", "darwin")
    monkeypatch.setattr(controller_detection, "_discover_host_sdl_joysticks", _raise)

    assert detect_xbox_controllers(max_devices=2) == []


def test_parse_macos_system_profiler_game_controllers_collects_leaf_devices() -> None:
    payload = json.dumps(
        {
            "SPGameControllerDataType": [
                {
                    "_name": "Game Controllers",
                    "_items": [
                        {"_name": "Wireless Controller", "spgamecontroller_connected": "yes"},
                        {"_name": "Xbox Wireless Controller", "spgamecontroller_connected": "yes"},
                    ],
                }
            ]
        }
    )

    devices = controller_sdl_guid._parse_macos_system_profiler_game_controllers(payload, max_devices=2)

    assert [(device.slot, device.name, device.guid, device.is_game_controller) for device in devices] == [
        (0, "Wireless Controller", None, True),
        (1, "Xbox Wireless Controller", None, True),
    ]


def test_discover_host_sdl_joysticks_macos_falls_back_to_system_profiler(monkeypatch) -> None:
    observed: dict[str, int | None] = {}

    monkeypatch.setattr(controller_sdl_guid.sys, "platform", "darwin")
    monkeypatch.setattr(
        controller_sdl_guid,
        "_enumerate_sdl_joysticks",
        lambda candidates, *, max_devices=None: [],
    )

    def _fake_fallback(*, max_devices: int | None = None):
        observed["max_devices"] = max_devices
        return [SimpleNamespace(slot=0, name="Wireless Controller", guid=None, is_game_controller=True)]

    monkeypatch.setattr(controller_sdl_guid, "_discover_macos_system_profiler_joysticks", _fake_fallback)

    devices = controller_sdl_guid._discover_host_sdl_joysticks(max_devices=2)

    assert observed["max_devices"] == 2
    assert [(device.slot, device.name, device.guid, device.is_game_controller) for device in devices] == [
        (0, "Wireless Controller", None, True)
    ]


def test_parse_macos_hidutil_joysticks_filters_gamepads() -> None:
    payload = "\n".join(
        [
            "Devices:",
            "VendorID ProductID LocationID UsagePage Usage RegistryID  Transport            Class                      Product                            UserClass Built-In ",
            "0x45e    0xb13     0xfd98c044 1         5     0x100012061 Bluetooth Low Energy IOHIDUserDevice            Xbox Wireless Controller           (null)    0        ",
            "0x28de   0x1146    0x0        1         2     0x1000120f9 USB                  IOHIDUserDevice            Mouse-1                            (null)    0        ",
            "0x0      0x0       0x11d      1         6     0x100000c52 FIFO                 AppleHIDTransportHIDDevice Apple Internal Keyboard / Trackpad (null)    1        ",
        ]
    )

    devices = controller_sdl_guid._parse_macos_hidutil_joysticks(payload, max_devices=2)

    assert [
        (
            device.slot,
            device.name,
            device.guid,
            device.is_game_controller,
            device.vendor_id,
            device.product_id,
            device.transport,
        )
        for device in devices
    ] == [(0, "Xbox Wireless Controller", None, True, 0x045E, 0x0B13, "Bluetooth Low Energy")]


def test_discover_host_sdl_joysticks_macos_falls_back_to_hidutil(monkeypatch) -> None:
    observed: dict[str, int | None] = {}

    monkeypatch.setattr(controller_sdl_guid.sys, "platform", "darwin")
    monkeypatch.setattr(
        controller_sdl_guid,
        "_enumerate_sdl_joysticks",
        lambda candidates, *, max_devices=None: [],
    )
    monkeypatch.setattr(
        controller_sdl_guid,
        "_discover_macos_system_profiler_joysticks",
        lambda *, max_devices=None: [],
    )

    def _fake_hidutil(*, max_devices: int | None = None):
        observed["max_devices"] = max_devices
        return [SimpleNamespace(slot=0, name="Xbox Wireless Controller", guid=None, is_game_controller=True)]

    monkeypatch.setattr(controller_sdl_guid, "_discover_macos_hidutil_joysticks", _fake_hidutil)

    devices = controller_sdl_guid._discover_host_sdl_joysticks(max_devices=2)

    assert observed["max_devices"] == 2
    assert [(device.slot, device.name, device.guid, device.is_game_controller) for device in devices] == [
        (0, "Xbox Wireless Controller", None, True)
    ]


def test_select_macos_embedded_sdl_mapping_prefers_nearest_named_vendor_match() -> None:
    mappings = [
        controller_sdl_guid._SDLControllerMapping(
            guid="030000005e040000e002000003090000",
            name="Xbox Wireless Controller",
            vendor_id=0x045E,
            product_id=0x02E0,
            version=0x0903,
            fields={"back": "b6", "start": "b7"},
        ),
        controller_sdl_guid._SDLControllerMapping(
            guid="030000005e040000200b000011050000",
            name="Xbox Wireless Controller",
            vendor_id=0x045E,
            product_id=0x0B20,
            version=0x0511,
            fields={"back": "b10", "start": "b11"},
        ),
        controller_sdl_guid._SDLControllerMapping(
            guid="030000005e040000fd02000003090000",
            name="Xbox Wireless Controller",
            vendor_id=0x045E,
            product_id=0x02FD,
            version=0x0903,
            fields={"back": "b16", "start": "b11"},
        ),
    ]

    selected = controller_sdl_guid._select_macos_embedded_sdl_mapping(
        mappings,
        name="Xbox Wireless Controller",
        vendor_id=0x045E,
        product_id=0x0B13,
    )

    assert selected is not None
    assert selected.guid == "030000005e040000200b000011050000"


def test_select_macos_embedded_sdl_mapping_prefers_exact_vendor_product_over_host_name() -> None:
    mappings = [
        controller_sdl_guid._SDLControllerMapping(
            guid="030000005e040000200b000011050000",
            name="Xbox Wireless Controller",
            vendor_id=0x045E,
            product_id=0x0B20,
            version=0x0511,
            fields={"back": "b10", "start": "b11"},
        ),
        controller_sdl_guid._SDLControllerMapping(
            guid="030000005e040000130b0000ff870000",
            name="Xbox Series X Controller",
            vendor_id=0x045E,
            product_id=0x0B13,
            version=0x87FF,
            fields={"back": "b10", "start": "b11"},
        ),
    ]

    selected = controller_sdl_guid._select_macos_embedded_sdl_mapping(
        mappings,
        name="Xbox Wireless Controller",
        vendor_id=0x045E,
        product_id=0x0B13,
    )

    assert selected is not None
    assert selected.guid == "030000005e040000130b0000ff870000"
    assert selected.name == "Xbox Series X Controller"


def test_discover_host_sdl_guid_macos_uses_embedded_mapping_when_probe_is_guidless(monkeypatch) -> None:
    monkeypatch.setattr(controller_sdl_guid.sys, "platform", "darwin")
    monkeypatch.setattr(
        controller_sdl_guid,
        "_discover_host_sdl_joysticks",
        lambda *, max_devices=None: [
            SimpleNamespace(
                slot=0,
                name="Xbox Wireless Controller",
                guid=None,
                is_game_controller=True,
                vendor_id=0x045E,
                product_id=0x0B13,
            )
        ],
    )
    monkeypatch.setattr(
        controller_sdl_guid,
        "_lookup_macos_embedded_sdl_guid_for_identity",
        lambda *, name, vendor_id=None, product_id=None: "030000005e040000200b000011050000",
    )

    guid = controller_sdl_guid._discover_host_sdl_guid(port=0)

    assert guid == "030000005e040000200b000011050000"


def test_lookup_macos_embedded_sdl_mapping_for_port_uses_discovered_identity(monkeypatch) -> None:
    selected_mapping = controller_sdl_guid._SDLControllerMapping(
        guid="030000005e040000200b000011050000",
        name="Xbox Wireless Controller",
        vendor_id=0x045E,
        product_id=0x0B20,
        version=0x0511,
        fields={"back": "b10", "start": "b11"},
    )

    monkeypatch.setattr(controller_sdl_guid.sys, "platform", "darwin")
    monkeypatch.setattr(
        controller_sdl_guid,
        "_discover_host_sdl_joysticks",
        lambda *, max_devices=None: [
            SimpleNamespace(
                slot=0,
                name="Xbox Wireless Controller",
                guid=None,
                is_game_controller=True,
                vendor_id=0x045E,
                product_id=0x0B13,
            )
        ],
    )
    monkeypatch.setattr(
        controller_sdl_guid,
        "_lookup_macos_embedded_sdl_mapping_for_identity",
        lambda *, name, vendor_id=None, product_id=None: selected_mapping,
    )

    mapping = controller_sdl_guid._lookup_macos_embedded_sdl_mapping_for_port(port=0)

    assert mapping == selected_mapping
