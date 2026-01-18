"""telegram_watch package exports."""

from __future__ import annotations

__all__ = [
    "load_config",
    "Config",
]

from .config import Config, load_config  # noqa: E402  (import after __all__)
