from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .common.config import GamehubConfig, default_config_path, load_config
from .controllers.convergence import run_controller_doctor
from .controllers.launch import run_shortcut_launch
from .steam import build_context, discover_deck_steam_input_roots, discover_steam_id, discover_userdata_dir
from .sync import run_init, run_sync
from .sync.diagnostics import build_sync_diagnostics_snapshot, run_firmware_doctor, run_roms_doctor

typer: Any
_typer: Any | None = None
try:
    import typer as _typer_module
except ModuleNotFoundError:
    pass
else:
    _typer = _typer_module
typer = _typer


def _resolve_existing_config_path(config_path: Path | None) -> Path:
    resolved = config_path or default_config_path()
    if resolved.exists():
        return resolved
    raise ValueError(f"Config file not found: {resolved}. Create a config file before running 'gamehub init'.")


def _load_existing_config(config_path: Path | None) -> GamehubConfig:
    return load_config(_resolve_existing_config_path(config_path))


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
    loaded = load_config(config_path)
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
    loaded = load_config(config_path)
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
    loaded = load_config(config_path)
    return run_roms_doctor(loaded, verify=verify, verbose=verbose)


def _run_doctor_firmware_command(
    *,
    config_path: Path | None,
    verbose: bool,
    verify: bool,
) -> int:
    loaded = load_config(config_path)
    return run_firmware_doctor(loaded, verify=verify, verbose=verbose)


def _run_doctor_all_command(
    *,
    config_path: Path | None,
    verbose: bool,
    verify: bool,
) -> int:
    loaded = load_config(config_path)
    roots, note = _discover_controller_doctor_steam_roots(loaded)
    controller_code = run_controller_doctor(
        loaded,
        apply=False,
        force=False,
        steam_roots=roots,
        steam_discovery_note=note,
    )
    snapshot = build_sync_diagnostics_snapshot(loaded, verify=verify, verbose=verbose)
    firmware_code = run_firmware_doctor(loaded, verify=verify, verbose=verbose, snapshot=snapshot)
    roms_code = run_roms_doctor(loaded, verify=verify, verbose=verbose, snapshot=snapshot)
    return 1 if any(code != 0 for code in (controller_code, firmware_code, roms_code)) else 0


if typer is not None:
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
        try:
            code = _run_init_command(
                config_path=config,
                dry_run=dry_run,
                verbose=verbose,
                reseed_profiles=reseed_profiles,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        raise typer.Exit(code=code)

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
        raise typer.Exit(
            code=_run_sync_command(
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
        payload: str = typer.Option(..., "--payload", help="Encoded shortcut-launch payload."),
        config: Path | None = typer.Option(
            None,
            "--config",
            help="Optional config TOML path override for shortcut launch.",
        ),
        audit: bool = typer.Option(False, "--audit", help="Print controller profile apply diagnostics."),
    ) -> None:
        raise typer.Exit(code=run_shortcut_launch(payload_token=payload, config_path=config, audit=audit))

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
        try:
            code = _run_doctor_controllers_command(config_path=config, apply=apply, force=force)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        raise typer.Exit(code=code)

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
        raise typer.Exit(code=_run_doctor_roms_command(config_path=config, verbose=verbose, verify=verify))

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
        raise typer.Exit(code=_run_doctor_firmware_command(config_path=config, verbose=verbose, verify=verify))

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
        raise typer.Exit(code=_run_doctor_all_command(config_path=config, verbose=verbose, verify=verify))
else:
    app = None


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
    if app is not None:
        app()
        return

    parser = argparse.ArgumentParser(prog="gamehub")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config TOML (default lookup: ./config.toml then ~/.gamehub/config.toml)",
    )
    init_parser.add_argument("--dry-run", action="store_true")
    init_parser.add_argument("--verbose", action="store_true")
    init_parser.add_argument(
        "--reseed-profiles",
        action="store_true",
        help="Overwrite managed profile/template files during init",
    )

    sync_parser = subparsers.add_parser("sync")
    sync_parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config TOML (default lookup: ./config.toml then ~/.gamehub/config.toml)",
    )
    sync_parser.add_argument("--dry-run", action="store_true", help="Plan only; no downloads or Steam writes")
    sync_parser.add_argument("--verbose", action="store_true")
    sync_parser.add_argument("--verify", action="store_true")
    sync_parser.add_argument("--skip-steam", action="store_true")
    sync_parser.add_argument("--skip-steam-relaunch", action="store_true")
    sync_parser.add_argument("--require-steam-closed", action="store_true")
    sync_parser.add_argument(
        "--reseed-profiles", action="store_true", help="Overwrite managed profile/template files during sync"
    )

    shortcut_launch_parser = subparsers.add_parser("shortcut-launch", help=argparse.SUPPRESS)
    shortcut_launch_parser.add_argument("--payload", required=True, help=argparse.SUPPRESS)
    shortcut_launch_parser.add_argument("--config", type=Path, default=None, help=argparse.SUPPRESS)
    shortcut_launch_parser.add_argument("--audit", action="store_true", help=argparse.SUPPRESS)

    doctor_parser = subparsers.add_parser("doctor")
    doctor_subparsers = doctor_parser.add_subparsers(dest="doctor_command", required=True)

    doctor_controllers_parser = doctor_subparsers.add_parser("controllers")
    doctor_controllers_parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config TOML (default lookup: ./config.toml then ~/.gamehub/config.toml)",
    )
    doctor_controllers_parser.add_argument("--apply", action="store_true")
    doctor_controllers_parser.add_argument("--force", action="store_true")

    doctor_roms_parser = doctor_subparsers.add_parser("roms")
    doctor_roms_parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config TOML (default lookup: ./config.toml then ~/.gamehub/config.toml)",
    )
    doctor_roms_parser.add_argument("--verbose", action="store_true")
    doctor_roms_parser.add_argument("--verify", action="store_true")

    doctor_firmware_parser = doctor_subparsers.add_parser("firmware")
    doctor_firmware_parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config TOML (default lookup: ./config.toml then ~/.gamehub/config.toml)",
    )
    doctor_firmware_parser.add_argument("--verbose", action="store_true")
    doctor_firmware_parser.add_argument("--verify", action="store_true")

    doctor_all_parser = doctor_subparsers.add_parser("all")
    doctor_all_parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config TOML (default lookup: ./config.toml then ~/.gamehub/config.toml)",
    )
    doctor_all_parser.add_argument("--verbose", action="store_true")
    doctor_all_parser.add_argument("--verify", action="store_true")

    args = parser.parse_args()
    if args.command == "init":
        try:
            raise SystemExit(
                _run_init_command(
                    config_path=args.config,
                    dry_run=args.dry_run,
                    verbose=args.verbose,
                    reseed_profiles=args.reseed_profiles,
                )
            )
        except ValueError as exc:
            parser.error(str(exc))
    if args.command == "sync":
        raise SystemExit(
            _run_sync_command(
                config_path=args.config,
                dry_run=args.dry_run,
                verbose=args.verbose,
                verify=args.verify,
                require_steam_closed=args.require_steam_closed,
                skip_steam=args.skip_steam,
                skip_steam_relaunch=args.skip_steam_relaunch,
                reseed_profiles=args.reseed_profiles,
            )
        )
    if args.command == "shortcut-launch":
        raise SystemExit(run_shortcut_launch(payload_token=args.payload, config_path=args.config, audit=args.audit))
    if args.command == "doctor":
        if args.doctor_command == "controllers":
            try:
                raise SystemExit(
                    _run_doctor_controllers_command(
                        config_path=args.config,
                        apply=args.apply,
                        force=args.force,
                    )
                )
            except ValueError as exc:
                parser.error(str(exc))
        if args.doctor_command == "roms":
            raise SystemExit(
                _run_doctor_roms_command(
                    config_path=args.config,
                    verbose=args.verbose,
                    verify=args.verify,
                )
            )
        if args.doctor_command == "firmware":
            raise SystemExit(
                _run_doctor_firmware_command(
                    config_path=args.config,
                    verbose=args.verbose,
                    verify=args.verify,
                )
            )
        if args.doctor_command == "all":
            raise SystemExit(
                _run_doctor_all_command(
                    config_path=args.config,
                    verbose=args.verbose,
                    verify=args.verify,
                )
            )


if __name__ == "__main__":
    main()
