"""Command-line interface for telegram-watch."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from typing import Sequence

from .config import Config, ConfigError, load_config
from .doctor import run_doctor
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
        "--push",
        action="store_true",
        help="Also push the generated report/messages to the control chat",
    )

    subparsers.add_parser(
        "run",
        help="Run watcher daemon",
        parents=[common],
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if args.command == "doctor":
        config = _load_config_or_exit(parser, args.config)
        run_doctor(config)
        return 0
    elif args.command == "once":
        config = _load_config_or_exit(parser, args.config)
        since = parse_since_spec(args.since, now=utc_now())
        return asyncio.run(_run_once_command(config, since, push=args.push))
    elif args.command == "run":
        config = _load_config_or_exit(parser, args.config)
        if not _confirm_retention(config.reporting.retention_days):
            logging.getLogger(__name__).warning("Run cancelled by user.")
            return 1
        return asyncio.run(_run_daemon_command(config))
    else:  # pragma: no cover - argparse ensures command
        parser.error(f"Unknown command {args.command}")


def _load_config_or_exit(parser: argparse.ArgumentParser, path: Path) -> Config:
    try:
        return load_config(path)
    except ConfigError as exc:
        parser.error(str(exc))


async def _run_once_command(config, since, push: bool = False):
    report_path = await run_once(config, since, push=push)
    logging.getLogger(__name__).info("Report generated at %s", report_path)
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
