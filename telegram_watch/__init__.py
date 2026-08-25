"""telegram_watch package exports."""

from __future__ import annotations

__version__ = "1.8.1"

from .telethon_compat import install_message_constructor_compat  # noqa: E402

install_message_constructor_compat()

__all__ = [
    "__version__",
    "load_config",
    "Config",
]

from .config import Config, load_config  # noqa: E402  (import after __all__)
