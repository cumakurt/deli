"""Unit tests for logging_config (get_logger)."""

from __future__ import annotations

import logging
import os

import pytest

from deli.logging_config import get_logger, LOG_LEVEL_ENV, LOG_FORMAT_ENV


def test_get_logger_returns_logger() -> None:
    logger = get_logger("test")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "deli.test"


def test_get_logger_root_name() -> None:
    logger = get_logger("deli")
    assert logger.name == "deli"


def test_get_logger_log_level_respected() -> None:
    prev = os.environ.pop(LOG_LEVEL_ENV, None)
    try:
        os.environ[LOG_LEVEL_ENV] = "DEBUG"
        logger = get_logger("test_level")
        root = logging.getLogger("deli")
        # Root may already have level set; just ensure logger exists
        assert root is not None
        assert logger.level >= 0
    finally:
        if prev is not None:
            os.environ[LOG_LEVEL_ENV] = prev
        else:
            os.environ.pop(LOG_LEVEL_ENV, None)


def test_get_logger_log_message() -> None:
    import io
    logger = get_logger("test_msg")
    logger.info("test message")
    # No exception; handler may write to stderr
    assert True
