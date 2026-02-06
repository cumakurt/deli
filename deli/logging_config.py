"""Structured logging configuration for deli."""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

LOG_LEVEL_ENV = "DELI_LOG_LEVEL"
LOG_FORMAT_ENV = "DELI_LOG_FORMAT"  # "json" | "text" (default)


def get_logger(name: str) -> logging.Logger:
    """Return a logger for the given module name. Configures root deli logger on first use."""
    logger = logging.getLogger("deli" if name == "deli" else f"deli.{name}")
    if not logger.handlers and logger.level == logging.NOTSET:
        _configure_deli_logging()
    return logger


def _configure_deli_logging() -> None:
    root = logging.getLogger("deli")
    if root.handlers:
        return
    level_name = (os.environ.get(LOG_LEVEL_ENV) or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root.setLevel(level)
    fmt_env = (os.environ.get(LOG_FORMAT_ENV) or "text").lower()
    if fmt_env == "json":
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(_JsonFormatter())
    else:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        )
    root.addHandler(handler)


class _JsonFormatter(logging.Formatter):
    """Simple JSON log formatter for structured logging (e.g. SIEM)."""

    def format(self, record: logging.LogRecord) -> str:
        import json
        obj: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt or "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(obj, ensure_ascii=False)
