from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .common.config import GamehubConfig, load_config
from .controllers.convergence import run_controller_doctor
from .controllers.launch import run_controller_launch
from .steam import build_context, discover_deck_steam_input_roots, discover_steam_id, discover_userdata_dir
from .sync import run_sync

typer: Any
_typer: Any | None
try:
    import typer as _typer
except ModuleNotFoundError:
    _typer = None
typer = _typer

if typer is not None:
    app = typer.Typer(add_completion=False, no_args_is_help=True)

    @app.callback()
    def root() -> None:
        """GAMEHUB CLI entrypoint."""
        return

    @app.command()
    def sync(
        config: Path | None = typer.Option(
            None,
            "--config",
            help="Path to config TOML (default lookup: ./config.toml then ~/.gamehub/config.toml)",
        ),
        dry_run: bool = typer.Option(False, "--dry-run", help="Plan only; do not download or modify Steam"),
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
        loaded = load_config(config)
        raise typer.Exit(
            code=run_sync(
                config=loaded,
                dry_run=dry_run,
                verbose=verbose,
                verify=verify,
                require_steam_closed=require_steam_closed,
                skip_steam=skip_steam,
                skip_steam_relaunch=skip_steam_relaunch,
                reseed_profiles=reseed_profiles,
            )
        )

    @app.command("controller-launch", hidden=True)
    def controller_launch(
        payload: str = typer.Option(..., "--payload", help="Encoded controller-launch payload."),
        config: Path | None = typer.Option(
            None,
            "--config",
            help="Optional config TOML path override for controller launch.",
        ),
        audit: bool = typer.Option(False, "--audit", help="Print controller profile apply diagnostics."),
    ) -> None:
        raise typer.Exit(code=run_controller_launch(payload_token=payload, config_path=config, audit=audit))

    @app.command()
    def doctor(
        config: Path | None = typer.Option(
            None,
            "--config",
            help="Path to config TOML (default lookup: ./config.toml then ~/.gamehub/config.toml)",
        ),
        controllers: bool = typer.Option(False, "--controllers", help="Run controller convergence diagnostics."),
        apply: bool = typer.Option(False, "--apply", help="Apply safe controller repairs."),
        force: bool = typer.Option(
            False,
            "--force",
            help="With --apply, archive and clean up unmanaged profile files as well.",
        ),
    ) -> None:
        if not controllers:
            raise typer.BadParameter("No doctor checks selected. Use --controllers.")
        if force and not apply:
            raise typer.BadParameter("--force requires --apply.")
        loaded = load_config(config)
        roots, note = _discover_controller_doctor_steam_roots(loaded)
        raise typer.Exit(
            code=run_controller_doctor(
                loaded,
                apply=apply,
                force=force,
                steam_roots=roots,
                steam_discovery_note=note,
            )
        )
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
    sync_parser = subparsers.add_parser("sync")
    sync_parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config TOML (default lookup: ./config.toml then ~/.gamehub/config.toml)",
    )
    sync_parser.add_argument("--dry-run", action="store_true")
    sync_parser.add_argument("--verbose", action="store_true")
    sync_parser.add_argument("--verify", action="store_true")
    sync_parser.add_argument("--skip-steam", action="store_true")
    sync_parser.add_argument("--skip-steam-relaunch", action="store_true")
    sync_parser.add_argument("--require-steam-closed", action="store_true")
    sync_parser.add_argument(
        "--reseed-profiles", action="store_true", help="Overwrite managed profile/template files during sync"
    )
    controller_launch_parser = subparsers.add_parser("controller-launch", help=argparse.SUPPRESS)
    controller_launch_parser.add_argument("--payload", required=True, help=argparse.SUPPRESS)
    controller_launch_parser.add_argument("--config", type=Path, default=None, help=argparse.SUPPRESS)
    controller_launch_parser.add_argument("--audit", action="store_true", help=argparse.SUPPRESS)
    doctor_parser = subparsers.add_parser("doctor")
    doctor_parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config TOML (default lookup: ./config.toml then ~/.gamehub/config.toml)",
    )
    doctor_parser.add_argument("--controllers", action="store_true")
    doctor_parser.add_argument("--apply", action="store_true")
    doctor_parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.command == "sync":
        loaded = load_config(args.config)
        raise SystemExit(
            run_sync(
                config=loaded,
                dry_run=args.dry_run,
                verbose=args.verbose,
                verify=args.verify,
                require_steam_closed=args.require_steam_closed,
                skip_steam=args.skip_steam,
                skip_steam_relaunch=args.skip_steam_relaunch,
                reseed_profiles=args.reseed_profiles,
            )
        )
    if args.command == "controller-launch":
        raise SystemExit(run_controller_launch(payload_token=args.payload, config_path=args.config, audit=args.audit))
    if args.command == "doctor":
        if not args.controllers:
            parser.error("doctor requires at least one check selector (use --controllers)")
        if args.force and not args.apply:
            parser.error("doctor --force requires --apply")
        loaded = load_config(args.config)
        roots, note = _discover_controller_doctor_steam_roots(loaded)
        raise SystemExit(
            run_controller_doctor(
                loaded,
                apply=args.apply,
                force=args.force,
                steam_roots=roots,
                steam_discovery_note=note,
            )
        )


if __name__ == "__main__":
    main()
