"""Application logging setup.

Deliberately plain: a single stream handler writing to stdout, which systemd
captures into the journal on EC2. No log files to rotate, no external log
shipper.

Secret safety: this module never logs headers, request bodies or credentials.
Handlers elsewhere log only booleans about credential presence.
"""

from __future__ import annotations

import logging
import os
import sys

_CONFIGURED = False

# Access logs are emitted by our own middleware with latency attached, so
# uvicorn's duplicate access log is silenced.
_NOISY_LOGGERS = ("uvicorn.access", "httpx", "httpcore")


def log_level() -> str:
    return (os.getenv("AUTOSEARCH_LOG_LEVEL") or "INFO").strip().upper()


def configure_logging() -> None:
    """Idempotent root logging configuration."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = getattr(logging, log_level(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    _CONFIGURED = True
