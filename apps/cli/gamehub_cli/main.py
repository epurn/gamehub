from __future__ import annotations

import argparse
from pathlib import Path

try:
    import typer
except ModuleNotFoundError:
    typer = None

from .config import load_config
from .sync import run_sync

if typer is not None:
    app = typer.Typer(add_completion=False, no_args_is_help=True)

    @app.callback()
    def root() -> None:
        """GAMEHUB CLI entrypoint."""
        return

    @app.command()
    def sync(
        config: Path | None = typer.Option(None, "--config", help="Path to config TOML"),
        dry_run: bool = typer.Option(False, "--dry-run", help="Plan only; do not download or modify Steam"),
        verbose: bool = typer.Option(False, "--verbose", help="Enable verbose logging"),
        verify: bool = typer.Option(False, "--verify", help="Re-hash local files before diffing"),
        skip_steam: bool = typer.Option(False, "--skip-steam", help="Skip Steam lifecycle and update hooks"),
        require_steam_closed: bool = typer.Option(
            False,
            "--require-steam-closed",
            help="Fail if Steam cannot be closed before config writes",
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
            )
        )
else:
    app = None


def main() -> None:
    if app is not None:
        app()
        return

    parser = argparse.ArgumentParser(prog="gamehub")
    subparsers = parser.add_subparsers(dest="command", required=True)
    sync_parser = subparsers.add_parser("sync")
    sync_parser.add_argument("--config", type=Path, default=None)
    sync_parser.add_argument("--dry-run", action="store_true")
    sync_parser.add_argument("--verbose", action="store_true")
    sync_parser.add_argument("--verify", action="store_true")
    sync_parser.add_argument("--skip-steam", action="store_true")
    sync_parser.add_argument("--require-steam-closed", action="store_true")
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
            )
        )


if __name__ == "__main__":
    main()
