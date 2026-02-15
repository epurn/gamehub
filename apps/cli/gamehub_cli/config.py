from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import tomllib

try:
    from platformdirs import user_config_dir, user_state_dir
except ModuleNotFoundError:
    def user_config_dir(appname: str) -> str:
        return str(Path.home() / f".{appname}")

    def user_state_dir(appname: str) -> str:
        return str(Path.home() / f".{appname}")


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
    pcsx2_controller_autoconfig: bool = True
    dolphin_user_path: Path | None = None


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
    index_timeout_seconds: float | None = None
    index_fetch_attempts: int = 3
    index_retry_backoff_seconds: float = 1.5
    max_parallel_downloads: int = 4
    linux: LinuxConfig = field(default_factory=LinuxConfig)


_VALID_SGDB_KINDS = ("grid", "hero", "logo", "icon")


def default_config_path() -> Path:
    local_config = Path.cwd() / "config.toml"
    if local_config.exists():
        return local_config
    return Path(user_config_dir("gamehub")) / "config.toml"


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


def _resolve_paths(paths: dict[str, object]) -> tuple[Path, Path, Path]:
    """
    Resolve client storage locations.

    Canonical config key is `paths.gamehub_dir`.
    Legacy keys are accepted as fallback for compatibility.
    """
    root = Path(paths.get("gamehub_dir", paths.get("library_dir", default_gamehub_dir()))).expanduser()
    if "gamehub_dir" in paths:
        return root, root / "firmware", root / "state.json"
    firmware = Path(paths.get("firmware_dir", root / "firmware")).expanduser()
    state = Path(paths.get("state_path", root / "state.json")).expanduser()
    return root, firmware, state


def load_config(config_path: Path | None = None) -> GamehubConfig:
    path = config_path or default_config_path()
    data: dict[str, object] = {}
    if path.exists():
        loaded = tomllib.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded

    default_root = default_gamehub_dir()
    server = data.get("server", {}) if isinstance(data.get("server", {}), dict) else {}
    paths = data.get("paths", {}) if isinstance(data.get("paths", {}), dict) else {}
    steam = data.get("steam", {}) if isinstance(data.get("steam", {}), dict) else {}
    sgdb = data.get("sgdb", {}) if isinstance(data.get("sgdb", {}), dict) else {}
    linux = data.get("linux", {}) if isinstance(data.get("linux", {}), dict) else {}

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
    env_dolphin_user_path = _normalize_optional_path(_first_env_value("DOLPHIN_EMU_USERPATH", "GAMEHUB_DOLPHIN_EMU_USERPATH"))

    config_pcsx2_controller_autoconfig = _normalize_optional_bool(linux.get("pcsx2_controller_autoconfig"))
    env_pcsx2_controller_autoconfig = _normalize_optional_bool(_first_env_value("GAMEHUB_PCSX2_CONTROLLER_AUTOCONFIG"))
    library_dir, firmware_dir, state_path = _resolve_paths(paths)
    return GamehubConfig(
        server_url=str(server.get("url", "http://127.0.0.1:8000")),
        index_timeout_seconds=env_index_timeout if env_index_timeout is not None else config_index_timeout,
        index_fetch_attempts=env_index_attempts if env_index_attempts is not None else (config_index_attempts or 3),
        index_retry_backoff_seconds=(
            env_index_backoff if env_index_backoff is not None else (config_index_backoff if config_index_backoff is not None else 1.5)
        ),
        max_parallel_downloads=min(
            16,
            env_parallel_downloads if env_parallel_downloads is not None else (config_parallel_downloads or 4),
        ),
        library_dir=library_dir,
        firmware_dir=firmware_dir,
        state_path=state_path,
        steam_userdata_dir=steam_userdata_dir,
        steam_id=str(steam["steam_id"]) if steam.get("steam_id") else None,
        steam_exe=Path(steam["steam_exe"]).expanduser() if steam.get("steam_exe") else None,
        sgdb_api_key=sgdb_api_key,
        sgdb_cache_dir=Path(sgdb.get("cache_dir", default_root / "artwork_cache" / "sgdb")).expanduser(),
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
            retroarch_cfg_path=env_retroarch_cfg_path if env_retroarch_cfg_path is not None else config_retroarch_cfg_path,
            retroarch_system_dir=(
                env_retroarch_system_dir
                if env_retroarch_system_dir is not None
                else config_retroarch_system_dir
            ),
            retroarch_cores_dir=(
                env_retroarch_cores_dir if env_retroarch_cores_dir is not None else config_retroarch_cores_dir
            ),
            retroarch_info_dir=env_retroarch_info_dir if env_retroarch_info_dir is not None else config_retroarch_info_dir,
            retroarch_cores_base_url=(
                env_retroarch_cores_base_url
                if env_retroarch_cores_base_url is not None
                else config_retroarch_cores_base_url
            ),
            pcsx2_ini_path=env_pcsx2_ini_path if env_pcsx2_ini_path is not None else config_pcsx2_ini_path,
            pcsx2_bios_dir=env_pcsx2_bios_dir if env_pcsx2_bios_dir is not None else config_pcsx2_bios_dir,
            pcsx2_controller_autoconfig=(
                env_pcsx2_controller_autoconfig
                if env_pcsx2_controller_autoconfig is not None
                else (config_pcsx2_controller_autoconfig if config_pcsx2_controller_autoconfig is not None else True)
            ),
            dolphin_user_path=env_dolphin_user_path if env_dolphin_user_path is not None else config_dolphin_user_path,
        ),
    )
