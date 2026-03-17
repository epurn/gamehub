from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import typer

from .common.config import GamehubConfig, default_config_path, load_config
from .controllers.convergence import run_controller_doctor
from .shortcuts.shortcut_launch import run_shortcut_launch
from .steam import build_context, discover_deck_steam_input_roots, discover_steam_id, discover_userdata_dir
from .sync import run_init, run_sync
from .sync.diagnostics import build_sync_diagnostics_snapshot, run_firmware_doctor, run_roms_doctor, run_save_doctor
from .sync.save_resolution import run_save_resolution


def _resolve_existing_config_path(config_path: Path | None) -> Path:
    resolved = config_path or default_config_path()
    if resolved.exists():
        return resolved
    raise ValueError(
        f"Config file not found: {resolved}. "
        "Create one from a platform template under docs/templates/ before running init, sync, or doctor."
    )


def _load_existing_config(config_path: Path | None) -> GamehubConfig:
    return load_config(_resolve_existing_config_path(config_path))


def _exit_for_cli_command(command: Callable[[], int]) -> None:
    try:
        code = command()
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    raise typer.Exit(code=code)


def _run_init_command(
    *,
    config_path: Path | None,
    dry_run: bool,
    verbose: bool,
    reseed_profiles: bool,
) -> int:
    loaded = _load_existing_config(config_path)
    return run_init(
        config=loaded,
        dry_run=dry_run,
        verbose=verbose,
        reseed_profiles=reseed_profiles,
    )


def _run_sync_command(
    *,
    config_path: Path | None,
    dry_run: bool,
    verbose: bool,
    verify: bool,
    require_steam_closed: bool,
    skip_steam: bool,
    skip_steam_relaunch: bool,
    reseed_profiles: bool,
) -> int:
    loaded = _load_existing_config(config_path)
    return run_sync(
        config=loaded,
        dry_run=dry_run,
        verbose=verbose,
        verify=verify,
        require_steam_closed=require_steam_closed,
        skip_steam=skip_steam,
        skip_steam_relaunch=skip_steam_relaunch,
        reseed_profiles=reseed_profiles,
    )


def _run_doctor_controllers_command(
    *,
    config_path: Path | None,
    apply: bool,
    force: bool,
) -> int:
    if force and not apply:
        raise ValueError("--force requires --apply.")
    loaded = _load_existing_config(config_path)
    roots, note = _discover_controller_doctor_steam_roots(loaded)
    return run_controller_doctor(
        loaded,
        apply=apply,
        force=force,
        steam_roots=roots,
        steam_discovery_note=note,
    )


def _run_doctor_roms_command(
    *,
    config_path: Path | None,
    verbose: bool,
    verify: bool,
) -> int:
    loaded = _load_existing_config(config_path)
    return run_roms_doctor(loaded, verify=verify, verbose=verbose)


def _run_doctor_firmware_command(
    *,
    config_path: Path | None,
    verbose: bool,
    verify: bool,
) -> int:
    loaded = _load_existing_config(config_path)
    return run_firmware_doctor(loaded, verify=verify, verbose=verbose)


def _run_doctor_saves_command(
    *,
    config_path: Path | None,
    verbose: bool,
    verify: bool,
    dry_run: bool,
    keep_local_save_id: str | None,
    keep_server_save_id: str | None,
) -> int:
    loaded = _load_existing_config(config_path)
    if keep_local_save_id is not None and keep_server_save_id is not None:
        raise ValueError("Choose only one of --keep-local or --keep-server.")
    if keep_local_save_id is not None:
        return run_save_resolution(
            loaded,
            save_id=keep_local_save_id,
            choice="keep-local",
            dry_run=dry_run,
            verbose=verbose,
            verify=verify,
        )
    if keep_server_save_id is not None:
        return run_save_resolution(
            loaded,
            save_id=keep_server_save_id,
            choice="keep-server",
            dry_run=dry_run,
            verbose=verbose,
            verify=verify,
        )
    if dry_run:
        raise ValueError("--dry-run requires --keep-local or --keep-server.")
    return run_save_doctor(loaded, verify=verify, verbose=verbose)


def _run_doctor_all_command(
    *,
    config_path: Path | None,
    verbose: bool,
    verify: bool,
) -> int:
    loaded = _load_existing_config(config_path)
    roots, note = _discover_controller_doctor_steam_roots(loaded)
    controller_code = run_controller_doctor(
        loaded,
        apply=False,
        force=False,
        steam_roots=roots,
        steam_discovery_note=note,
    )
    snapshot = build_sync_diagnostics_snapshot(loaded, verify=verify, verbose=verbose)
    save_code = run_save_doctor(loaded, verify=verify, verbose=verbose, snapshot=snapshot)
    firmware_code = run_firmware_doctor(loaded, verify=verify, verbose=verbose, snapshot=snapshot)
    roms_code = run_roms_doctor(loaded, verify=verify, verbose=verbose, snapshot=snapshot)
    return 1 if any(code != 0 for code in (controller_code, save_code, firmware_code, roms_code)) else 0


app = typer.Typer(add_completion=False, no_args_is_help=True)
doctor_app = typer.Typer(add_completion=False, no_args_is_help=True)
app.add_typer(doctor_app, name="doctor")


@app.callback()
def root() -> None:
    """GAMEHUB CLI entrypoint."""
    return


@app.command()
def init(
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Path to config TOML (default lookup: ./config.toml then ~/.gamehub/config.toml)",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Plan only; do not mutate local bootstrap state"),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose logging"),
    reseed_profiles: bool = typer.Option(
        False,
        "--reseed-profiles",
        help="Overwrite managed profile/template files during init",
    ),
) -> None:
    _exit_for_cli_command(
        lambda: _run_init_command(
            config_path=config,
            dry_run=dry_run,
            verbose=verbose,
            reseed_profiles=reseed_profiles,
        )
    )


@app.command()
def sync(
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Path to config TOML (default lookup: ./config.toml then ~/.gamehub/config.toml)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Plan only; do not download or modify Steam (includes save-sync planning when enabled)",
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose logging"),
    verify: bool = typer.Option(False, "--verify", help="Re-hash local files before diffing"),
    skip_steam: bool = typer.Option(False, "--skip-steam", help="Skip Steam lifecycle and update hooks"),
    skip_steam_relaunch: bool = typer.Option(
        False,
        "--skip-steam-relaunch",
        help="Apply Steam updates but do not relaunch Steam afterward",
    ),
    require_steam_closed: bool = typer.Option(
        False,
        "--require-steam-closed",
        help="Fail if Steam cannot be closed before config writes",
    ),
    reseed_profiles: bool = typer.Option(
        False,
        "--reseed-profiles",
        help="Overwrite managed profile/template files during sync",
    ),
) -> None:
    _exit_for_cli_command(
        lambda: _run_sync_command(
            config_path=config,
            dry_run=dry_run,
            verbose=verbose,
            verify=verify,
            require_steam_closed=require_steam_closed,
            skip_steam=skip_steam,
            skip_steam_relaunch=skip_steam_relaunch,
            reseed_profiles=reseed_profiles,
        )
    )


@app.command("shortcut-launch", hidden=True)
def shortcut_launch(
    payload: str | None = typer.Option(None, "--payload", help="Encoded shortcut-launch payload."),
    payload_ref: str | None = typer.Option(None, "--payload-ref", help="Shortcut payload registry reference."),
    payload_registry: Path | None = typer.Option(
        None,
        "--payload-registry",
        help="Path to shortcut payload registry.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Optional config TOML path override for shortcut launch.",
    ),
) -> None:
    raise typer.Exit(
        code=run_shortcut_launch(
            payload_token=payload,
            payload_ref=payload_ref,
            payload_registry_path=payload_registry,
            config_path=config,
        )
    )


@doctor_app.command("controllers")
def doctor_controllers(
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Path to config TOML (default lookup: ./config.toml then ~/.gamehub/config.toml)",
    ),
    apply: bool = typer.Option(False, "--apply", help="Apply safe controller repairs."),
    force: bool = typer.Option(
        False,
        "--force",
        help="With --apply, archive and clean up unmanaged profile files as well.",
    ),
) -> None:
    _exit_for_cli_command(lambda: _run_doctor_controllers_command(config_path=config, apply=apply, force=force))


@doctor_app.command("roms")
def doctor_roms(
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Path to config TOML (default lookup: ./config.toml then ~/.gamehub/config.toml)",
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose logging"),
    verify: bool = typer.Option(False, "--verify", help="Re-hash local files before diffing"),
) -> None:
    _exit_for_cli_command(lambda: _run_doctor_roms_command(config_path=config, verbose=verbose, verify=verify))


@doctor_app.command("firmware")
def doctor_firmware(
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Path to config TOML (default lookup: ./config.toml then ~/.gamehub/config.toml)",
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose logging"),
    verify: bool = typer.Option(False, "--verify", help="Re-hash local files before diffing"),
) -> None:
    _exit_for_cli_command(lambda: _run_doctor_firmware_command(config_path=config, verbose=verbose, verify=verify))


@doctor_app.command("saves")
def doctor_saves(
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Path to config TOML (default lookup: ./config.toml then ~/.gamehub/config.toml)",
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose logging"),
    verify: bool = typer.Option(False, "--verify", help="Re-hash local files before diffing"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview a requested save resolution without mutating data"),
    keep_local: str | None = typer.Option(
        None,
        "--keep-local",
        help="Resolve one indexed save by uploading the local copy to the server",
    ),
    keep_server: str | None = typer.Option(
        None,
        "--keep-server",
        help="Resolve one indexed save by downloading the server copy locally",
    ),
) -> None:
    _exit_for_cli_command(
        lambda: _run_doctor_saves_command(
            config_path=config,
            verbose=verbose,
            verify=verify,
            dry_run=dry_run,
            keep_local_save_id=keep_local,
            keep_server_save_id=keep_server,
        )
    )


@doctor_app.command("all")
def doctor_all(
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Path to config TOML (default lookup: ./config.toml then ~/.gamehub/config.toml)",
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose logging"),
    verify: bool = typer.Option(False, "--verify", help="Re-hash local files before diffing"),
) -> None:
    _exit_for_cli_command(lambda: _run_doctor_all_command(config_path=config, verbose=verbose, verify=verify))


def _unique_paths(paths: list[Path]) -> tuple[Path, ...]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        marker = str(path).replace("\\", "/").casefold()
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(path)
    return tuple(unique)


def _discover_controller_doctor_steam_roots(config: GamehubConfig) -> tuple[tuple[Path, ...], str | None]:
    userdata_dir = discover_userdata_dir(config.steam_userdata_dir)
    if userdata_dir is None:
        return (), "Steam userdata root not found"
    roots: list[Path] = [userdata_dir]
    try:
        steam_id = discover_steam_id(userdata_dir, preferred_steam_id=config.steam_id)
    except ValueError as exc:
        return _unique_paths(roots), str(exc)
    if steam_id is None:
        return _unique_paths(roots), "Steam ID not found"
    context = build_context(userdata_dir, steam_id, config.steam_exe)
    roots.append(context.userdata_dir / context.steam_id / "config")
    roots.extend(discover_deck_steam_input_roots(steam_id))
    return _unique_paths(roots), None


def main() -> None:
    app()


if __name__ == "__main__":
    main()
