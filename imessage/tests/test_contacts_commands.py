"""Tests for contacts commands and the Contacts.app-not-running hardening.

These tests mock at the osascript execution layer (subprocess.run inside
applescript.py) so they simulate macOS AppleScript behavior without needing a
real running Contacts.app in CI.
"""
import json
import subprocess

import pytest
from typer.testing import CliRunner

from imessage_cli.applescript import (
    AppleScriptError,
    ensure_app_running,
    run_applescript,
)
from imessage_cli.client import ClientError, ImessageClient
from imessage_cli.main import app


NOT_RUNNING_ERROR = (
    '121:136: execution error: Contacts got an error: '
    "Application isn't running. (-600)"
)


def _completed_process(returncode: int, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(
        args=["osascript", "-e", "irrelevant"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


class RecordingOsascript:
    """Fake subprocess.run that records every osascript invocation.

    `responses` is a list of CompletedProcess results consumed in order, one
    per call. If exhausted, the last response is reused.
    """

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[index]

    @property
    def scripts(self):
        """The AppleScript source (`-e` argument) passed to each call."""
        return [cmd[2] for cmd in self.calls]


# ==================== ensure_app_running / run_applescript unit tests ====================


def test_ensure_app_running_sends_launch_verb_not_activate(monkeypatch):
    """`launch` starts the app without stealing focus, unlike `activate`."""
    fake = RecordingOsascript([_completed_process(0, stdout="")])
    monkeypatch.setattr(subprocess, "run", fake)

    ensure_app_running("Contacts")

    assert len(fake.calls) == 1
    assert 'tell application "Contacts" to launch' == fake.scripts[0]
    assert "activate" not in fake.scripts[0]


def test_ensure_app_running_raises_when_launch_itself_fails(monkeypatch):
    fake = RecordingOsascript(
        [_completed_process(1, stderr="some launch failure")]
    )
    monkeypatch.setattr(subprocess, "run", fake)

    with pytest.raises(AppleScriptError, match="some launch failure"):
        ensure_app_running("Contacts")


def test_run_applescript_surfaces_application_not_running_error(monkeypatch):
    """Reproduces the exact -600 error text from the bug report."""
    fake = RecordingOsascript([_completed_process(1, stderr=NOT_RUNNING_ERROR)])
    monkeypatch.setattr(subprocess, "run", fake)

    with pytest.raises(AppleScriptError, match=r"Application isn't running\. \(-600\)"):
        run_applescript('tell application "Contacts" to return count of people')


# ==================== ImessageClient.list_contacts / get_contact ====================


def test_list_contacts_launches_contacts_app_before_querying(monkeypatch):
    """When Contacts.app is not running, list_contacts must launch it first,
    then issue the real query -- never surfacing the -600 error to the caller.
    """
    query_output = "abc-123\tMiranda Bailey\t+15551234567|\tmiranda@example.com|\tAcme\n"
    fake = RecordingOsascript(
        [
            _completed_process(0, stdout=""),  # ensure_app_running("Contacts")
            _completed_process(0, stdout=query_output),  # the real list query
        ]
    )
    monkeypatch.setattr(subprocess, "run", fake)

    client = ImessageClient()
    contacts = client.list_contacts(limit=100)

    assert len(fake.calls) == 2
    assert fake.scripts[0] == 'tell application "Contacts" to launch'
    assert 'tell application "Contacts"' in fake.scripts[1]
    assert len(contacts) == 1
    assert contacts[0].name == "Miranda Bailey"


def test_list_contacts_still_works_when_contacts_app_already_running(monkeypatch):
    """Calling `launch` on an already-running app is a harmless no-op per
    AppleScript semantics; the query must still succeed.
    """
    query_output = "abc-123\tMiranda Bailey\t+15551234567|\tmiranda@example.com|\tAcme\n"
    fake = RecordingOsascript(
        [
            _completed_process(0, stdout=""),  # launch (already running -> no-op)
            _completed_process(0, stdout=query_output),
        ]
    )
    monkeypatch.setattr(subprocess, "run", fake)

    client = ImessageClient()
    contacts = client.list_contacts(limit=100)

    assert len(contacts) == 1
    assert contacts[0].name == "Miranda Bailey"


def test_list_contacts_raises_client_error_if_query_fails_after_launch(monkeypatch):
    """The launch-first guard must not mask a genuine query failure -- if the
    query still errors after ensure_app_running succeeded, that must surface.
    """
    fake = RecordingOsascript(
        [
            _completed_process(0, stdout=""),  # ensure_app_running succeeds
            _completed_process(1, stderr="some other AppleScript failure"),
        ]
    )
    monkeypatch.setattr(subprocess, "run", fake)

    client = ImessageClient()
    with pytest.raises(ClientError, match="Failed to list contacts"):
        client.list_contacts(limit=100)

    assert len(fake.calls) == 2


def test_get_contact_launches_contacts_app_before_querying(monkeypatch):
    query_output = "abc-123\tMiranda Bailey\t+15551234567|\tmiranda@example.com|\tAcme"
    fake = RecordingOsascript(
        [
            _completed_process(0, stdout=""),  # ensure_app_running("Contacts")
            _completed_process(0, stdout=query_output),  # the real get query
        ]
    )
    monkeypatch.setattr(subprocess, "run", fake)

    client = ImessageClient()
    contact = client.get_contact("abc-123")

    assert len(fake.calls) == 2
    assert fake.scripts[0] == 'tell application "Contacts" to launch'
    assert 'tell application "Contacts"' in fake.scripts[1]
    assert contact.name == "Miranda Bailey"


def test_auth_status_contacts_check_launches_contacts_app_first(monkeypatch):
    """auth_status's Contacts reachability probe must also launch first.

    auth_status now checks Messages send-capability before the Contacts probe:
    it launches Messages via ``open -g -a`` and runs a bounded ``get name``
    Apple Events probe, then launches Contacts and counts people. All four
    subprocess calls flow through the same fake in order.
    """
    fake = RecordingOsascript(
        [
            _completed_process(0, stdout=""),  # launch_app("Messages") -> open -g -a
            _completed_process(0, stdout="Messages"),  # probe_automation("Messages") get name
            _completed_process(0, stdout=""),  # ensure_app_running("Contacts")
            _completed_process(0, stdout="3"),  # count of people
        ]
    )
    monkeypatch.setattr(subprocess, "run", fake)
    # db.is_accessible() touches the filesystem; keep this test scoped to the
    # Contacts reachability probe only.
    monkeypatch.setattr(
        "imessage_cli.client.MessageDB.is_accessible",
        lambda self: True,
    )

    client = ImessageClient()
    status = client.auth_status()

    # Messages is launched via LaunchServices (open), not an Apple Event.
    assert fake.calls[0] == ["open", "-g", "-a", "Messages"]
    launch_calls = [s for s in fake.scripts if s == 'tell application "Contacts" to launch']
    assert len(launch_calls) == 1
    assert status.contacts_accessible is True
    assert status.messages_app_available is True


# ==================== CLI-level: `imessage contacts list` end to end ====================


def test_contacts_list_command_succeeds_when_contacts_app_was_not_running(monkeypatch):
    """End-to-end regression test for the reported bug:
    `imessage contacts list --filter "name:like:%miranda%"` must no longer
    fail with the -600 "Application isn't running" error.
    """
    query_output = "abc-123\tMiranda Bailey\t+15551234567|\tmiranda@example.com|\tAcme\n"
    fake = RecordingOsascript(
        [
            _completed_process(0, stdout=""),  # ensure_app_running("Contacts")
            _completed_process(0, stdout=query_output),  # the real list query
        ]
    )
    monkeypatch.setattr(subprocess, "run", fake)

    result = CliRunner().invoke(
        app, ["contacts", "list", "--filter", "name:like:%miranda%"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert len(payload) == 1
    assert payload[0]["name"] == "Miranda Bailey"
