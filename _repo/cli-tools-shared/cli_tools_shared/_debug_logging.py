"""Shared debug logging setup for CLI tools modules."""

import logging
import os
import sys


def configure_debug_logger(logger: logging.Logger) -> None:
    """Configure debug logging to stderr when DEBUG=1 or CLI_TOOLS_DEBUG=1."""
    if os.environ.get("DEBUG") == "1" or os.environ.get("CLI_TOOLS_DEBUG") == "1":
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(
            "[%(name)s] %(levelname)s: %(message)s"
        ))
        logger.setLevel(logging.DEBUG)
        if not logger.handlers:
            logger.addHandler(handler)


def get_debug_logger(name: str) -> logging.Logger:
    """Create and configure a debug logger in one call."""
    logger = logging.getLogger(name)
    configure_debug_logger(logger)
    return logger
