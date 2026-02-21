from __future__ import annotations

from .deploy import deploy_firmware_to_emulators
from .retroarch_cores import ensure_retroarch_cores, resolve_retroarch_paths
from .targets import (
    default_pcsx2_ini_path,
    resolve_dolphin_config_dirs,
    resolve_dolphin_runtime_user_dir,
    resolve_pcsx2_bios_dirs,
    resolve_retroarch_system_dirs,
    target_dirs_for_system,
)

__all__ = [
    "default_pcsx2_ini_path",
    "deploy_firmware_to_emulators",
    "ensure_retroarch_cores",
    "resolve_dolphin_config_dirs",
    "resolve_dolphin_runtime_user_dir",
    "resolve_pcsx2_bios_dirs",
    "resolve_retroarch_paths",
    "resolve_retroarch_system_dirs",
    "target_dirs_for_system",
]
