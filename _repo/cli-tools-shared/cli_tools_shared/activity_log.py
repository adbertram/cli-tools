"""Centralized activity logging for CLI tools.

Provides an always-on file-based logger that any CLI tool can use to track
operational activity. Writes to a shared rotating log file without interfering
with stdout/stderr stream separation.
"""

import logging
import os
import platform
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _get_log_dir() -> Path:
    """Return the platform-appropriate log directory."""
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "cli-tools"
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "cli-tools"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "cli-tools"


_LOG_DIR = _get_log_dir()
_LOG_FILE = _LOG_DIR / "cli_tool_activity.txt"
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_BACKUP_COUNT = 3
_FORMAT = "%(asctime)s [%(tool_name)s] %(levelname)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_initialized_loggers: set[str] = set()


class _ToolNameFilter(logging.Filter):
    """Injects tool_name into log records."""

    def __init__(self, tool_name: str) -> None:
        super().__init__()
        self.tool_name = tool_name

    def filter(self, record: logging.LogRecord) -> bool:
        record.tool_name = self.tool_name  # type: ignore[attr-defined]
        return True


def get_activity_logger(tool_name: str) -> logging.Logger:
    """Return a logger that writes to the shared CLI activity log file.

    Args:
        tool_name: Identifier for the CLI tool (e.g. "bricklink", "shippo").

    Returns:
        A configured ``logging.Logger`` instance. Safe to call multiple times
        with the same *tool_name* — duplicate handlers are prevented.
    """
    logger_name = f"activity.{tool_name}"

    if logger_name in _initialized_loggers:
        return logging.getLogger(logger_name)

    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        handler = RotatingFileHandler(
            _LOG_FILE,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT))
        handler.addFilter(_ToolNameFilter(tool_name))
        logger.addHandler(handler)
    except Exception:
        # Logging failures must never crash CLI tools.
        pass

    _initialized_loggers.add(logger_name)
    return logger
