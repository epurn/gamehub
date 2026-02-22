from __future__ import annotations

from .fsops import replace_file
from .paths import from_rel_path
from .platform_paths import (
    AZAHAR_FLATPAK_APP_ID,
    DOLPHIN_FLATPAK_APP_ID,
    PCSX2_FLATPAK_APP_ID,
    RETROARCH_FLATPAK_APP_ID,
    is_flatpak_command,
    parse_simple_kv_config,
    retroarch_cfg_candidates,
    unique_paths,
)

__all__ = [
    "AZAHAR_FLATPAK_APP_ID",
    "DOLPHIN_FLATPAK_APP_ID",
    "PCSX2_FLATPAK_APP_ID",
    "RETROARCH_FLATPAK_APP_ID",
    "from_rel_path",
    "is_flatpak_command",
    "parse_simple_kv_config",
    "replace_file",
    "retroarch_cfg_candidates",
    "unique_paths",
]
