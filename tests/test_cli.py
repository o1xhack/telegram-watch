from __future__ import annotations

from telegram_watch.cli import _confirm_retention, build_parser


def test_confirm_retention_auto_confirm_bypasses_prompt() -> None:
    assert _confirm_retention(365, auto_confirm=True) is True


def test_cleanup_replies_parser_defaults() -> None:
    parser = build_parser()
    assert parser.prog == "tgwatch"
    args = parser.parse_args(["cleanup-replies", "--config", "config.toml"])
    assert args.command == "cleanup-replies"
    assert args.apply is False
    assert args.no_backup is False
