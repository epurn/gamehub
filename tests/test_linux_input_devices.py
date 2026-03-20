from __future__ import annotations

from gamehub_cli.controllers import linux_input_devices


def test_parse_linux_input_device_records_captures_mixed_js_and_event_handlers() -> None:
    raw = "\n".join(
        [
            'N: Name="Xbox Wireless Controller"',
            "H: Handlers=kbd event18 js1 event19 js0",
            "",
            'N: Name="Steam Deck Motion Sensors"',
            "H: Handlers=event16 js2",
            "",
        ]
    )

    records = linux_input_devices.parse_linux_input_device_records(raw)

    assert records == [
        linux_input_devices.LinuxInputDeviceRecord(
            name="Xbox Wireless Controller",
            js_indices=(0, 1),
            event_indices=(18, 19),
        ),
        linux_input_devices.LinuxInputDeviceRecord(
            name="Steam Deck Motion Sensors",
            js_indices=(2,),
            event_indices=(16,),
        ),
    ]


def test_parse_linux_input_device_records_skips_incomplete_sections() -> None:
    raw = "\n".join(
        [
            'N: Name="Missing Handlers"',
            "",
            "H: Handlers=js3 event30",
            "",
            'N: Name="Complete Controller"',
            "H: Handlers=js0 event20",
            "",
        ]
    )

    records = linux_input_devices.parse_linux_input_device_records(raw)

    assert records == [
        linux_input_devices.LinuxInputDeviceRecord(
            name="Complete Controller",
            js_indices=(0,),
            event_indices=(20,),
        )
    ]


def test_js_device_index_extracts_numeric_suffix() -> None:
    assert linux_input_devices.js_device_index("/dev/input/js12") == 12
    assert linux_input_devices.js_device_index("js3") == 3
    assert linux_input_devices.js_device_index("/dev/input/event5") is None
