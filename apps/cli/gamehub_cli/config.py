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
    retroarch_cfg_path: Path | None = None
    retroarch_system_dir: Path | None = None
    retroarch_cores_dir: Path | None = None
    retroarch_info_dir: Path | None = None
    retroarch_cores_base_url: str | None = None
    pcsx2_ini_path: Path | None = None
    pcsx2_bios_dir: Path | None = None
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
    default_root = default_gamehub_dir()
    if not path.exists():
        sgdb_api_key = _normalize_secret(os.environ.get("GAMEHUB_SGDB_API_KEY"))
        return GamehubConfig(
            server_url="http://127.0.0.1:8000",
            library_dir=default_root,
            firmware_dir=default_root / "firmware",
            state_path=default_root / "state.json",
            steam_userdata_dir=None,
            steam_id=None,
            steam_exe=None,
            sgdb_api_key=sgdb_api_key,
            sgdb_cache_dir=default_sgdb_cache_dir(),
            sgdb_enabled_kinds=_VALID_SGDB_KINDS,
            linux=LinuxConfig(),
        )

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    server = data.get("server", {})
    paths = data.get("paths", {})
    steam = data.get("steam", {})
    sgdb = data.get("sgdb", {})
    linux = data.get("linux", {})
    env_api_key = _normalize_secret(os.environ.get("GAMEHUB_SGDB_API_KEY"))
    config_api_key = _normalize_secret(sgdb.get("api_key"))
    sgdb_api_key = env_api_key or config_api_key
    library_dir, firmware_dir, state_path = _resolve_paths(paths)
    return GamehubConfig(
        server_url=str(server.get("url", "http://127.0.0.1:8000")),
        library_dir=library_dir,
        firmware_dir=firmware_dir,
        state_path=state_path,
        steam_userdata_dir=Path(steam["userdata_dir"]).expanduser() if steam.get("userdata_dir") else None,
        steam_id=str(steam["steam_id"]) if steam.get("steam_id") else None,
        steam_exe=Path(steam["steam_exe"]).expanduser() if steam.get("steam_exe") else None,
        sgdb_api_key=sgdb_api_key,
        sgdb_cache_dir=Path(sgdb.get("cache_dir", default_sgdb_cache_dir())).expanduser(),
        sgdb_enabled_kinds=_normalize_sgdb_kinds(sgdb.get("enabled_kinds")),
        linux=LinuxConfig(
            emulator_install_backend=_normalize_optional_text(linux.get("emulator_install_backend")),
            emulator_install_command=_normalize_optional_text(linux.get("emulator_install_command")),
            retroarch_cfg_path=_normalize_optional_path(linux.get("retroarch_cfg_path")),
            retroarch_system_dir=_normalize_optional_path(linux.get("retroarch_system_dir")),
            retroarch_cores_dir=_normalize_optional_path(linux.get("retroarch_cores_dir")),
            retroarch_info_dir=_normalize_optional_path(linux.get("retroarch_info_dir")),
            retroarch_cores_base_url=_normalize_optional_text(linux.get("retroarch_cores_base_url")),
            pcsx2_ini_path=_normalize_optional_path(linux.get("pcsx2_ini_path")),
            pcsx2_bios_dir=_normalize_optional_path(linux.get("pcsx2_bios_dir")),
            dolphin_user_path=_normalize_optional_path(linux.get("dolphin_user_path")),
        ),
    )
