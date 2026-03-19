from __future__ import annotations

import plistlib
from types import SimpleNamespace

import pytest

from gamehub_cli.controllers import azahar_exit_hook
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


def test_handle_js_event_detects_select_start_combo() -> None:
    pressed: set[int] = set()
    triggered = azahar_exit_hook._handle_js_event(
        pressed,
        event_type=0x01,
        event_value=1,
        button_index=4,
        select_button=4,
        start_button=6,
    )
    assert triggered is False
    triggered = azahar_exit_hook._handle_js_event(
        pressed,
        event_type=0x01,
        event_value=1,
        button_index=6,
        select_button=4,
        start_button=6,
    )
    assert triggered is True


def test_handle_js_event_ignores_non_button_events() -> None:
    pressed: set[int] = set()
    triggered = azahar_exit_hook._handle_js_event(
        pressed,
        event_type=0x02,
        event_value=1,
        button_index=6,
        select_button=4,
        start_button=6,
    )
    assert triggered is False
    assert pressed == set()


def test_handle_ev_key_event_detects_btn_select_start_combo() -> None:
    pressed: set[int] = set()
    triggered = azahar_exit_hook._handle_ev_key_event(
        pressed,
        event_type=0x01,
        code=0x13A,
        value=1,
    )
    assert triggered is False
    triggered = azahar_exit_hook._handle_ev_key_event(
        pressed,
        event_type=0x01,
        code=0x13B,
        value=1,
    )
    assert triggered is True


def test_handle_ev_key_event_ignores_other_keys() -> None:
    pressed: set[int] = set()
    triggered = azahar_exit_hook._handle_ev_key_event(
        pressed,
        event_type=0x01,
        code=0x130,
        value=1,
    )
    assert triggered is False
    assert pressed == set()


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
    primary_down = azahar_exit_hook._apply_azahar_mouse_bridge_state(
        azahar_exit_hook._AzaharMouseBridgeState(stick_x=1.0, stick_y=1.0, primary_down=True),
        primary_down=False,
        emitter=emitter,
    )
    primary_down = azahar_exit_hook._apply_azahar_mouse_bridge_state(
        azahar_exit_hook._AzaharMouseBridgeState(stick_x=0.0, stick_y=0.0, primary_down=True),
        primary_down=primary_down,
        emitter=emitter,
    )
    primary_down = azahar_exit_hook._apply_azahar_mouse_bridge_state(
        azahar_exit_hook._AzaharMouseBridgeState(stick_x=0.0, stick_y=0.0, primary_down=False),
        primary_down=primary_down,
        emitter=emitter,
    )

    assert primary_down is False
    assert events == [("move", 24, -24), ("down",), ("up",)]


def test_create_azahar_mouse_bridge_poller_linux_disables_on_steam_deck_before_capability_probe(monkeypatch) -> None:
    monkeypatch.setattr(azahar_exit_hook.sys, "platform", "linux")
    monkeypatch.setattr(azahar_exit_hook, "is_steam_deck_linux", lambda: True)
    monkeypatch.setattr(
        azahar_exit_hook,
        "_load_linux_evdev",
        lambda: (_ for _ in ()).throw(AssertionError("linux capability probing should be skipped on Steam Deck")),
    )

    with pytest.raises(azahar_exit_hook.AzaharMouseBridgeUnavailable, match="Steam Deck hosts"):
        azahar_exit_hook._create_azahar_mouse_bridge_poller(
            XboxController(slot=0, name="Xbox Wireless Controller", subtype=None)
        )


def test_create_azahar_mouse_bridge_poller_linux_uses_evdev_uinput_backend(monkeypatch) -> None:
    monkeypatch.setattr(azahar_exit_hook.sys, "platform", "linux")
    monkeypatch.setattr(azahar_exit_hook, "is_steam_deck_linux", lambda: False)
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
    monkeypatch.setattr(azahar_exit_hook, "_load_linux_evdev", lambda: evdev_module)
    monkeypatch.setattr(
        azahar_exit_hook, "_linux_event_device_path_for_controller", lambda controller: "/dev/input/event5"
    )

    poll_state, emitter = azahar_exit_hook._create_azahar_mouse_bridge_poller(
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
    monkeypatch.setattr(azahar_exit_hook.sys, "platform", "linux")
    monkeypatch.setattr(azahar_exit_hook, "is_steam_deck_linux", lambda: False)
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
    monkeypatch.setattr(azahar_exit_hook, "_load_linux_evdev", lambda: evdev_module)
    monkeypatch.setattr(
        azahar_exit_hook, "_linux_event_device_path_for_controller", lambda controller: "/dev/input/event7"
    )

    poll_state, _emitter = azahar_exit_hook._create_azahar_mouse_bridge_poller(
        XboxController(slot=1, name="Xbox Wireless Controller", subtype=None)
    )

    first = poll_state()
    second = poll_state()

    assert first is not None and first.primary_down is True
    assert second is not None and second.primary_down is False


def test_launch_azahar_flatpak_linux_mouse_bridge_coexists_with_exit_hook(monkeypatch) -> None:
    observed: dict[str, object] = {}

    class _Process:
        def poll(self):
            return 0

    class _Thread:
        def __init__(self, *, target=None, args=(), kwargs=None, daemon=None):
            observed["thread_target"] = target
            observed["thread_args"] = args
            observed["thread_kwargs"] = kwargs or {}
            observed["thread_daemon"] = daemon

        def start(self) -> None:
            observed["thread_started"] = True

    monkeypatch.setattr(azahar_exit_hook.sys, "platform", "linux")
    monkeypatch.setattr(
        azahar_exit_hook.subprocess,
        "Popen",
        lambda command, stdin=None: observed.update({"command": command, "stdin": stdin}) or _Process(),
    )
    monkeypatch.setattr(
        azahar_exit_hook,
        "_detect_azahar_mouse_bridge_controller",
        lambda: XboxController(slot=0, name="Xbox Wireless Controller", subtype=None),
    )
    monkeypatch.setattr(
        azahar_exit_hook,
        "_start_azahar_mouse_bridge",
        lambda process, *, controller, app_id=None: observed.update(
            {"bridge_process": process, "bridge_controller": controller, "bridge_app_id": app_id}
        ),
    )
    monkeypatch.setattr(azahar_exit_hook, "_resolve_select_and_start_buttons", lambda: (4, 6))
    monkeypatch.setattr(azahar_exit_hook, "_discover_js_devices", lambda: ["/dev/input/js0"])
    monkeypatch.setattr(azahar_exit_hook, "_wait_for_session_exit", lambda process, app_id: 0)
    monkeypatch.setattr(azahar_exit_hook.threading, "Thread", _Thread)

    exit_code = azahar_exit_hook._launch_azahar_flatpak(
        rom="/var/home/deck/GameHub/roms/N3DS/Pilotwings Resort.3ds",
        app_id="org.azahar_emu.Azahar",
    )

    assert exit_code == 0
    assert observed["bridge_controller"] == XboxController(slot=0, name="Xbox Wireless Controller", subtype=None)
    assert observed["bridge_app_id"] == "org.azahar_emu.Azahar"
    assert observed["thread_target"] is azahar_exit_hook._monitor_combo_and_terminate
    assert observed["thread_started"] is True


def test_launch_azahar_flatpak_linux_mouse_bridge_failure_warns_and_continues(monkeypatch) -> None:
    warnings: list[str] = []

    class _Process:
        def poll(self):
            return 0

    class _Thread:
        def __init__(self, *, target=None, args=(), kwargs=None, daemon=None):
            del target, args, kwargs, daemon

        def start(self) -> None:
            return None

    monkeypatch.setattr(azahar_exit_hook.sys, "platform", "linux")
    monkeypatch.setattr(azahar_exit_hook.subprocess, "Popen", lambda command, stdin=None: _Process())
    monkeypatch.setattr(
        azahar_exit_hook,
        "_detect_azahar_mouse_bridge_controller",
        lambda: XboxController(slot=0, name="Xbox Wireless Controller", subtype=None),
    )
    monkeypatch.setattr(
        azahar_exit_hook,
        "_start_azahar_mouse_bridge",
        lambda process, *, controller, app_id=None: (_ for _ in ()).throw(
            azahar_exit_hook.AzaharMouseBridgeUnavailable("permission denied opening /dev/uinput")
        ),
    )
    monkeypatch.setattr(azahar_exit_hook, "_warn_azahar_runtime", lambda message: warnings.append(message))
    monkeypatch.setattr(azahar_exit_hook, "_resolve_select_and_start_buttons", lambda: (4, 6))
    monkeypatch.setattr(azahar_exit_hook, "_discover_js_devices", lambda: [])
    monkeypatch.setattr(azahar_exit_hook, "_wait_for_session_exit", lambda process, app_id: 0)
    monkeypatch.setattr(azahar_exit_hook.threading, "Thread", _Thread)

    exit_code = azahar_exit_hook._launch_azahar_flatpak(rom="/tmp/game.3ds", app_id="org.azahar_emu.Azahar")

    assert exit_code == 0
    assert warnings == [
        "Azahar mouse bridge unavailable (error=permission denied opening /dev/uinput); continuing without synthetic mouse input"
    ]


def test_resolve_select_and_start_buttons_prefers_qt_config_when_env_unset(monkeypatch) -> None:
    monkeypatch.delenv("GAMEHUB_AZAHAR_EXIT_BUTTON_SELECT", raising=False)
    monkeypatch.delenv("GAMEHUB_AZAHAR_EXIT_BUTTON_START", raising=False)
    monkeypatch.setattr(azahar_exit_hook, "_resolve_button_pair_from_config", lambda: (7, 9))

    select_button, start_button = azahar_exit_hook._resolve_select_and_start_buttons()

    assert select_button == 7
    assert start_button == 9


def test_resolve_macos_button_selectors_from_embedded_mapping(monkeypatch) -> None:
    monkeypatch.setattr(azahar_exit_hook.sys, "platform", "darwin")
    monkeypatch.setattr(
        azahar_exit_hook,
        "_lookup_macos_embedded_sdl_mapping_for_port",
        lambda port: azahar_exit_hook._SDLControllerMapping(
            guid="050000005e040000130b0000ff870001",
            name="Xbox Series X Controller",
            vendor_id=0x045E,
            product_id=0x0B13,
            version=0x87FF,
            fields={
                "back": "b8",
                "start": "b10",
                "guide": "b9",
                "leftshoulder": "b4",
                "rightshoulder": "b5",
            },
        ),
    )

    selectors = azahar_exit_hook._resolve_macos_button_selectors(port=0, select_button=8, start_button=10)

    assert selectors == ("buttonOptions", "buttonMenu")


def test_capture_macos_xbox_event_log_parses_hidutil_dump(monkeypatch) -> None:
    monkeypatch.setattr(azahar_exit_hook.sys, "platform", "darwin")
    payload = {
        "ServiceRecords": [
            {
                "ServicePluginDebug": {"PluginName": "OtherPlugin"},
                "IORegistryEntryID": 7,
                "EventLog": [{"EventType": 3, "UsagePage": 12, "Usage": 999, "Down": 1}],
            },
            {
                "ServicePluginDebug": {"PluginName": "XboxOneHIDServicePlugin"},
                "IORegistryEntryID": 42,
                "PrimaryUsagePage": 1,
                "PrimaryUsage": 5,
                "EventLog": [
                    {"EventType": 3, "UsagePage": 12, "Usage": 521, "Down": 1},
                    "ignored",
                ],
            },
        ]
    }
    monkeypatch.setattr(
        azahar_exit_hook.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=plistlib.dumps(payload)),
    )

    snapshot = azahar_exit_hook._capture_macos_xbox_event_log()

    assert snapshot == (
        42,
        [{"EventType": 3, "UsagePage": 12, "Usage": 521, "Down": 1}],
    )


def test_macos_pressed_consumer_usages_from_event_log_tracks_button_state() -> None:
    event_log = [
        {"EventTime": "1", "EventType": 3, "UsagePage": 12, "Usage": 521, "Down": 1},
        {"EventTime": "2", "EventType": 3, "UsagePage": 12, "Usage": 516, "Down": 1},
        {"EventTime": "3", "EventType": 3, "UsagePage": 12, "Usage": 521, "Down": 0},
        {"EventTime": "4", "EventType": 35},
    ]

    pressed = azahar_exit_hook._macos_pressed_consumer_usages_from_event_log(event_log)

    assert pressed == {516}


def test_monitor_macos_combo_and_terminate_quits_on_hidutil_consumer_combo(monkeypatch) -> None:
    class _Proc:
        exited = False

        def poll(self):
            return 0 if self.exited else None

    process = _Proc()
    snapshots = iter(
        [
            (42, [{"EventTime": "1", "EventType": 3, "UsagePage": 12, "Usage": 521, "Down": 1}]),
            (
                42,
                [
                    {"EventTime": "1", "EventType": 3, "UsagePage": 12, "Usage": 521, "Down": 1},
                    {"EventTime": "2", "EventType": 3, "UsagePage": 12, "Usage": 516, "Down": 1},
                ],
            ),
        ]
    )
    quit_calls: list[str | None] = []

    monkeypatch.setattr(azahar_exit_hook, "_resolve_macos_button_selectors", lambda **kwargs: None)
    monkeypatch.setattr(azahar_exit_hook, "_capture_macos_xbox_event_log", lambda: next(snapshots))
    monkeypatch.setattr(azahar_exit_hook.time, "sleep", lambda *_args, **_kwargs: None)

    def _quit(*, bundle_id: str | None) -> None:
        quit_calls.append(bundle_id)
        process.exited = True

    monkeypatch.setattr(azahar_exit_hook, "_request_macos_application_quit", _quit)

    def _fail_terminate_named_processes(**kwargs) -> None:
        raise AssertionError("process termination fallback should not run")

    monkeypatch.setattr(azahar_exit_hook, "_terminate_named_processes", _fail_terminate_named_processes)

    azahar_exit_hook._monitor_macos_combo_and_terminate(
        process,
        select_button=8,
        start_button=10,
        controller_port=0,
        bundle_id="org.azahar-emu.azahar",
        process_name="azahar",
        prelaunch_pids={101},
    )

    assert quit_calls == ["org.azahar-emu.azahar"]


def test_monitor_macos_combo_and_terminate_prefers_selector_polling_when_available(monkeypatch) -> None:
    class _Proc:
        exited = False

        def poll(self):
            return 0 if self.exited else None

    process = _Proc()
    quit_calls: list[str | None] = []
    selector_calls: list[tuple[int, str, str]] = []

    monkeypatch.setattr(
        azahar_exit_hook, "_resolve_macos_button_selectors", lambda **kwargs: ("buttonOptions", "buttonMenu")
    )

    def _combo_pressed(*, controller_port: int, select_selector: str, start_selector: str) -> bool | None:
        selector_calls.append((controller_port, select_selector, start_selector))
        return True

    monkeypatch.setattr(azahar_exit_hook, "_macos_controller_combo_pressed", _combo_pressed)
    monkeypatch.setattr(
        azahar_exit_hook,
        "_capture_macos_xbox_event_log",
        lambda: (_ for _ in ()).throw(AssertionError("hidutil fallback should not run")),
    )
    monkeypatch.setattr(azahar_exit_hook.time, "sleep", lambda *_args, **_kwargs: None)

    def _quit(*, bundle_id: str | None) -> None:
        quit_calls.append(bundle_id)
        process.exited = True

    monkeypatch.setattr(azahar_exit_hook, "_request_macos_application_quit", _quit)

    def _fail_terminate_named_processes(**kwargs) -> None:
        raise AssertionError("process termination fallback should not run")

    monkeypatch.setattr(azahar_exit_hook, "_terminate_named_processes", _fail_terminate_named_processes)

    azahar_exit_hook._monitor_macos_combo_and_terminate(
        process,
        select_button=8,
        start_button=10,
        controller_port=1,
        bundle_id="org.azahar-emu.azahar",
        process_name="azahar",
        prelaunch_pids={101},
    )

    assert selector_calls == [(1, "buttonOptions", "buttonMenu")]
    assert quit_calls == ["org.azahar-emu.azahar"]


def test_terminate_named_processes_skips_prelaunch_only_matches(monkeypatch) -> None:
    kill_calls: list[tuple[int, int]] = []

    monkeypatch.setattr(azahar_exit_hook, "_discover_process_ids_by_name", lambda process_name: {101, 102})
    monkeypatch.setattr(azahar_exit_hook.os, "kill", lambda pid, sig: kill_calls.append((pid, sig)))

    azahar_exit_hook._terminate_named_processes(
        process_name="azahar",
        prelaunch_pids={101, 102},
        sig=15,
    )

    assert kill_calls == []


def test_resolve_macos_bundle_identifier_reads_info_plist(monkeypatch, workspace_tempdir) -> None:
    with workspace_tempdir("gamehub-azahar-bundle-id-") as temp_root:
        monkeypatch.setattr(azahar_exit_hook.sys, "platform", "darwin")
        bundle = temp_root / "Azahar.app"
        info_plist = bundle / "Contents" / "Info.plist"
        info_plist.parent.mkdir(parents=True, exist_ok=True)
        info_plist.write_bytes(plistlib.dumps({"CFBundleIdentifier": "org.azahar-emu.azahar"}))

        bundle_id = azahar_exit_hook._resolve_macos_bundle_identifier(str(bundle))

        assert bundle_id == "org.azahar-emu.azahar"


def test_is_flatpak_app_running_parses_application_column(monkeypatch) -> None:
    monkeypatch.setattr(
        azahar_exit_hook.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="Application\norg.azahar_emu.Azahar\n",
        ),
    )
    assert azahar_exit_hook._is_flatpak_app_running("org.azahar_emu.Azahar") is True


def test_session_active_checks_flatpak_when_process_exited(monkeypatch) -> None:
    class _Proc:
        def poll(self):
            return 0

    monkeypatch.setattr(azahar_exit_hook, "_is_flatpak_app_running", lambda app_id: True)
    assert azahar_exit_hook._session_active(_Proc(), "org.azahar_emu.Azahar") is True
