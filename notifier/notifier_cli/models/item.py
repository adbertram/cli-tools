"""Models for Notifier CLI.

Models for macOS desktop notifications via terminal-notifier.
"""
from typing import Optional

from .base import CLIModel


class AuthStatus(CLIModel):
    """Authentication/installation status for terminal-notifier."""

    authenticated: bool
    terminal_notifier_path: Optional[str] = None
    version: Optional[str] = None
    message: Optional[str] = None


class SendResult(CLIModel):
    """Result of sending a notification."""

    success: bool
    message: Optional[str] = None
