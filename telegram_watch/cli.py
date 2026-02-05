"""Command-line interface for telegram-watch."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from typing import Sequence
from rich.console import Console

from .config import Config, ConfigError, load_config
from .migration import detect_migration_needed, migrate_config
from .doctor import run_doctor
from .gui import run_gui
from .runner import run_daemon, run_once
from .timeutils import parse_since_spec, utc_now


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="telegram_watch",
        description="Telegram user watcher",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to config TOML file",
    )
    common.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "doctor",
        help="Validate config and environment",
        parents=[common],
    )

    once_parser = subparsers.add_parser(
        "once",
        help="Fetch a window and generate a report",
        parents=[common],
    )
    once_parser.add_argument(
        "--since",
        required=True,
        help="Window spec (e.g. 10m, 2h, or ISO timestamp)",
    )
    once_parser.add_argument(
        "--target",
        help="Limit to a single target (target name or target_chat_id)",
    )
    once_parser.add_argument(
        "--push",
        action="store_true",
        help="Also push the generated report/messages to the control chat",
    )

    subparsers.add_parser(
        "run",
        help="Run watcher daemon",
        parents=[common],
    )

    gui_parser = subparsers.add_parser(
        "gui",
        help="Launch local GUI to edit config",
    )
    gui_parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity",
    )
    gui_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind the GUI server",
    )
    gui_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to bind the GUI server",
    )
    gui_parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.toml"),
        help="Path to config TOML file (default: config.toml)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("telethon").setLevel(logging.WARNING)
    if args.command == "doctor":
        config = _load_config_or_exit(parser, args.config, command=args.command)
        run_doctor(config)
        return 0
    elif args.command == "once":
        config = _load_config_or_exit(parser, args.config, command=args.command)
        since = parse_since_spec(args.since, now=utc_now())
        return asyncio.run(
            _run_once_command(
                config,
                since,
                since_label=args.since,
                push=args.push,
                target_selector=args.target,
            )
        )
    elif args.command == "run":
        config = _load_config_or_exit(parser, args.config, command=args.command)
        if not _confirm_retention(config.reporting.retention_days):
            logging.getLogger(__name__).warning("Run cancelled by user.")
            return 1
        return asyncio.run(_run_daemon_command(config))
    elif args.command == "gui":
        run_gui(args.config, host=args.host, port=args.port)
        return 0
    else:  # pragma: no cover - argparse ensures command
        parser.error(f"Unknown command {args.command}")


def _load_config_or_exit(
    parser: argparse.ArgumentParser, path: Path, *, command: str
) -> Config:
    try:
        return load_config(path)
    except ConfigError as exc:
        if command in {"run", "once"}:
            Console().print(f"[bold red]Config error:[/bold red] {exc}")
            if _maybe_migrate_config(path):
                Console().print(
                    "[green]Migration completed. Review config.toml and rerun the command.[/green]"
                )
                raise SystemExit(0)
            raise SystemExit(2)
        parser.error(str(exc))


def _maybe_migrate_config(path: Path) -> bool:
    needs, reason = detect_migration_needed(path)
    if not needs:
        return False
    prompt = (
        f"Config migration needed ({reason}). Create a backup and rewrite config.toml now? [y/N]: "
    )
    try:
        answer = input(prompt)
    except EOFError:
        return False
    if answer.strip().lower() not in {"y", "yes"}:
        return False
    result = migrate_config(path)
    if not result.ok:
        Console().print(f"[bold red]Migration failed:[/bold red] {result.status}")
        return False
    if result.backup_path:
        Console().print(f"Backup saved to {result.backup_path.name}.")
    return True


async def _run_once_command(
    config,
    since,
    since_label=None,
    push: bool = False,
    target_selector: str | None = None,
):
    try:
        report_paths = await run_once(
            config,
            since,
            push=push,
            since_label=since_label,
            target_selector=target_selector,
        )
    except ValueError as exc:
        Console().print(f"[bold red]Run once error:[/bold red] {exc}")
        raise SystemExit(2)
    logger = logging.getLogger(__name__)
    for report_path in report_paths:
        logger.info("Report generated at %s", report_path)
    return 0


async def _run_daemon_command(config):
    await run_daemon(config)
    return 0


def _confirm_retention(retention_days: int) -> bool:
    if retention_days <= 180:
        return True
    prompt = (
        f"reporting.retention_days is set to {retention_days} days. "
        "This may consume significant disk space. Continue? [y/N]: "
    )
    try:
        answer = input(prompt)
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
