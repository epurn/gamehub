from __future__ import annotations

from gamehub_cli.azahar_exit_hook import _handle_js_event


def test_handle_js_event_detects_select_start_combo() -> None:
    pressed: set[int] = set()
    triggered = _handle_js_event(
        pressed,
        event_type=0x01,
        event_value=1,
        button_index=4,
        select_button=4,
        start_button=6,
    )
    assert triggered is False
    triggered = _handle_js_event(
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
    triggered = _handle_js_event(
        pressed,
        event_type=0x02,
        event_value=1,
        button_index=6,
        select_button=4,
        start_button=6,
    )
    assert triggered is False
    assert pressed == set()
