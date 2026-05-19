"""Debug logging for PayPal CLI.

Provides file-based logging for debugging.
Log file is cleared at the start of each major operation.
"""
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


class Logger:
    """Simple file-based logger for debugging."""

    def __init__(self, log_file: str = "paypal-debug.log"):
        """Initialize logger with log file path.

        Args:
            log_file: Path to log file (relative to CLI directory or absolute)
        """
        # Store log file in the paypal_cli directory
        cli_dir = Path(__file__).parent
        self.log_path = cli_dir / log_file
        self._enabled = True

    def enable(self):
        """Enable logging."""
        self._enabled = True

    def disable(self):
        """Disable logging."""
        self._enabled = False

    def clear(self):
        """Clear the log file."""
        if self.log_path.exists():
            self.log_path.unlink()

    def _write(self, level: str, message: str, data: Optional[dict] = None):
        """Write a log entry."""
        if not self._enabled:
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        entry = f"[{timestamp}] [{level}] {message}"

        if data:
            # Format data as indented key-value pairs
            for key, value in data.items():
                # Truncate long values
                str_value = str(value)
                if len(str_value) > 500:
                    str_value = str_value[:500] + "..."
                entry += f"\n    {key}: {str_value}"

        entry += "\n"

        with open(self.log_path, "a") as f:
            f.write(entry)

    def debug(self, message: str, data: Optional[dict] = None):
        """Log debug message."""
        self._write("DEBUG", message, data)

    def info(self, message: str, data: Optional[dict] = None):
        """Log info message."""
        self._write("INFO", message, data)

    def warn(self, message: str, data: Optional[dict] = None):
        """Log warning message."""
        self._write("WARN", message, data)

    def error(self, message: str, data: Optional[dict] = None):
        """Log error message."""
        self._write("ERROR", message, data)

    def step(self, step_name: str, details: Optional[str] = None):
        """Log a workflow step."""
        msg = f"STEP: {step_name}"
        if details:
            msg += f" - {details}"
        self._write("STEP", msg)


# Global logger instance
_logger: Optional[Logger] = None


def get_logger() -> Logger:
    """Get or create the global logger instance."""
    global _logger
    if _logger is None:
        _logger = Logger()
    return _logger
