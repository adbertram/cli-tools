"""Models for the Cody cc-connect Slack bridge manager."""
from typing import List, Optional

from .base import CLIModel


class ActionResult(CLIModel):
    """Result from a management command."""

    action: str
    success: bool
    message: str


class ServiceStatus(CLIModel):
    """LaunchAgent status for the Cody cc-connect bridge."""

    label: str
    loaded: bool
    running: bool
    pid: Optional[int] = None
    state: Optional[str] = None
    plist_path: str
    config_path: str
    wrapper_path: str
    stdout_log_path: str
    stderr_log_path: str


class ConfigStatus(CLIModel):
    """Configured Cody bridge paths and Slack identifiers."""

    config_path: str
    wrapper_path: str
    launch_agent_plist_path: str
    data_dir: str
    app_id: str
    bot_user_id: str
    dm_channel_id: str
    adam_user_id: str


class TokenStatus(CLIModel):
    """Keychain-backed token status without secret values."""

    service: str
    account: str
    present: bool


class SlackUserStatus(CLIModel):
    """Slack user verification result."""

    id: str
    name: str
    deleted: bool
    is_bot: bool
    is_app_user: bool
    api_app_id: Optional[str] = None
    bot_id: Optional[str] = None
    image_512: Optional[str] = None


class SlackVerification(CLIModel):
    """Slack identity verification for Cody's Slack app."""

    profile: str
    app_id: str
    bot_user: SlackUserStatus
    dm_channel_id: str


class LogTail(CLIModel):
    """Tail output from a Cody bridge log."""

    path: str
    lines: List[str]


class CheckResult(CLIModel):
    """Single health check result."""

    id: str
    name: str
    ok: bool
    detail: str


__all__ = [
    "ActionResult",
    "CheckResult",
    "ConfigStatus",
    "LogTail",
    "ServiceStatus",
    "SlackUserStatus",
    "SlackVerification",
    "TokenStatus",
]
