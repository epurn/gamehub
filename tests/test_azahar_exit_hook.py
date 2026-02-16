from __future__ import annotations

from gamehub_cli import azahar_exit_hook


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


def test_resolve_select_and_start_buttons_prefers_qt_config_when_env_unset(monkeypatch) -> None:
    monkeypatch.delenv("GAMEHUB_AZAHAR_EXIT_BUTTON_SELECT", raising=False)
    monkeypatch.delenv("GAMEHUB_AZAHAR_EXIT_BUTTON_START", raising=False)
    monkeypatch.setattr(azahar_exit_hook, "_resolve_button_pair_from_config", lambda: (7, 9))

    select_button, start_button = azahar_exit_hook._resolve_select_and_start_buttons()

    assert select_button == 7
    assert start_button == 9
