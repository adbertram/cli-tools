"""Client for managing the Cody cc-connect Slack bridge."""
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import (
    ActionResult,
    CheckResult,
    ConfigStatus,
    LogTail,
    ServiceStatus,
    SlackUserStatus,
    SlackVerification,
    TokenStatus,
)


class ClientError(Exception):
    """Custom exception for cc-connect Slack manager errors."""


class CcConnectSlackManagerClient:
    """Manage the local Cody cc-connect bridge."""

    TEAM_ID = "T0F2BD3QA"
    SLACK_PROFILE = "default"
    CONFIG_LINE_CHECKS = [
        ("reply-footer-disabled", "Reply footer disabled", "reply_footer = false"),
        ("context-indicator-disabled", "Context indicator disabled", "show_context_indicator = false"),
        ("compact-display-enabled", "Compact display enabled", 'mode = "compact"'),
        ("quiet-mode-enabled", "Quiet mode enabled", "quiet = true"),
        ("tool-messages-disabled", "Tool messages disabled", "tool_messages = false"),
        ("thinking-messages-disabled", "Thinking messages disabled", "thinking_messages = false"),
    ]

    def __init__(self):
        self.home = Path.home()
        self.cody_config_path = self._cody_config_path()
        self.cody_config = self._read_cody_config()
        paths = self._require_dict(self.cody_config, "paths")
        secrets = self._require_dict(self.cody_config, "secrets")
        channels = self._require_dict(self.cody_config, "channels")
        slack = self._require_dict(channels, "slack")
        bridge = self._require_dict(slack, "bridge")
        self.launch_agent_label = self._require_str(bridge, "label")
        self.app_id = self._require_str(slack, "app_id")
        self.bot_user_id = self._require_str(slack, "bot_user_id")
        self.adam_user_id = self._require_str(slack, "default_user_id")
        self.dm_channel_id = self._require_str(slack, "default_dm_channel_id")
        self.keychain_path = Path(self._require_str(secrets, "keychain_path"))
        self.bot_token_config = self._require_dict(secrets, "slack_bot_token")
        self.app_token_config = self._require_dict(secrets, "slack_app_token")
        self.config_path = Path(self._require_str(paths, "cc_connect_config"))
        self.wrapper_path = Path(self._require_str(paths, "cc_connect_runner"))
        self.stdout_log_path = Path(self._require_str(paths, "cc_connect_logs_dir")) / "cody.out.log"
        self.stderr_log_path = Path(self._require_str(paths, "cc_connect_logs_dir")) / "cody.err.log"
        self.plist_path = (
            self.home
            / "Library"
            / "LaunchAgents"
            / f"{self.launch_agent_label}.plist"
        )
        self.data_dir = Path(self._require_str(paths, "cc_connect_data_dir"))

    def _cody_config_path(self) -> Path:
        value = os.environ.get("CODY_CONFIG_PATH")
        if value is None:
            return self.home / ".codex" / "cody" / "configuration.json"
        stripped = value.strip()
        if stripped == "":
            raise ClientError("CODY_CONFIG_PATH is empty")
        return Path(stripped)

    def _read_cody_config(self) -> Dict[str, Any]:
        if not self.cody_config_path.exists():
            raise ClientError(f"Cody configuration is missing: {self.cody_config_path}")
        data = json.loads(self.cody_config_path.read_text())
        if not isinstance(data, dict):
            raise ClientError("Cody configuration must be a JSON object")
        self._validate_cody_config(data)
        return data

    def _validate_cody_config(self, data: Dict[str, Any]) -> None:
        version = data.get("version")
        if version != 1:
            raise ClientError("Cody configuration version must be 1")
        identity = self._require_dict(data, "identity")
        self._require_str(identity, "name")
        self._require_str(identity, "email")
        paths = self._require_dict(data, "paths")
        for key in ("cc_connect_config", "cc_connect_runner", "cc_connect_data_dir", "cc_connect_logs_dir"):
            self._require_str(paths, key)
        sessions = self._require_dict(data, "sessions")
        self._require_list(sessions, "readable_sources")
        secrets = self._require_dict(data, "secrets")
        self._require_str(secrets, "keychain_path")
        for key in ("slack_bot_token", "slack_app_token", "email_password"):
            token = self._require_dict(secrets, key)
            self._require_str(token, "service")
            self._require_str(token, "account")
        channels = self._require_dict(data, "channels")
        slack = self._require_dict(channels, "slack")
        self._require_bool(slack, "enabled")
        for key in ("app_id", "bot_user_id", "default_user_id", "default_dm_channel_id"):
            self._require_str(slack, key)
        bridge = self._require_dict(slack, "bridge")
        self._require_str(bridge, "label")
        email = self._require_dict(channels, "email")
        self._require_bool(email, "enabled")
        self._require_str(email, "session_key_prefix")
        headers = self._require_dict(email, "headers")
        self._require_str(headers, "channel")
        self._require_str(headers, "session_key")

    def _require_dict(self, data: Dict[str, Any], key: str) -> Dict[str, Any]:
        value = data.get(key)
        if not isinstance(value, dict):
            raise ClientError(f"Cody configuration key {key!r} must be an object")
        return value

    def _require_list(self, data: Dict[str, Any], key: str) -> List[Any]:
        value = data.get(key)
        if not isinstance(value, list):
            raise ClientError(f"Cody configuration key {key!r} must be a list")
        return value

    def _require_str(self, data: Dict[str, Any], key: str) -> str:
        value = data.get(key)
        if not isinstance(value, str) or value == "":
            raise ClientError(f"Cody configuration key {key!r} must be a non-empty string")
        return value

    def _require_bool(self, data: Dict[str, Any], key: str) -> bool:
        value = data.get(key)
        if not isinstance(value, bool):
            raise ClientError(f"Cody configuration key {key!r} must be a boolean")
        return value

    def _run(self, args: List[str], check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(args, capture_output=True, text=True)
        if check and result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise ClientError(detail)
        return result

    def _launchctl_target(self) -> str:
        return f"gui/{os.getuid()}/{self.launch_agent_label}"

    def _keychain_token(self, token_config: Dict[str, Any]) -> str:
        account = self._require_str(token_config, "account")
        service = self._require_str(token_config, "service")
        result = self._run(
            [
                "security",
                "find-generic-password",
                "-a",
                account,
                "-s",
                service,
                "-w",
                str(self.keychain_path),
            ]
        )
        token = result.stdout.strip()
        if not token:
            raise ClientError(f"Keychain service {service} returned an empty token")
        return token

    def _keychain_token_present(self, token_config: Dict[str, Any]) -> bool:
        account = self._require_str(token_config, "account")
        service = self._require_str(token_config, "service")
        result = self._run(
            [
                "security",
                "find-generic-password",
                "-a",
                account,
                "-s",
                service,
                "-w",
                str(self.keychain_path),
            ],
            check=False,
        )
        return result.returncode == 0 and bool(result.stdout.strip())

    def _slack_user(self, user_id: str) -> SlackUserStatus:
        result = self._run(
            [
                "slack",
                "--profile",
                self.SLACK_PROFILE,
                "--no-cache",
                "users",
                "get",
                user_id,
            ]
        )
        data = json.loads(result.stdout)
        profile = data.get("profile", {})
        return SlackUserStatus(
            id=data["id"],
            name=data["name"],
            deleted=data["deleted"],
            is_bot=data["is_bot"],
            is_app_user=data["is_app_user"],
            api_app_id=profile.get("api_app_id"),
            bot_id=profile.get("bot_id"),
            image_512=profile.get("image_512"),
        )

    def service_status(self) -> ServiceStatus:
        result = self._run(["launchctl", "print", self._launchctl_target()], check=False)
        loaded = result.returncode == 0
        state: Optional[str] = None
        pid: Optional[int] = None

        if loaded:
            state_match = re.search(r"state = (\w+)", result.stdout)
            pid_match = re.search(r"pid = (\d+)", result.stdout)
            state = state_match.group(1) if state_match else None
            pid = int(pid_match.group(1)) if pid_match else None

        return ServiceStatus(
            label=self.launch_agent_label,
            loaded=loaded,
            running=state == "running",
            pid=pid,
            state=state,
            plist_path=str(self.plist_path),
            config_path=str(self.config_path),
            wrapper_path=str(self.wrapper_path),
            stdout_log_path=str(self.stdout_log_path),
            stderr_log_path=str(self.stderr_log_path),
        )

    def service_start(self) -> ActionResult:
        self._run(
            [
                "launchctl",
                "bootstrap",
                f"gui/{os.getuid()}",
                str(self.plist_path),
            ]
        )
        return ActionResult(
            action="service_start",
            success=True,
            message=f"Bootstrapped {self.launch_agent_label}",
        )

    def service_stop(self) -> ActionResult:
        self._run(["launchctl", "bootout", self._launchctl_target()])
        return ActionResult(
            action="service_stop",
            success=True,
            message=f"Booted out {self.launch_agent_label}",
        )

    def service_restart(self) -> ActionResult:
        self._run(["launchctl", "kickstart", "-k", self._launchctl_target()])
        return ActionResult(
            action="service_restart",
            success=True,
            message=f"Restarted {self.launch_agent_label}",
        )

    def log_tail(self, stream: str, lines: int) -> LogTail:
        if stream not in {"stdout", "stderr"}:
            raise ClientError("stream must be stdout or stderr")
        path = self.stdout_log_path if stream == "stdout" else self.stderr_log_path
        result = self._run(["tail", "-n", str(lines), str(path)])
        return LogTail(path=str(path), lines=result.stdout.splitlines())

    def config_status(self) -> ConfigStatus:
        return ConfigStatus(
            config_path=str(self.config_path),
            wrapper_path=str(self.wrapper_path),
            launch_agent_plist_path=str(self.plist_path),
            data_dir=str(self.data_dir),
            app_id=self.app_id,
            bot_user_id=self.bot_user_id,
            dm_channel_id=self.dm_channel_id,
            adam_user_id=self.adam_user_id,
        )

    def token_status(self) -> List[TokenStatus]:
        return [
            TokenStatus(
                service=self._require_str(self.bot_token_config, "service"),
                account=self._require_str(self.bot_token_config, "account"),
                present=self._keychain_token_present(self.bot_token_config),
            ),
            TokenStatus(
                service=self._require_str(self.app_token_config, "service"),
                account=self._require_str(self.app_token_config, "account"),
                present=self._keychain_token_present(self.app_token_config),
            ),
        ]

    def _config_has_line(self, expected_line: str) -> bool:
        return expected_line in self._config_lines()

    def _config_lines(self) -> set[str]:
        return {line.strip() for line in self.config_path.read_text().splitlines()}

    def slack_verify(self) -> SlackVerification:
        bot_user = self._slack_user(self.bot_user_id)
        if bot_user.api_app_id != self.app_id:
            raise ClientError(
                f"Cody bot {bot_user.id} belongs to Slack app {bot_user.api_app_id}; expected {self.app_id}"
            )
        return SlackVerification(
            profile=self.SLACK_PROFILE,
            app_id=self.app_id,
            bot_user=bot_user,
            dm_channel_id=self.dm_channel_id,
        )

    def send_test_message(self, text: str) -> ActionResult:
        token = self._keychain_token(self.bot_token_config)
        payload = urllib.parse.urlencode(
            {
                "channel": self.dm_channel_id,
                "text": text,
            }
        ).encode()
        request = urllib.request.Request(
            "https://slack.com/api/chat.postMessage",
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode())
        if not data["ok"]:
            raise ClientError(f"Slack chat.postMessage failed: {data['error']}")
        return ActionResult(
            action="send_test_message",
            success=True,
            message=f"Sent message to {self.dm_channel_id} at {data['ts']}",
        )

    def list_checks(self) -> List[CheckResult]:
        service = self.service_status()
        tokens = self.token_status()
        config = self.config_status()
        slack = self.slack_verify()

        config_lines = self._config_lines()
        config_line_checks = [
            CheckResult(
                id=check_id,
                name=name,
                ok=expected_line in config_lines,
                detail=config.config_path,
            )
            for check_id, name, expected_line in self.CONFIG_LINE_CHECKS
        ]
        return [
            CheckResult(
                id="service-running",
                name="LaunchAgent running",
                ok=service.running,
                detail=f"{service.label} state={service.state} pid={service.pid}",
            ),
            CheckResult(
                id="config-present",
                name="Config file exists",
                ok=Path(config.config_path).exists(),
                detail=config.config_path,
            ),
            CheckResult(
                id="wrapper-present",
                name="Wrapper script exists",
                ok=Path(config.wrapper_path).exists(),
                detail=config.wrapper_path,
            ),
            *config_line_checks,
            CheckResult(
                id="bot-token-present",
                name="Bot token in Keychain",
                ok=tokens[0].present,
                detail=tokens[0].service,
            ),
            CheckResult(
                id="app-token-present",
                name="App token in Keychain",
                ok=tokens[1].present,
                detail=tokens[1].service,
            ),
            CheckResult(
                id="new-bot-active",
                name="Cody bot active",
                ok=not slack.bot_user.deleted and slack.bot_user.is_bot,
                detail=f"{slack.bot_user.id} name={slack.bot_user.name}",
            ),
        ]


_client: Optional[CcConnectSlackManagerClient] = None


def get_client() -> CcConnectSlackManagerClient:
    """Get or create the global manager client."""
    global _client
    if _client is None:
        _client = CcConnectSlackManagerClient()
    return _client
