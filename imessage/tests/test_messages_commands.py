"""Tests for the messages send path and the Messages Automation (TCC) hardening.

These tests mock at the subprocess layer (``subprocess.run`` inside
applescript.py) so they simulate macOS ``open`` + osascript / Apple Events
behavior without needing real Automation consent or sending a real text --
mirroring the pattern in ``test_contacts_commands.py``.
"""
import json
import subprocess

import pytest
from typer.testing import CliRunner

from imessage_cli.applescript import (
    AutomationPermissionError,
    launch_app,
    probe_automation,
)
from imessage_cli.client import ClientError, ImessageClient
from imessage_cli.main import app


# osascript denial text for a missing Automation grant (error -1743).
NOT_AUTHORIZED_ERROR = (
    "execution error: Not authorized to send Apple events to Messages. (-1743)"
)


def _completed_process(returncode: int, stdout: str = "", stderr: str = "", args=None):
    return subprocess.CompletedProcess(
        args=args or ["osascript", "-e", "irrelevant"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


class RecordingSubprocess:
    """Fake ``subprocess.run`` that records calls and replays ordered responses.

    ``responses`` is consumed one per call. Each entry is either a
    ``CompletedProcess`` (returned) or an ``Exception`` instance (raised, e.g.
    ``subprocess.TimeoutExpired``) so the automation-block path can be
    simulated. If exhausted, the last response is reused.
    """

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        response = self.responses[index]
        if isinstance(response, BaseException):
            raise response
        return response

    @property
    def osascript_scripts(self):
        """The ``-e`` AppleScript source for every osascript call."""
        return [
            cmd[2]
            for cmd in self.calls
            if len(cmd) >= 3 and cmd[0] == "osascript" and cmd[1] == "-e"
        ]

    @property
    def open_calls(self):
        """Every ``open ...`` invocation (LaunchServices launches)."""
        return [cmd for cmd in self.calls if cmd and cmd[0] == "open"]


# ==================== probe_automation unit tests ====================


def test_probe_automation_raises_on_timeout(monkeypatch):
    """A hung Apple Event (osascript timeout) means Automation is blocked."""
    fake = RecordingSubprocess(
        [subprocess.TimeoutExpired(cmd=["osascript"], timeout=3)]
    )
    monkeypatch.setattr(subprocess, "run", fake)

    with pytest.raises(AutomationPermissionError, match="Automation .* is not granted"):
        probe_automation("Messages")


def test_probe_automation_raises_on_not_authorized_denial(monkeypatch):
    """An explicit -1743 denial also raises AutomationPermissionError."""
    fake = RecordingSubprocess([_completed_process(1, stderr=NOT_AUTHORIZED_ERROR)])
    monkeypatch.setattr(subprocess, "run", fake)

    with pytest.raises(AutomationPermissionError, match="Automation .* is not granted"):
        probe_automation("Messages")


def test_probe_automation_passes_when_get_name_succeeds(monkeypatch):
    """rc=0 with the app name means Automation consent is granted -- no raise."""
    fake = RecordingSubprocess([_completed_process(0, stdout="Messages")])
    monkeypatch.setattr(subprocess, "run", fake)

    probe_automation("Messages")  # must not raise

    assert fake.osascript_scripts == ['tell application "Messages" to get name']


# ==================== launch_app unit test ====================


def test_launch_app_uses_open_background_argv(monkeypatch):
    """launch_app must use LaunchServices (open -g -a), not an Apple Event."""
    fake = RecordingSubprocess([_completed_process(0, args=["open", "-g", "-a", "Messages"])])
    monkeypatch.setattr(subprocess, "run", fake)

    launch_app("Messages")

    assert fake.calls == [["open", "-g", "-a", "Messages"]]


# ==================== send_message: fail-fast when blocked ====================


def test_send_message_fails_fast_when_automation_blocked(monkeypatch):
    """When the probe times out, send_message raises ClientError with the
    actionable guidance and NEVER executes the send AppleScript.
    """
    fake = RecordingSubprocess(
        [
            _completed_process(0, args=["open", "-g", "-a", "Messages"]),  # launch ok
            subprocess.TimeoutExpired(cmd=["osascript"], timeout=3),  # probe hangs
        ]
    )
    monkeypatch.setattr(subprocess, "run", fake)

    client = ImessageClient()
    with pytest.raises(ClientError, match="automation is not permitted"):
        client.send_message("+15551234567", "hi")

    # The send script (`send "..." to targetBuddy`) must never run.
    assert not any("send " in script for script in fake.osascript_scripts)
    # Only the launch (open) and the bounded probe were attempted.
    assert fake.open_calls == [["open", "-g", "-a", "Messages"]]


# ==================== send_message: happy path ====================


def test_send_message_happy_path_returns_success(monkeypatch):
    """launch ok -> probe ok -> send ok yields a successful SendResult, and the
    call order is open -> get name probe -> send.
    """
    fake = RecordingSubprocess(
        [
            _completed_process(0, args=["open", "-g", "-a", "Messages"]),  # launch
            _completed_process(0, stdout="Messages"),  # probe get name
            _completed_process(0, stdout=""),  # send
        ]
    )
    monkeypatch.setattr(subprocess, "run", fake)

    client = ImessageClient()
    result = client.send_message("+15551234567", "hi")

    assert result.success is True
    assert result.recipient == "+15551234567"

    assert fake.calls[0] == ["open", "-g", "-a", "Messages"]
    assert fake.osascript_scripts[0] == 'tell application "Messages" to get name'
    assert "send " in fake.osascript_scripts[1]
    assert "get name" in fake.osascript_scripts[0]


# ==================== send_message: genuine post-probe send failure ====================


def test_send_message_surfaces_real_send_failure(monkeypatch):
    """A send failure AFTER the probe passes must surface as ClientError, not be
    masked by the automation-permission branch.
    """
    fake = RecordingSubprocess(
        [
            _completed_process(0, args=["open", "-g", "-a", "Messages"]),  # launch
            _completed_process(0, stdout="Messages"),  # probe ok
            _completed_process(1, stderr="some error"),  # send fails
        ]
    )
    monkeypatch.setattr(subprocess, "run", fake)

    client = ImessageClient()
    with pytest.raises(ClientError, match="Failed to send message"):
        client.send_message("+15551234567", "hi")


# ==================== CLI end-to-end ====================


def test_messages_send_cli_blocked_exits_1_with_actionable_message(monkeypatch):
    """`imessage messages send` exits 1 with the actionable guidance when the
    Automation gate blocks the send.
    """
    fake = RecordingSubprocess(
        [
            _completed_process(0, args=["open", "-g", "-a", "Messages"]),  # launch ok
            subprocess.TimeoutExpired(cmd=["osascript"], timeout=3),  # probe hangs
        ]
    )
    monkeypatch.setattr(subprocess, "run", fake)

    result = CliRunner().invoke(app, ["messages", "send", "+15551234567", "hi"])

    assert result.exit_code == 1, result.output
    assert "automation is not permitted" in result.output
    assert "google gmail" in result.output


def test_messages_send_cli_happy_path_exits_0_with_success_json(monkeypatch):
    """`imessage messages send` exits 0 and emits JSON success on the happy path."""
    fake = RecordingSubprocess(
        [
            _completed_process(0, args=["open", "-g", "-a", "Messages"]),  # launch
            _completed_process(0, stdout="Messages"),  # probe ok
            _completed_process(0, stdout=""),  # send ok
        ]
    )
    monkeypatch.setattr(subprocess, "run", fake)

    result = CliRunner().invoke(app, ["messages", "send", "+15551234567", "hi"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["recipient"] == "+15551234567"
