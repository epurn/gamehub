from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..common.config import GamehubConfig
from .pcsx2_ini import read_ini_lines, upsert_ini_key, write_ini_atomic
from .targets import resolve_dolphin_config_dirs, resolve_dolphin_runtime_user_dir


def default_dolphin_ini_path(config: GamehubConfig | None = None) -> Path:
    return resolve_dolphin_runtime_user_dir(config=config) / "Config" / "Dolphin.ini"


def configure_dolphin_runtime(
    config: GamehubConfig,
    dry_run: bool,
    verbose: bool,
    writer: Callable[[str], None],
) -> Path:
    runtime_user_dir = resolve_dolphin_runtime_user_dir(config=config)
    ini_paths = [default_dolphin_ini_path(config=config)]
    extra_ini_paths = [path / "Config" / "Dolphin.ini" for path in resolve_dolphin_config_dirs(config=config)]
    for candidate in extra_ini_paths:
        if candidate not in ini_paths:
            ini_paths.append(candidate)
    if dry_run:
        if verbose:
            for ini_path in ini_paths:
                writer(
                    f"dolphin\tdry-run\tconfigure\t{ini_path}\t"
                    "fullscreen=true\tconfirm_stop=false\tbackground_input=true"
                )
        return runtime_user_dir / "Config" / "Dolphin.ini"

    for ini_path in ini_paths:
        lines = read_ini_lines(ini_path)
        lines, changed_fullscreen = upsert_ini_key(lines, "Display", "Fullscreen", "True")
        lines, changed_confirm_stop = upsert_ini_key(lines, "Interface", "ConfirmStop", "False")
        lines, changed_background_input = upsert_ini_key(lines, "Interface", "BackgroundInput", "True")
        if changed_fullscreen or changed_confirm_stop or changed_background_input or not ini_path.exists():
            write_ini_atomic(ini_path, lines)

        if verbose:
            writer(f"dolphin\tconfigured\t{ini_path}\tfullscreen=true\tconfirm_stop=false\tbackground_input=true")
    return runtime_user_dir / "Config" / "Dolphin.ini"
