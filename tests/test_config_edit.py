from __future__ import annotations

from gamehub_cli.common.config_edit import (
    parse_qsettings_pairs,
    read_qsettings_key,
    read_simple_cfg_key,
    upsert_qsettings_key,
    upsert_simple_cfg_key,
)


def test_read_simple_cfg_key_trims_inline_comments() -> None:
    lines = [
        "# comment",
        'input_menu_toggle_gamepad_combo = "4" # inline',
        "other = value",
    ]

    value = read_simple_cfg_key(lines, "input_menu_toggle_gamepad_combo")

    assert value == "4"


def test_upsert_simple_cfg_key_rewrites_in_managed_format() -> None:
    lines = [
        "[Section]",
        'input_menu_toggle_gamepad_combo = "0"',
    ]

    updated, changed = upsert_simple_cfg_key(lines, "input_menu_toggle_gamepad_combo", "4")

    assert changed is True
    assert 'input_menu_toggle_gamepad_combo = "4"' in updated


def test_upsert_qsettings_key_updates_and_appends() -> None:
    lines = [
        "[Controls]",
        "fullscreen=false",
    ]

    updated, changed = upsert_qsettings_key(lines, "confirmClose", "false")

    assert changed is True
    assert updated[-1] == "confirmClose=false"


def test_parse_qsettings_pairs_skips_sections_and_comments() -> None:
    lines = [
        "; comment",
        "[Controls]",
        "fullscreen=true",
        "confirmClose=false",
    ]

    pairs = parse_qsettings_pairs(lines)

    assert pairs == {"fullscreen": "true", "confirmClose": "false"}


def test_read_qsettings_key_returns_exact_value() -> None:
    lines = [
        "[Controls]",
        'profiles\\1\\button_a="button:0,engine:sdl,port:0"',
    ]

    value = read_qsettings_key(lines, r"profiles\1\button_a")

    assert value == '"button:0,engine:sdl,port:0"'
