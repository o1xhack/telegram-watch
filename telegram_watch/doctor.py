"""Doctor command implementation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from rich.console import Console
from rich.table import Table

from .config import Config
from .storage import db_session


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def run_doctor(config: Config) -> None:
    """Validate config and local environment."""
    console = Console()
    checks: list[CheckResult] = []
    checks.append(CheckResult("config", True, "config parsed successfully"))

    checks.extend(
        [
            _check_dir("session dir", config.telegram.session_file.parent),
            _check_dir("media dir", config.storage.media_dir),
            _check_dir("reports dir", config.reporting.reports_dir),
        ]
    )
    if config.sender is not None:
        checks.append(_check_dir("sender session dir", config.sender.session_file.parent))

    checks.append(_check_db(config))

    table = Table(title="telegram-watch doctor", show_lines=False)
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Detail")
    success = True
    for result in checks:
        status = "[green]OK[/green]" if result.ok else "[red]FAIL[/red]"
        table.add_row(result.name, status, result.detail)
        success &= result.ok

    console.print(table)
    if not success:
        raise SystemExit("doctor failed")


def _check_dir(label: str, path: Path) -> CheckResult:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return CheckResult(label, False, f"cannot create {path}: {exc}")
    return CheckResult(label, True, f"{path}")


def _check_db(config: Config) -> CheckResult:
    try:
        with db_session(config.storage.db_path) as conn:
            conn.execute("SELECT 1")
    except Exception as exc:  # pragma: no cover - surfaces in console only
        return CheckResult("database", False, f"{exc}")
    return CheckResult("database", True, f"{config.storage.db_path}")
