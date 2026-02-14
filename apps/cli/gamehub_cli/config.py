from __future__ import annotations

from dataclasses import dataclass
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
    steam_exe: Path | None


def default_config_path() -> Path:
    return Path(user_config_dir("gamehub")) / "config.toml"


def default_state_path() -> Path:
    return Path(user_state_dir("gamehub")) / "state.json"


def load_config(config_path: Path | None = None) -> GamehubConfig:
    path = config_path or default_config_path()
    if not path.exists():
        return GamehubConfig(
            server_url="http://127.0.0.1:8000",
            library_dir=Path(user_state_dir("gamehub")) / "library",
            firmware_dir=Path(user_state_dir("gamehub")) / "firmware",
            state_path=default_state_path(),
            steam_userdata_dir=None,
            steam_exe=None,
        )

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    server = data.get("server", {})
    paths = data.get("paths", {})
    steam = data.get("steam", {})
    return GamehubConfig(
        server_url=str(server.get("url", "http://127.0.0.1:8000")),
        library_dir=Path(paths.get("library_dir", Path(user_state_dir("gamehub")) / "library")).expanduser(),
        firmware_dir=Path(paths.get("firmware_dir", Path(user_state_dir("gamehub")) / "firmware")).expanduser(),
        state_path=Path(paths.get("state_path", default_state_path())).expanduser(),
        steam_userdata_dir=Path(steam["userdata_dir"]).expanduser() if steam.get("userdata_dir") else None,
        steam_exe=Path(steam["steam_exe"]).expanduser() if steam.get("steam_exe") else None,
    )
