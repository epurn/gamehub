from __future__ import annotations

from types import SimpleNamespace

import pytest

from gamehub_cli.controllers import azahar_mouse_bridge
from gamehub_cli.controllers.detection import XboxController


class _FakeAbsInfo:
    def __init__(self, *, value: int, minimum: int, maximum: int) -> None:
        self.value = value
        self.min = minimum
        self.max = maximum


class _FakeInputEvent:
    def __init__(self, *, event_type: int, code: int, value: int) -> None:
        self.type = event_type
        self.code = code
        self.value = value


def _fake_linux_evdev_module(
    *,
    abs_capabilities: dict[int, _FakeAbsInfo],
    key_capabilities: tuple[int, ...] = (),
    read_batches: tuple[tuple[_FakeInputEvent, ...], ...] = (),
    uinput_error: BaseException | None = None,
):
    ecodes = SimpleNamespace(
        EV_ABS=3,
        EV_KEY=1,
        EV_REL=2,
        ABS_RX=3,
        ABS_RY=4,
        ABS_RZ=5,
        BTN_TR2=0x139,
        BTN_LEFT=0x110,
        REL_X=0,
        REL_Y=1,
    )
    created_devices: list[object] = []
    created_uinputs: list[object] = []

    class _InputDevice:
        def __init__(self, path: str) -> None:
            self.path = path
            self.blocking: bool | None = None
            self.closed = False
            self._batches = [list(batch) for batch in read_batches]
            created_devices.append(self)

        def capabilities(self, *, absinfo: bool = False) -> dict[int, list[object]]:
            del absinfo
            return {
                ecodes.EV_ABS: list(abs_capabilities.items()),
                ecodes.EV_KEY: list(key_capabilities),
            }

        def set_blocking(self, value: bool) -> None:
            self.blocking = value

        def read(self) -> list[_FakeInputEvent]:
            if not self._batches:
                raise BlockingIOError()
            return self._batches.pop(0)

        def close(self) -> None:
            self.closed = True

    class _UInput:
        def __init__(self, capabilities: dict[int, list[int]], *, name: str) -> None:
            if uinput_error is not None:
                raise uinput_error
            self.capabilities = capabilities
            self.name = name
            self.events: list[tuple[object, ...]] = []
            created_uinputs.append(self)

        def write(self, event_type: int, code: int, value: int) -> None:
            self.events.append(("write", event_type, code, value))

        def syn(self) -> None:
            self.events.append(("syn",))

        def close(self) -> None:
            self.events.append(("close",))

    return SimpleNamespace(ecodes=ecodes, InputDevice=_InputDevice, UInput=_UInput), created_devices, created_uinputs


def test_azahar_mouse_bridge_translates_right_stick_and_r2() -> None:
    events: list[tuple[object, ...]] = []

    class _Emitter:
        def move_relative(self, dx: int, dy: int) -> None:
            events.append(("move", dx, dy))

        def press_left(self) -> None:
            events.append(("down",))

        def release_left(self) -> None:
            events.append(("up",))

    emitter = _Emitter()
    primary_down = azahar_mouse_bridge._apply_azahar_mouse_bridge_state(
        azahar_mouse_bridge._AzaharMouseBridgeState(stick_x=1.0, stick_y=1.0, primary_down=True),
        primary_down=False,
        emitter=emitter,
    )
    primary_down = azahar_mouse_bridge._apply_azahar_mouse_bridge_state(
        azahar_mouse_bridge._AzaharMouseBridgeState(stick_x=0.0, stick_y=0.0, primary_down=True),
        primary_down=primary_down,
        emitter=emitter,
    )
    primary_down = azahar_mouse_bridge._apply_azahar_mouse_bridge_state(
        azahar_mouse_bridge._AzaharMouseBridgeState(stick_x=0.0, stick_y=0.0, primary_down=False),
        primary_down=primary_down,
        emitter=emitter,
    )

    assert primary_down is False
    assert events == [("move", 24, -24), ("down",), ("up",)]


def test_create_azahar_mouse_bridge_poller_linux_disables_on_steam_deck_before_capability_probe(monkeypatch) -> None:
    monkeypatch.setattr(azahar_mouse_bridge.sys, "platform", "linux")
    monkeypatch.setattr(azahar_mouse_bridge, "is_steam_deck_linux", lambda: True)
    monkeypatch.setattr(
        azahar_mouse_bridge,
        "_load_linux_evdev",
        lambda: (_ for _ in ()).throw(AssertionError("linux capability probing should be skipped on Steam Deck")),
    )

    with pytest.raises(azahar_mouse_bridge.AzaharMouseBridgeUnavailable, match="Steam Deck hosts"):
        azahar_mouse_bridge._create_azahar_mouse_bridge_poller(
            XboxController(slot=0, name="Xbox Wireless Controller", subtype=None)
        )


def test_create_azahar_mouse_bridge_poller_linux_uses_evdev_uinput_backend(monkeypatch) -> None:
    monkeypatch.setattr(azahar_mouse_bridge.sys, "platform", "linux")
    monkeypatch.setattr(azahar_mouse_bridge, "is_steam_deck_linux", lambda: False)
    evdev_module, created_devices, created_uinputs = _fake_linux_evdev_module(
        abs_capabilities={
            3: _FakeAbsInfo(value=512, minimum=0, maximum=1023),
            4: _FakeAbsInfo(value=512, minimum=0, maximum=1023),
            5: _FakeAbsInfo(value=0, minimum=0, maximum=255),
        },
        read_batches=(
            (
                _FakeInputEvent(event_type=3, code=3, value=1023),
                _FakeInputEvent(event_type=3, code=4, value=0),
                _FakeInputEvent(event_type=3, code=5, value=255),
            ),
        ),
    )
    monkeypatch.setattr(azahar_mouse_bridge, "_load_linux_evdev", lambda: evdev_module)
    monkeypatch.setattr(
        azahar_mouse_bridge, "_linux_event_device_path_for_controller", lambda controller: "/dev/input/event5"
    )

    poll_state, emitter = azahar_mouse_bridge._create_azahar_mouse_bridge_poller(
        XboxController(slot=0, name="Xbox Wireless Controller", subtype=None)
    )
    state = poll_state()
    assert state is not None
    assert state.stick_x > 0.95
    assert state.stick_y < -0.95
    assert state.primary_down is True

    emitter.move_relative(4, -3)
    emitter.press_left()
    emitter.release_left()
    emitter.close()

    assert len(created_devices) == 1
    assert getattr(created_devices[0], "blocking", None) is False
    assert len(created_uinputs) == 1
    assert created_uinputs[0].events == [
        ("write", 2, 0, 4),
        ("write", 2, 1, -3),
        ("syn",),
        ("write", 1, 272, 1),
        ("syn",),
        ("write", 1, 272, 0),
        ("syn",),
        ("close",),
    ]


def test_create_azahar_mouse_bridge_poller_linux_uses_btn_tr2_fallback_when_abs_rz_missing(monkeypatch) -> None:
    monkeypatch.setattr(azahar_mouse_bridge.sys, "platform", "linux")
    monkeypatch.setattr(azahar_mouse_bridge, "is_steam_deck_linux", lambda: False)
    evdev_module, _created_devices, _created_uinputs = _fake_linux_evdev_module(
        abs_capabilities={
            3: _FakeAbsInfo(value=512, minimum=0, maximum=1023),
            4: _FakeAbsInfo(value=512, minimum=0, maximum=1023),
        },
        key_capabilities=(0x139,),
        read_batches=(
            (_FakeInputEvent(event_type=1, code=0x139, value=1),),
            (_FakeInputEvent(event_type=1, code=0x139, value=0),),
        ),
    )
    monkeypatch.setattr(azahar_mouse_bridge, "_load_linux_evdev", lambda: evdev_module)
    monkeypatch.setattr(
        azahar_mouse_bridge, "_linux_event_device_path_for_controller", lambda controller: "/dev/input/event7"
    )

    poll_state, _emitter = azahar_mouse_bridge._create_azahar_mouse_bridge_poller(
        XboxController(slot=1, name="Xbox Wireless Controller", subtype=None)
    )

    first = poll_state()
    second = poll_state()

    assert first is not None and first.primary_down is True
    assert second is not None and second.primary_down is False
