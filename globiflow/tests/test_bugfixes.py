import json
import re

from typer.testing import CliRunner

from globiflow_cli.browser import GlobiflowBrowser
from globiflow_cli.commands import flows, triggers
from globiflow_cli.models import Trigger


def test_globiflow_browser_treats_marketing_homepage_as_auth_failure():
    """The public marketing homepage is not an authenticated Globiflow session."""
    pattern = GlobiflowBrowser.AUTH_FAILURE_URL_PATTERN

    assert pattern, "GlobiflowBrowser must declare an auth-failure URL pattern."
    assert re.search(pattern, "https://workflow-automation.podio.com/"), (
        "GlobiflowBrowser must treat the public marketing homepage as an auth "
        "failure page; otherwise auth status lies when generic cookies exist."
    )
    assert not re.search(pattern, GlobiflowBrowser.AUTH_CHECK_URL), (
        "The auth-failure matcher must not match the authenticated flows page."
    )
    assert GlobiflowBrowser.AUTH_COOKIE_PATTERNS == [], (
        "GlobiflowBrowser must not rely on generic cookie names for auth; "
        "that was the false-positive auth status root cause."
    )


def test_triggers_list_outputs_plain_resource_array(monkeypatch):
    """List commands must return a resource array, not a cache wrapper."""
    runner = CliRunner()

    class _FakeClient:
        def list_triggers(self):
            return [
                Trigger(
                    code="T",
                    name="Every Day",
                    description="Scheduled to run daily at a specific time",
                )
            ]

        def close(self):
            return None

    monkeypatch.setattr(triggers, "get_client", lambda: _FakeClient())

    result = runner.invoke(triggers.app, ["list", "--limit", "1"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert isinstance(payload, list), (
        "globiflow triggers list must return a JSON array so compliance can "
        "discover trigger codes for `triggers get`."
    )
    assert payload == [
        {
            "code": "T",
            "name": "Every Day",
            "description": "Scheduled to run daily at a specific time",
        }
    ]


def test_triggers_get_accepts_code_from_list_output(monkeypatch):
    """The trigger code surfaced by list output must round-trip into get."""
    runner = CliRunner()

    class _FakeClient:
        def list_triggers(self):
            return [
                Trigger(
                    code="T",
                    name="Every Day",
                    description="Scheduled to run daily at a specific time",
                )
            ]

        def close(self):
            return None

    monkeypatch.setattr(triggers, "get_client", lambda: _FakeClient())

    result = runner.invoke(triggers.app, ["get", "T"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["code"] == "T"
    assert payload["name"] == "Every Day"


def test_steps_list_table_without_flow_id_is_not_json():
    """`--table` must never fall back to JSON, even for empty results."""
    runner = CliRunner()

    result = runner.invoke(flows.app, ["steps", "list", "--table"])

    assert result.exit_code == 0, result.output
    assert result.stdout.strip(), "Expected table-mode output for empty steps list."
    try:
        json.loads(result.stdout)
    except json.JSONDecodeError:
        return

    raise AssertionError(
        "globiflow flows steps list --table still emitted JSON. "
        "Use table output for the empty-result path."
    )
