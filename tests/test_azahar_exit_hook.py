from __future__ import annotations

from types import SimpleNamespace

from gamehub_cli.controllers import azahar_exit_hook


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


def test_resolve_select_and_start_buttons_prefers_qt_config_when_env_unset(monkeypatch) -> None:
    monkeypatch.delenv("GAMEHUB_AZAHAR_EXIT_BUTTON_SELECT", raising=False)
    monkeypatch.delenv("GAMEHUB_AZAHAR_EXIT_BUTTON_START", raising=False)
    monkeypatch.setattr(azahar_exit_hook, "_resolve_button_pair_from_config", lambda: (7, 9))

    select_button, start_button = azahar_exit_hook._resolve_select_and_start_buttons()

    assert select_button == 7
    assert start_button == 9


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
