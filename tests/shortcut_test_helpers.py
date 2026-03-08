from __future__ import annotations

import hashlib
from pathlib import Path

from gamehub_cli.common.config import ControllersConfig, GamehubConfig


def default_shortcut_config() -> GamehubConfig:
    return GamehubConfig(
        server_url="http://localhost:8000",
        library_dir=Path("D:/GameHub"),
        firmware_dir=Path("D:/GameHub/firmware"),
        state_path=Path("D:/GameHub/state.json"),
        steam_userdata_dir=None,
        steam_id=None,
        steam_exe=None,
        sgdb_api_key=None,
        sgdb_cache_dir=Path("D:/GameHub/cache"),
        sgdb_enabled_kinds=("grid", "hero", "logo", "icon"),
        controllers=ControllersConfig(launch_autoconfig=True),
    )


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
