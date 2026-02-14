from __future__ import annotations

from dataclasses import dataclass
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


_VALID_SGDB_KINDS = ("grid", "hero", "logo", "icon")


def default_config_path() -> Path:
    return Path(user_config_dir("gamehub")) / "config.toml"


def default_state_path() -> Path:
    return Path(user_state_dir("gamehub")) / "state.json"


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


def load_config(config_path: Path | None = None) -> GamehubConfig:
    path = config_path or default_config_path()
    if not path.exists():
        sgdb_api_key = _normalize_secret(os.environ.get("GAMEHUB_SGDB_API_KEY"))
        return GamehubConfig(
            server_url="http://127.0.0.1:8000",
            library_dir=Path(user_state_dir("gamehub")) / "library",
            firmware_dir=Path(user_state_dir("gamehub")) / "firmware",
            state_path=default_state_path(),
            steam_userdata_dir=None,
            steam_id=None,
            steam_exe=None,
            sgdb_api_key=sgdb_api_key,
            sgdb_cache_dir=default_sgdb_cache_dir(),
            sgdb_enabled_kinds=_VALID_SGDB_KINDS,
        )

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    server = data.get("server", {})
    paths = data.get("paths", {})
    steam = data.get("steam", {})
    sgdb = data.get("sgdb", {})
    env_api_key = _normalize_secret(os.environ.get("GAMEHUB_SGDB_API_KEY"))
    config_api_key = _normalize_secret(sgdb.get("api_key"))
    sgdb_api_key = env_api_key or config_api_key
    return GamehubConfig(
        server_url=str(server.get("url", "http://127.0.0.1:8000")),
        library_dir=Path(paths.get("library_dir", Path(user_state_dir("gamehub")) / "library")).expanduser(),
        firmware_dir=Path(paths.get("firmware_dir", Path(user_state_dir("gamehub")) / "firmware")).expanduser(),
        state_path=Path(paths.get("state_path", default_state_path())).expanduser(),
        steam_userdata_dir=Path(steam["userdata_dir"]).expanduser() if steam.get("userdata_dir") else None,
        steam_id=str(steam["steam_id"]) if steam.get("steam_id") else None,
        steam_exe=Path(steam["steam_exe"]).expanduser() if steam.get("steam_exe") else None,
        sgdb_api_key=sgdb_api_key,
        sgdb_cache_dir=Path(sgdb.get("cache_dir", default_sgdb_cache_dir())).expanduser(),
        sgdb_enabled_kinds=_normalize_sgdb_kinds(sgdb.get("enabled_kinds")),
    )
