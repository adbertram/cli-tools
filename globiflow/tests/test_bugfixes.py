import json
import re

from typer.testing import CliRunner

from globiflow_cli import client as client_module
from globiflow_cli.browser import GlobiflowBrowser
from globiflow_cli.client import GlobiflowClient, _clean
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


def test_clean_handles_none_text_content():
    """Playwright text_content() returns None for empty nodes; _clean must not crash.

    Regression for `'NoneType' object has no attribute 'strip'` raised while
    extracting step parameters from a flow's configureflow.php page.
    """
    assert _clean(None) == ""
    assert _clean("  hello  ") == "hello"
    assert _clean("") == ""


# ---- Fakes for the step-list DOM, modelled on the live configureflow.php page ----


class _FakeLocator:
    """Minimal Playwright-locator stand-in supporting the calls the step
    extraction makes: locator('> li').all(), locator('> div').first,
    inner_text(), and count()."""

    def __init__(self, children=None, inner_text="", count=1):
        self._children = children or {}
        self._inner_text = inner_text
        self._count = count

    def locator(self, selector):
        return self._children.get(selector, _FakeLocator(count=0))

    @property
    def first(self):
        return self

    def all(self):
        return self._children.get("__items__", [])

    def count(self):
        return self._count

    def inner_text(self):
        return self._inner_text


class _FakePage:
    """Records wait_for_selector calls and serves a fixed locator tree."""

    def __init__(self, locators):
        self.waited_selectors = []
        self._locators = locators
        self.url = "https://workflow-automation.podio.com/configureflow.php?id=1"

    def wait_for_selector(self, selector, timeout=0):
        self.waited_selectors.append(selector)

    def wait_for_timeout(self, ms):
        return None

    def locator(self, selector):
        return self._locators.get(selector, _FakeLocator(count=0))


def _build_steps_page():
    """Build a fake page whose ul#flowactions holds two <li>, each with a
    leading <div>. One div's first line is a normal action; the second has no
    extra content, exercising the empty-text path."""
    step1_div = _FakeLocator(inner_text="Create a new Variable\nvarname = url")
    step2_div = _FakeLocator(inner_text="Add Comment")
    li1 = _FakeLocator(children={"> div": step1_div})
    li2 = _FakeLocator(children={"> div": step2_div})
    flowactions = _FakeLocator(children={"> li": _FakeLocator(children={"__items__": [li1, li2]})})
    return _FakePage({"ul#flowactions": flowactions})


def _client_with_page(monkeypatch, page):
    client = GlobiflowClient()
    monkeypatch.setattr(client, "ensure_authenticated", lambda path="/": None)

    class _FakeBrowser:
        def get_page(self, url=None):
            return page

    monkeypatch.setattr(GlobiflowClient, "browser", property(lambda self: _FakeBrowser()))
    # Parameter extraction is exercised live; isolate the selector/traversal here.
    monkeypatch.setattr(client, "_extract_step_parameters", lambda action_div: {})
    monkeypatch.setattr(client_module, "create_step", _fake_create_step)
    return client


def _fake_create_step(step_number, action_type, parameters=None, flow_id=None):
    return {
        "step_number": step_number,
        "action_type": action_type,
        "parameters": parameters,
        "flow_id": flow_id,
    }


def test_list_flow_steps_anchors_on_flowactions_id(monkeypatch):
    """Steps must be located via the stable ul#flowactions id, not an "Actions"
    heading. The page now renders two h4 headings containing "Actions" (a
    sidebar palette plus the real section), so heading-text matching broke with
    a wait_for_selector timeout. Regression for that universal step-list failure.
    """
    page = _build_steps_page()
    client = _client_with_page(monkeypatch, page)

    steps = client.list_flow_steps("4321944")

    assert page.waited_selectors == ["ul#flowactions"], (
        "list_flow_steps must wait on the stable ul#flowactions id, not an "
        "ambiguous h4 'Actions' heading."
    )
    assert [s["action_type"] for s in steps] == ["Create a new Variable", "Add Comment"]


def test_get_flow_step_anchors_on_flowactions_id(monkeypatch):
    """get_flow_step must also anchor on ul#flowactions and return the step."""
    page = _build_steps_page()
    client = _client_with_page(monkeypatch, page)

    step = client.get_flow_step("4321944", 2)

    assert page.waited_selectors == ["ul#flowactions"]
    assert step["action_type"] == "Add Comment"
    assert step["step_number"] == 2
