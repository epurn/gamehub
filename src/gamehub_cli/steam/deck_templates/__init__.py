from __future__ import annotations

from .roots import discover_deck_steam_input_roots, normalize_steam_input_title_dir
from .sync import TemplateSyncResult, apply_deck_steam_input_templates

__all__ = [
    "TemplateSyncResult",
    "apply_deck_steam_input_templates",
    "discover_deck_steam_input_roots",
    "normalize_steam_input_title_dir",
]
