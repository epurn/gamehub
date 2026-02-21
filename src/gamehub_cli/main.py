from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .common.config import load_config
from .controllers.launch import run_controller_launch
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
            help="Overwrite default controller profiles during sync",
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
    ) -> None:
        raise typer.Exit(code=run_controller_launch(payload_token=payload, config_path=config))
else:
    app = None


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
    sync_parser.add_argument("--reseed-profiles", action="store_true")
    controller_launch_parser = subparsers.add_parser("controller-launch", help=argparse.SUPPRESS)
    controller_launch_parser.add_argument("--payload", required=True, help=argparse.SUPPRESS)
    controller_launch_parser.add_argument("--config", type=Path, default=None, help=argparse.SUPPRESS)
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
        raise SystemExit(run_controller_launch(payload_token=args.payload, config_path=args.config))


if __name__ == "__main__":
    main()
