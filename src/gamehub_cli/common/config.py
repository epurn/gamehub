from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_state_dir


@dataclass(frozen=True)
class LinuxConfig:
    emulator_install_backend: str | None = None
    emulator_install_command: str | None = None
    flatpak_remote: str | None = None
    retroarch_cfg_path: Path | None = None
    retroarch_system_dir: Path | None = None
    retroarch_cores_dir: Path | None = None
    retroarch_info_dir: Path | None = None
    retroarch_cores_base_url: str | None = None
    pcsx2_ini_path: Path | None = None
    pcsx2_bios_dir: Path | None = None
    dolphin_user_path: Path | None = None


@dataclass(frozen=True)
class MacOSConfig:
    emulator_install_backend: str | None = None
    emulator_install_command: str | None = None
    disable_pcsx2_rosetta: bool = False
    retroarch_cfg_path: Path | None = None
    retroarch_system_dir: Path | None = None
    retroarch_cores_dir: Path | None = None
    retroarch_info_dir: Path | None = None
    retroarch_cores_base_url: str | None = None
    pcsx2_ini_path: Path | None = None
    pcsx2_bios_dir: Path | None = None
    dolphin_user_path: Path | None = None


@dataclass(frozen=True)
class ControllersConfig:
    launch_autoconfig: bool = True
    profiles_dir: Path | None = None


@dataclass(frozen=True)
class SaveSyncConfig:
    enabled: bool = False
    mode: str = "download"
    conflict_policy: str = "prefer_server"
    systems: tuple[str, ...] = ()


@dataclass(frozen=True)
class BackupsConfig:
    keep_limit: int = 3


@dataclass(frozen=True)
class GamehubConfig:
    server_url: str
    library_dir: Path
    firmware_dir: Path
    state_path: Path
    steam_userdata_dir: Path | None
    steam_id: str | None
    steam_exe: Path | None
    sgdb_api_key: str | None
    sgdb_cache_dir: Path
    sgdb_enabled_kinds: tuple[str, ...]
    roms_dir: Path | None = None
    index_timeout_seconds: float | None = None
    index_fetch_attempts: int = 3
    index_retry_backoff_seconds: float = 1.5
    max_parallel_downloads: int = 4
    linux: LinuxConfig = field(default_factory=LinuxConfig)
    macos: MacOSConfig = field(default_factory=MacOSConfig)
    controllers: ControllersConfig = field(default_factory=ControllersConfig)
    save_sync: SaveSyncConfig = field(default_factory=SaveSyncConfig)
    config_path: Path | None = None
    backups: BackupsConfig = field(default_factory=BackupsConfig)


_VALID_SGDB_KINDS = ("grid", "hero", "logo", "icon")
_VALID_SAVE_SYNC_MODES = ("download", "bidirectional")
_VALID_SAVE_SYNC_CONFLICT_POLICIES = ("prefer_server", "prefer_local", "manual")
_REMOVED_PATH_KEYS = {
    "library_dir": "paths.gamehub_dir",
    "firmware_dir": "paths.gamehub_dir (firmware path is <gamehub_dir>/firmware)",
    "state_path": "paths.gamehub_dir (state path is <gamehub_dir>/state.json)",
    "output_dir": "paths.roms_dir",
}
_REMOVED_ENV_ALIASES = {
    "GAMEHUB_OUTPUT_DIR": "GAMEHUB_ROMS_DIR",
}


def default_config_path() -> Path:
    local_config = Path.cwd() / "config.toml"
    if local_config.exists():
        return local_config
    home_config = Path.home() / ".gamehub" / "config.toml"
    if home_config.exists():
        return home_config
    return home_config


def default_gamehub_dir() -> Path:
    return Path(user_state_dir("gamehub"))


def default_sgdb_cache_dir() -> Path:
    return Path(user_state_dir("gamehub")) / "artwork_cache" / "sgdb"


def _normalize_sgdb_kinds(raw: object) -> tuple[str, ...]:
    if raw is None:
        return _VALID_SGDB_KINDS
    if isinstance(raw, str):
        candidates = [raw]
    elif isinstance(raw, (list, tuple)):
        candidates = list(raw)
    else:
        return _VALID_SGDB_KINDS

    normalized: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        kind = candidate.strip().lower()
        if kind in _VALID_SGDB_KINDS and kind not in normalized:
            normalized.append(kind)
    return tuple(normalized) if normalized else _VALID_SGDB_KINDS


def _normalize_save_sync_mode(raw: object) -> str:
    if not isinstance(raw, str):
        return "download"
    value = raw.strip().lower().replace("-", "_")
    if value == "download_only":
        value = "download"
    return value if value in _VALID_SAVE_SYNC_MODES else "download"


def _normalize_save_sync_conflict_policy(raw: object) -> str:
    if not isinstance(raw, str):
        return "prefer_server"
    value = raw.strip().lower().replace("-", "_")
    return value if value in _VALID_SAVE_SYNC_CONFLICT_POLICIES else "prefer_server"


def _normalize_system_filter(raw: object) -> tuple[str, ...]:
    if isinstance(raw, str):
        candidates = [raw]
    elif isinstance(raw, (list, tuple)):
        candidates = list(raw)
    else:
        return ()
    normalized: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        value = candidate.strip()
        if not value:
            continue
        system = value.upper()
        if system not in normalized:
            normalized.append(system)
    return tuple(normalized)


def _load_save_sync_config(save_sync: dict[str, object]) -> SaveSyncConfig:
    enabled = _normalize_optional_bool(save_sync.get("enabled"))
    return SaveSyncConfig(
        enabled=enabled if enabled is not None else False,
        mode=_normalize_save_sync_mode(save_sync.get("mode")),
        conflict_policy=_normalize_save_sync_conflict_policy(save_sync.get("conflict_policy")),
        systems=_normalize_system_filter(save_sync.get("systems")),
    )


def _normalize_secret(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    return value or None


def _normalize_optional_path(raw: object) -> Path | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value:
        return None
    return Path(value).expanduser()


def _normalize_optional_text(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    return value or None


def _normalize_optional_float(raw: object, *, minimum: float = 0.0) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if not isinstance(raw, (int, float, str)):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < minimum:
        return None
    return value


def _normalize_optional_int(raw: object, *, minimum: int = 0) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if not isinstance(raw, (int, float, str)):
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if value < minimum:
        return None
    return value


def _normalize_optional_bool(raw: object) -> bool | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)) and raw in (0, 1):
        return bool(raw)
    if isinstance(raw, str):
        value = raw.strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off"}:
            return False
    return None


def _first_env_value(*names: str) -> str | None:
    for name in names:
        raw = os.environ.get(name)
        if raw is None:
            continue
        if not isinstance(raw, str):
            continue
        if not raw.strip():
            continue
        return raw
    return None


def _as_section(raw: object) -> dict[str, object]:
    return dict(raw) if isinstance(raw, dict) else {}


def _path_or_default(raw: object, default: Path) -> Path:
    normalized = _normalize_optional_path(raw)
    return normalized if normalized is not None else default


def _resolve_paths(paths: dict[str, object]) -> tuple[Path, Path, Path]:
    root = _path_or_default(paths.get("gamehub_dir"), default_gamehub_dir())
    return root, root / "firmware", root / "state.json"


def _reject_removed_path_keys(paths: dict[str, object]) -> None:
    removed = [key for key in _REMOVED_PATH_KEYS if key in paths]
    if not removed:
        return
    removed_text = ", ".join(f"paths.{key}" for key in removed)
    migration_text = "; ".join(f"paths.{key} -> {_REMOVED_PATH_KEYS[key]}" for key in removed)
    raise ValueError(
        f"Unsupported [paths] keys: {removed_text}. "
        f"These compatibility keys were removed. Update config: {migration_text}."
    )


def _reject_removed_env_aliases() -> None:
    for legacy_name, replacement in _REMOVED_ENV_ALIASES.items():
        raw_value = os.environ.get(legacy_name)
        if isinstance(raw_value, str) and raw_value.strip():
            raise ValueError(f"Environment variable {legacy_name} is no longer supported. Use {replacement} instead.")


def load_config(config_path: Path | None = None) -> GamehubConfig:
    path = config_path or default_config_path()
    data: dict[str, object] = {}
    if path.exists():
        loaded = tomllib.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded

    default_root = default_gamehub_dir()
    server = _as_section(data.get("server"))
    paths = _as_section(data.get("paths"))
    steam = _as_section(data.get("steam"))
    sgdb = _as_section(data.get("sgdb"))
    linux = _as_section(data.get("linux"))
    macos = _as_section(data.get("macos"))
    controllers = _as_section(data.get("controllers"))
    save_sync = _as_section(data.get("save_sync"))
    backups = _as_section(data.get("backups"))
    _reject_removed_path_keys(paths)
    _reject_removed_env_aliases()

    env_api_key = _normalize_secret(_first_env_value("GAMEHUB_SGDB_API_KEY"))
    config_api_key = _normalize_secret(sgdb.get("api_key"))
    sgdb_api_key = env_api_key or config_api_key
    config_index_timeout = _normalize_optional_float(server.get("index_timeout_seconds"), minimum=1.0)
    env_index_timeout = _normalize_optional_float(_first_env_value("GAMEHUB_INDEX_TIMEOUT_SECONDS"), minimum=1.0)
    config_index_attempts = _normalize_optional_int(server.get("index_fetch_attempts"), minimum=1)
    env_index_attempts = _normalize_optional_int(_first_env_value("GAMEHUB_INDEX_FETCH_ATTEMPTS"), minimum=1)
    config_index_backoff = _normalize_optional_float(server.get("index_retry_backoff_seconds"), minimum=0.0)
    env_index_backoff = _normalize_optional_float(
        _first_env_value("GAMEHUB_INDEX_RETRY_BACKOFF_SECONDS"),
        minimum=0.0,
    )
    config_parallel_downloads = _normalize_optional_int(server.get("max_parallel_downloads"), minimum=1)
    env_parallel_downloads = _normalize_optional_int(_first_env_value("GAMEHUB_MAX_PARALLEL_DOWNLOADS"), minimum=1)

    config_steam_userdata_dir = _normalize_optional_path(steam.get("userdata_dir"))
    env_steam_userdata_dir = _normalize_optional_path(_first_env_value("GAMEHUB_STEAM_USERDATA_DIR"))
    steam_userdata_dir = env_steam_userdata_dir if env_steam_userdata_dir is not None else config_steam_userdata_dir

    config_emulator_install_backend = _normalize_optional_text(linux.get("emulator_install_backend"))
    env_emulator_install_backend = _normalize_optional_text(_first_env_value("GAMEHUB_LINUX_EMULATOR_INSTALL_BACKEND"))
    config_emulator_install_command = _normalize_optional_text(linux.get("emulator_install_command"))
    env_emulator_install_command = _normalize_optional_text(_first_env_value("GAMEHUB_LINUX_EMULATOR_INSTALL_COMMAND"))
    config_flatpak_remote = _normalize_optional_text(linux.get("flatpak_remote"))
    env_flatpak_remote = _normalize_optional_text(_first_env_value("GAMEHUB_LINUX_FLATPAK_REMOTE"))
    config_macos_emulator_install_backend = _normalize_optional_text(macos.get("emulator_install_backend"))
    env_macos_emulator_install_backend = _normalize_optional_text(
        _first_env_value("GAMEHUB_MACOS_EMULATOR_INSTALL_BACKEND")
    )
    config_macos_emulator_install_command = _normalize_optional_text(macos.get("emulator_install_command"))
    env_macos_emulator_install_command = _normalize_optional_text(
        _first_env_value("GAMEHUB_MACOS_EMULATOR_INSTALL_COMMAND")
    )
    config_macos_disable_pcsx2_rosetta = _normalize_optional_bool(macos.get("disable_pcsx2_rosetta"))
    env_macos_disable_pcsx2_rosetta = _normalize_optional_bool(_first_env_value("GAMEHUB_MACOS_DISABLE_PCSX2_ROSETTA"))

    config_roms_dir = _normalize_optional_path(paths.get("roms_dir"))
    env_roms_dir = _normalize_optional_path(_first_env_value("GAMEHUB_ROMS_DIR"))

    config_retroarch_cfg_path = _normalize_optional_path(linux.get("retroarch_cfg_path"))
    env_retroarch_cfg_path = _normalize_optional_path(_first_env_value("GAMEHUB_RETROARCH_CFG_PATH"))
    config_retroarch_system_dir = _normalize_optional_path(linux.get("retroarch_system_dir"))
    env_retroarch_system_dir = _normalize_optional_path(
        _first_env_value("RETROARCH_SYSTEM_DIR", "GAMEHUB_RETROARCH_SYSTEM_DIR")
    )
    config_retroarch_cores_dir = _normalize_optional_path(linux.get("retroarch_cores_dir"))
    env_retroarch_cores_dir = _normalize_optional_path(_first_env_value("GAMEHUB_RETROARCH_CORES_DIR"))
    config_retroarch_info_dir = _normalize_optional_path(linux.get("retroarch_info_dir"))
    env_retroarch_info_dir = _normalize_optional_path(_first_env_value("GAMEHUB_RETROARCH_INFO_DIR"))
    config_retroarch_cores_base_url = _normalize_optional_text(linux.get("retroarch_cores_base_url"))
    env_retroarch_cores_base_url = _normalize_optional_text(_first_env_value("GAMEHUB_RETROARCH_CORES_BASE_URL"))

    config_pcsx2_ini_path = _normalize_optional_path(linux.get("pcsx2_ini_path"))
    env_pcsx2_ini_path = _normalize_optional_path(_first_env_value("GAMEHUB_PCSX2_INI_PATH"))
    config_pcsx2_bios_dir = _normalize_optional_path(linux.get("pcsx2_bios_dir"))
    env_pcsx2_bios_dir = _normalize_optional_path(_first_env_value("PCSX2_BIOS_DIR", "GAMEHUB_PCSX2_BIOS_DIR"))

    config_dolphin_user_path = _normalize_optional_path(linux.get("dolphin_user_path"))
    env_dolphin_user_path = _normalize_optional_path(
        _first_env_value("DOLPHIN_EMU_USERPATH", "GAMEHUB_DOLPHIN_EMU_USERPATH")
    )
    config_macos_retroarch_cfg_path = _normalize_optional_path(macos.get("retroarch_cfg_path"))
    config_macos_retroarch_system_dir = _normalize_optional_path(macos.get("retroarch_system_dir"))
    config_macos_retroarch_cores_dir = _normalize_optional_path(macos.get("retroarch_cores_dir"))
    config_macos_retroarch_info_dir = _normalize_optional_path(macos.get("retroarch_info_dir"))
    config_macos_retroarch_cores_base_url = _normalize_optional_text(macos.get("retroarch_cores_base_url"))
    config_macos_pcsx2_ini_path = _normalize_optional_path(macos.get("pcsx2_ini_path"))
    config_macos_pcsx2_bios_dir = _normalize_optional_path(macos.get("pcsx2_bios_dir"))
    config_macos_dolphin_user_path = _normalize_optional_path(macos.get("dolphin_user_path"))

    config_controller_launch_autoconfig = _normalize_optional_bool(controllers.get("launch_autoconfig"))
    env_controller_launch_autoconfig = _normalize_optional_bool(
        _first_env_value("GAMEHUB_CONTROLLER_LAUNCH_AUTOCONFIG")
    )
    config_controller_profiles_dir = _normalize_optional_path(controllers.get("profiles_dir"))
    env_controller_profiles_dir = _normalize_optional_path(_first_env_value("GAMEHUB_CONTROLLER_PROFILES_DIR"))
    save_sync_config = _load_save_sync_config(save_sync)
    config_backup_keep_limit = _normalize_optional_int(backups.get("keep_limit"), minimum=1)
    env_backup_keep_limit = _normalize_optional_int(_first_env_value("GAMEHUB_BACKUP_KEEP_LIMIT"), minimum=1)
    server_url = _normalize_optional_text(server.get("url")) or "http://127.0.0.1:8000"
    steam_id = _normalize_optional_text(steam.get("steam_id"))
    steam_exe = _normalize_optional_path(steam.get("steam_exe"))
    sgdb_cache_dir = _path_or_default(sgdb.get("cache_dir"), default_root / "artwork_cache" / "sgdb")
    library_dir, firmware_dir, state_path = _resolve_paths(paths)
    return GamehubConfig(
        server_url=server_url,
        index_timeout_seconds=env_index_timeout if env_index_timeout is not None else config_index_timeout,
        index_fetch_attempts=env_index_attempts if env_index_attempts is not None else (config_index_attempts or 3),
        index_retry_backoff_seconds=(
            env_index_backoff
            if env_index_backoff is not None
            else (config_index_backoff if config_index_backoff is not None else 1.5)
        ),
        max_parallel_downloads=min(
            16,
            env_parallel_downloads if env_parallel_downloads is not None else (config_parallel_downloads or 4),
        ),
        library_dir=library_dir,
        firmware_dir=firmware_dir,
        state_path=state_path,
        roms_dir=env_roms_dir if env_roms_dir is not None else config_roms_dir,
        steam_userdata_dir=steam_userdata_dir,
        steam_id=steam_id,
        steam_exe=steam_exe,
        sgdb_api_key=sgdb_api_key,
        sgdb_cache_dir=sgdb_cache_dir,
        sgdb_enabled_kinds=_normalize_sgdb_kinds(sgdb.get("enabled_kinds")),
        linux=LinuxConfig(
            emulator_install_backend=(
                env_emulator_install_backend
                if env_emulator_install_backend is not None
                else config_emulator_install_backend
            ),
            emulator_install_command=(
                env_emulator_install_command
                if env_emulator_install_command is not None
                else config_emulator_install_command
            ),
            flatpak_remote=env_flatpak_remote if env_flatpak_remote is not None else config_flatpak_remote,
            retroarch_cfg_path=env_retroarch_cfg_path
            if env_retroarch_cfg_path is not None
            else config_retroarch_cfg_path,
            retroarch_system_dir=(
                env_retroarch_system_dir if env_retroarch_system_dir is not None else config_retroarch_system_dir
            ),
            retroarch_cores_dir=(
                env_retroarch_cores_dir if env_retroarch_cores_dir is not None else config_retroarch_cores_dir
            ),
            retroarch_info_dir=env_retroarch_info_dir
            if env_retroarch_info_dir is not None
            else config_retroarch_info_dir,
            retroarch_cores_base_url=(
                env_retroarch_cores_base_url
                if env_retroarch_cores_base_url is not None
                else config_retroarch_cores_base_url
            ),
            pcsx2_ini_path=env_pcsx2_ini_path if env_pcsx2_ini_path is not None else config_pcsx2_ini_path,
            pcsx2_bios_dir=env_pcsx2_bios_dir if env_pcsx2_bios_dir is not None else config_pcsx2_bios_dir,
            dolphin_user_path=env_dolphin_user_path if env_dolphin_user_path is not None else config_dolphin_user_path,
        ),
        macos=MacOSConfig(
            emulator_install_backend=(
                env_macos_emulator_install_backend
                if env_macos_emulator_install_backend is not None
                else config_macos_emulator_install_backend
            ),
            emulator_install_command=(
                env_macos_emulator_install_command
                if env_macos_emulator_install_command is not None
                else config_macos_emulator_install_command
            ),
            disable_pcsx2_rosetta=(
                env_macos_disable_pcsx2_rosetta
                if env_macos_disable_pcsx2_rosetta is not None
                else (config_macos_disable_pcsx2_rosetta if config_macos_disable_pcsx2_rosetta is not None else False)
            ),
            retroarch_cfg_path=env_retroarch_cfg_path
            if env_retroarch_cfg_path is not None
            else config_macos_retroarch_cfg_path,
            retroarch_system_dir=(
                env_retroarch_system_dir if env_retroarch_system_dir is not None else config_macos_retroarch_system_dir
            ),
            retroarch_cores_dir=(
                env_retroarch_cores_dir if env_retroarch_cores_dir is not None else config_macos_retroarch_cores_dir
            ),
            retroarch_info_dir=env_retroarch_info_dir
            if env_retroarch_info_dir is not None
            else config_macos_retroarch_info_dir,
            retroarch_cores_base_url=(
                env_retroarch_cores_base_url
                if env_retroarch_cores_base_url is not None
                else config_macos_retroarch_cores_base_url
            ),
            pcsx2_ini_path=env_pcsx2_ini_path if env_pcsx2_ini_path is not None else config_macos_pcsx2_ini_path,
            pcsx2_bios_dir=(env_pcsx2_bios_dir if env_pcsx2_bios_dir is not None else config_macos_pcsx2_bios_dir),
            dolphin_user_path=(
                env_dolphin_user_path if env_dolphin_user_path is not None else config_macos_dolphin_user_path
            ),
        ),
        controllers=ControllersConfig(
            launch_autoconfig=(
                env_controller_launch_autoconfig
                if env_controller_launch_autoconfig is not None
                else (config_controller_launch_autoconfig if config_controller_launch_autoconfig is not None else True)
            ),
            profiles_dir=(
                env_controller_profiles_dir
                if env_controller_profiles_dir is not None
                else config_controller_profiles_dir
            ),
        ),
        save_sync=save_sync_config,
        config_path=path,
        backups=BackupsConfig(
            keep_limit=env_backup_keep_limit if env_backup_keep_limit is not None else (config_backup_keep_limit or 3)
        ),
    )
