from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import typer

from .common.config import GamehubConfig, default_config_path, default_gamehub_dir, load_config
from .common.fsops import DEFAULT_BACKUP_KEEP_LIMIT, backup_existing_file, replace_file
from .steam import discover_steam_id, discover_userdata_dir


@dataclass(frozen=True)
class SteamDetection:
    userdata_dir: Path | None
    steam_id: str | None


@dataclass(frozen=True)
class ConfigInitDefaults:
    output_path: Path
    server_url: str
    gamehub_dir: Path
    steam_userdata_dir: Path | None
    steam_id: str | None
    controller_launch_autoconfig: bool
    save_sync_enabled: bool
    save_sync_mode: str
    save_sync_conflict_policy: str
    backup_keep_limit: int


def resolve_existing_config_path(config_path: Path | None) -> Path:
    resolved = config_path or default_config_path()
    if resolved.exists():
        return resolved
    raise ValueError(
        f"Config file not found: {resolved}. "
        "Run `gamehub config init` or create one from a platform template under docs/templates/ "
        "before running init, sync, or doctor."
    )


def default_config_init_path(output_path: Path | None) -> Path:
    if output_path is not None:
        return output_path
    resolved = default_config_path()
    if resolved.exists():
        return resolved
    return Path.cwd() / "config.toml"


def detect_steam_defaults() -> SteamDetection:
    userdata_dir = discover_userdata_dir(None)
    if userdata_dir is None:
        return SteamDetection(userdata_dir=None, steam_id=None)
    steam_id = discover_steam_id(userdata_dir)
    return SteamDetection(userdata_dir=userdata_dir, steam_id=steam_id)


def _existing_config_defaults(path: Path) -> GamehubConfig | None:
    if not path.exists():
        return None
    try:
        return load_config(path)
    except Exception:
        return None


def build_config_init_defaults(output_path: Path | None = None) -> ConfigInitDefaults:
    resolved_output = default_config_init_path(output_path).expanduser()
    existing = _existing_config_defaults(resolved_output)
    detected = detect_steam_defaults()
    server_url = existing.server_url if existing is not None else "http://127.0.0.1:8000"
    gamehub_dir = existing.library_dir if existing is not None else default_gamehub_dir()
    steam_userdata_dir = existing.steam_userdata_dir if existing is not None else detected.userdata_dir
    steam_id = existing.steam_id if existing is not None else detected.steam_id
    controller_launch_autoconfig = existing.controllers.launch_autoconfig if existing is not None else True
    save_sync_enabled = existing.save_sync.enabled if existing is not None else False
    save_sync_mode = existing.save_sync.mode if existing is not None else "download"
    save_sync_conflict_policy = existing.save_sync.conflict_policy if existing is not None else "manual"
    backup_keep_limit = existing.backups.keep_limit if existing is not None else DEFAULT_BACKUP_KEEP_LIMIT
    return ConfigInitDefaults(
        output_path=resolved_output,
        server_url=server_url,
        gamehub_dir=gamehub_dir,
        steam_userdata_dir=steam_userdata_dir,
        steam_id=steam_id,
        controller_launch_autoconfig=controller_launch_autoconfig,
        save_sync_enabled=save_sync_enabled,
        save_sync_mode=save_sync_mode,
        save_sync_conflict_policy=save_sync_conflict_policy,
        backup_keep_limit=backup_keep_limit,
    )


def _interactive_enabled(interactive: bool | None) -> bool:
    if interactive is not None:
        return interactive
    return sys.stdin.isatty() and sys.stdout.isatty()


def _prompt_text(label: str, *, default: str, interactive: bool, allow_empty: bool = False) -> str:
    if not interactive:
        return default
    value = str(typer.prompt(label, default=default))
    if allow_empty:
        return value.strip()
    normalized = value.strip()
    return normalized or default


def _prompt_bool(label: str, *, default: bool, interactive: bool) -> bool:
    if not interactive:
        return default
    return typer.confirm(label, default=default)


def _normalize_optional_path(value: Path | str | None) -> Path | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return Path(text).expanduser()


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _render_toml_string(value: str) -> str:
    return json.dumps(value)


def render_config_text(
    *,
    server_url: str,
    gamehub_dir: Path,
    steam_userdata_dir: Path | None,
    steam_id: str | None,
    controller_launch_autoconfig: bool,
    save_sync_enabled: bool,
    save_sync_mode: str,
    save_sync_conflict_policy: str,
    backup_keep_limit: int,
) -> str:
    lines = [
        "# Generated by `gamehub config init`.",
        "# Prefer GAMEHUB_SGDB_API_KEY in the environment instead of storing SGDB secrets here.",
        "",
        "[server]",
        f"url = {_render_toml_string(server_url)}",
        "",
        "[paths]",
        f"gamehub_dir = {_render_toml_string(str(gamehub_dir))}",
        "",
    ]
    if steam_userdata_dir is not None or steam_id is not None:
        lines.extend(["[steam]"])
        if steam_userdata_dir is not None:
            lines.append(f"userdata_dir = {_render_toml_string(str(steam_userdata_dir))}")
        if steam_id is not None:
            lines.append(f"steam_id = {_render_toml_string(steam_id)}")
        lines.append("")

    lines.extend(
        [
            "[sgdb]",
            f"cache_dir = {_render_toml_string(str(gamehub_dir / 'artwork-cache' / 'sgdb'))}",
            'enabled_kinds = ["grid", "hero", "logo", "icon"]',
            "",
            "[controllers]",
            f"launch_autoconfig = {'true' if controller_launch_autoconfig else 'false'}",
            "",
            "[backups]",
            f"keep_limit = {backup_keep_limit}",
            "",
            "[save_sync]",
            f"enabled = {'true' if save_sync_enabled else 'false'}",
        ]
    )
    if save_sync_enabled:
        lines.append(f"mode = {_render_toml_string(save_sync_mode)}")
        if save_sync_mode == "bidirectional":
            lines.append(f"conflict_policy = {_render_toml_string(save_sync_conflict_policy)}")
    lines.append("")
    return "\n".join(lines)


def _write_new_config(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def _overwrite_config_atomic(path: Path, text: str, *, keep_limit: int) -> tuple[Path | None, tuple[Path, ...]]:
    backup_result = backup_existing_file(path, keep_limit=keep_limit)
    temp_handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp")
    try:
        with temp_handle as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        replace_file(Path(temp_handle.name), path)
    finally:
        Path(temp_handle.name).unlink(missing_ok=True)
    return backup_result.created_path, backup_result.pruned_paths


def run_config_init(
    *,
    output_path: Path | None,
    server_url: str | None,
    gamehub_dir: Path | None,
    steam_userdata_dir: Path | None,
    steam_id: str | None,
    controller_launch_autoconfig: bool | None,
    save_sync_enabled: bool | None,
    save_sync_mode: str | None,
    save_sync_conflict_policy: str | None,
    interactive: bool | None = None,
) -> int:
    defaults = build_config_init_defaults(output_path)
    prompt_mode = _interactive_enabled(interactive)

    resolved_output = Path(
        _prompt_text(
            "Config output path",
            default=str(defaults.output_path),
            interactive=prompt_mode,
        )
    ).expanduser()
    resolved_server_url = _prompt_text(
        "Server URL",
        default=_normalize_optional_text(server_url) or defaults.server_url,
        interactive=prompt_mode,
    )
    resolved_gamehub_dir = Path(
        _prompt_text(
            "Local GAMEHUB directory",
            default=str(_normalize_optional_path(gamehub_dir) or defaults.gamehub_dir),
            interactive=prompt_mode,
        )
    ).expanduser()

    steam_userdata_default = str(_normalize_optional_path(steam_userdata_dir) or defaults.steam_userdata_dir or "")
    resolved_steam_userdata = _normalize_optional_path(
        _prompt_text(
            "Steam userdata path (optional)",
            default=steam_userdata_default,
            interactive=prompt_mode,
            allow_empty=True,
        )
    )
    steam_id_default = _normalize_optional_text(steam_id) or defaults.steam_id or ""
    resolved_steam_id = _normalize_optional_text(
        _prompt_text(
            "Steam ID (optional)",
            default=steam_id_default,
            interactive=prompt_mode,
            allow_empty=True,
        )
    )
    if resolved_steam_id is not None and not resolved_steam_id.isdigit():
        raise ValueError(f"Configured steam_id is not numeric: {resolved_steam_id}")

    resolved_controller_autoconfig = (
        controller_launch_autoconfig
        if controller_launch_autoconfig is not None
        else _prompt_bool(
            "Enable controller autoconfig by default?",
            default=defaults.controller_launch_autoconfig,
            interactive=prompt_mode,
        )
    )
    resolved_save_sync_enabled = (
        save_sync_enabled
        if save_sync_enabled is not None
        else _prompt_bool(
            "Enable save sync by default?",
            default=defaults.save_sync_enabled,
            interactive=prompt_mode,
        )
    )
    resolved_save_sync_mode = "download"
    if resolved_save_sync_enabled:
        resolved_save_sync_mode = _normalize_optional_text(save_sync_mode) or defaults.save_sync_mode or "download"
        if prompt_mode and save_sync_mode is None:
            resolved_save_sync_mode = _prompt_text(
                "Save sync mode (download or bidirectional)",
                default=resolved_save_sync_mode,
                interactive=True,
            ).lower()
        if resolved_save_sync_mode not in {"download", "bidirectional"}:
            raise ValueError("Save sync mode must be 'download' or 'bidirectional'.")

    resolved_conflict_policy = "manual"
    if resolved_save_sync_enabled and resolved_save_sync_mode == "bidirectional":
        resolved_conflict_policy = (
            _normalize_optional_text(save_sync_conflict_policy) or defaults.save_sync_conflict_policy or "manual"
        )
        if prompt_mode and save_sync_conflict_policy is None:
            resolved_conflict_policy = _prompt_text(
                "Conflict policy (manual, prefer_server, prefer_local)",
                default=resolved_conflict_policy,
                interactive=True,
            ).lower()
        if resolved_conflict_policy not in {"manual", "prefer_server", "prefer_local"}:
            raise ValueError("Conflict policy must be 'manual', 'prefer_server', or 'prefer_local'.")

    rendered = render_config_text(
        server_url=resolved_server_url,
        gamehub_dir=resolved_gamehub_dir,
        steam_userdata_dir=resolved_steam_userdata,
        steam_id=resolved_steam_id,
        controller_launch_autoconfig=resolved_controller_autoconfig,
        save_sync_enabled=resolved_save_sync_enabled,
        save_sync_mode=resolved_save_sync_mode,
        save_sync_conflict_policy=resolved_conflict_policy,
        backup_keep_limit=defaults.backup_keep_limit,
    )

    if resolved_output.exists():
        backup_path, pruned_paths = _overwrite_config_atomic(
            resolved_output,
            rendered,
            keep_limit=defaults.backup_keep_limit,
        )
        if backup_path is not None:
            print(f"Backed up existing config: {backup_path}")
        for pruned_path in pruned_paths:
            print(f"Pruned old config backup: {pruned_path}")
        print(f"Updated config: {resolved_output}")
    else:
        _write_new_config(resolved_output, rendered)
        print(f"Wrote config: {resolved_output}")

    print("SGDB secret policy: prefer GAMEHUB_SGDB_API_KEY in the environment.")
    return 0


def run_config_verify(*, config_path: Path | None) -> int:
    resolved = resolve_existing_config_path(config_path)
    loaded = load_config(resolved)
    if loaded.steam_id is not None and not loaded.steam_id.isdigit():
        raise ValueError(f"Configured steam_id is not numeric: {loaded.steam_id}")
    print(f"config-verify\tok\tpath={resolved}\tserver={loaded.server_url}\tgamehub_dir={loaded.library_dir}")
    return 0
