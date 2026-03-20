from __future__ import annotations

import plistlib
from types import SimpleNamespace

from gamehub_cli.controllers import azahar_exit_hook
from gamehub_cli.controllers.detection import XboxController


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
        azahar_exit_hook.azahar_mouse_bridge,
        "detect_azahar_mouse_bridge_controller",
        lambda: XboxController(slot=0, name="Xbox Wireless Controller", subtype=None),
    )
    monkeypatch.setattr(
        azahar_exit_hook.azahar_mouse_bridge,
        "start_azahar_mouse_bridge",
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
        azahar_exit_hook.azahar_mouse_bridge,
        "detect_azahar_mouse_bridge_controller",
        lambda: XboxController(slot=0, name="Xbox Wireless Controller", subtype=None),
    )
    monkeypatch.setattr(
        azahar_exit_hook.azahar_mouse_bridge,
        "start_azahar_mouse_bridge",
        lambda process, *, controller, app_id=None: (_ for _ in ()).throw(
            azahar_exit_hook.azahar_mouse_bridge.AzaharMouseBridgeUnavailable("permission denied opening /dev/uinput")
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
