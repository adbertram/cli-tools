import json
import re

from typer.testing import CliRunner

from globiflow_cli import client as client_module
from globiflow_cli.browser import GlobiflowBrowser
from globiflow_cli.client import GlobiflowClient, _clean
from globiflow_cli.commands import flows, triggers
from globiflow_cli.models import FlowDetail, Trigger


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


class _AuthPage:
    def __init__(self, url):
        self.url = url
        self.wait_for_timeout_calls = []

    def wait_for_timeout(self, timeout):
        self.wait_for_timeout_calls.append(timeout)


class _TargetPageAuthBrowser:
    def __init__(self):
        self.get_page_calls = []
        self.checked_pages = []
        self.page = None

    def is_authenticated(self):
        raise AssertionError(
            "ensure_authenticated must not run a separate auth probe before "
            "opening the command target page."
        )

    def get_page(self, url=None):
        self.get_page_calls.append(url)
        self.page = _AuthPage(url)
        return self.page

    def _check_auth(self, page):
        self.checked_pages.append(page)
        return True


def test_ensure_authenticated_validates_target_page_without_separate_probe(monkeypatch):
    """The command target page must stay under one browser-open lifecycle.

    A separate is_authenticated() call opens and closes the browser before the
    command navigation, leaving a near-concurrent command window between auth
    verification and the real operation.
    """
    browser = _TargetPageAuthBrowser()
    client = GlobiflowClient()
    monkeypatch.setattr(GlobiflowClient, "browser", property(lambda self: browser))

    client.ensure_authenticated("/flows.php")

    assert browser.get_page_calls == ["https://workflow-automation.podio.com/flows.php"]
    assert browser.checked_pages == [browser.page]
    assert browser.page.wait_for_timeout_calls == [2000]


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


def test_move_flow_step_rejects_out_of_range_step_number(monkeypatch):
    """move_flow_step must validate step_number before touching the browser
    move functions, with a clear message naming the actual step count."""
    page = _build_steps_page()
    client = _client_with_page(monkeypatch, page)

    try:
        client.move_flow_step("4321944", 5, 1)
        raise AssertionError("Expected ClientError for out-of-range step_number")
    except client_module.ClientError as e:
        assert "Step 5 not found in flow 4321944 (has 2 steps)" in str(e)


def test_move_flow_step_rejects_out_of_range_target_position(monkeypatch):
    """move_flow_step must validate --to against the actual step count."""
    page = _build_steps_page()
    client = _client_with_page(monkeypatch, page)

    try:
        client.move_flow_step("4321944", 1, 9)
        raise AssertionError("Expected ClientError for out-of-range to_position")
    except client_module.ClientError as e:
        assert "Target position 9 is out of range for flow 4321944 (has 2 steps)" in str(e)


def test_delete_flow_step_rejects_out_of_range_step_number(monkeypatch):
    """delete_flow_step must validate step_number before calling deleteStep()."""
    page = _build_steps_page()
    client = _client_with_page(monkeypatch, page)

    try:
        client.delete_flow_step("4321944", 5)
        raise AssertionError("Expected ClientError for out-of-range step_number")
    except client_module.ClientError as e:
        assert "Step 5 not found in flow 4321944 (has 2 steps)" in str(e)


def test_steps_move_command_forwards_target_position_to_client(monkeypatch):
    """`globiflow flows steps move` must call client.move_flow_step with the
    parsed flow_id, step_number, and --to target, and print its JSON result."""
    runner = CliRunner()
    calls = []

    class _FakeClient:
        def move_flow_step(self, flow_id, step_number, to_position):
            calls.append((flow_id, step_number, to_position))
            return {
                "step_number": to_position,
                "action_type": "Create a new Variable",
                "flow_id": flow_id,
            }

        def close(self):
            return None

    monkeypatch.setattr(flows, "get_client", lambda: _FakeClient())

    result = runner.invoke(flows.app, ["steps", "move", "4314927", "3", "--to", "1"])

    assert result.exit_code == 0, result.output
    assert calls == [("4314927", 3, 1)]
    payload = json.loads(result.stdout)
    assert payload["step_number"] == 1
    assert payload["action_type"] == "Create a new Variable"


def test_steps_delete_force_skips_confirmation(monkeypatch):
    """`--force` must delete without prompting for confirmation."""
    runner = CliRunner()
    calls = []

    class _FakeClient:
        def delete_flow_step(self, flow_id, step_number):
            calls.append((flow_id, step_number))
            return True

        def close(self):
            return None

    monkeypatch.setattr(flows, "get_client", lambda: _FakeClient())

    result = runner.invoke(flows.app, ["steps", "delete", "4314927", "2", "--force"])

    assert result.exit_code == 0, result.output
    assert calls == [("4314927", 2)]
    assert "deleted successfully" in result.output


def test_steps_delete_without_force_cancels_on_no(monkeypatch):
    """Without --force, declining the confirmation prompt must not delete."""
    runner = CliRunner()
    calls = []

    class _FakeClient:
        def get_flow_step(self, flow_id, step_number):
            return {"action_type": "Add a Comment to this Item"}

        def delete_flow_step(self, flow_id, step_number):
            calls.append((flow_id, step_number))
            return True

        def close(self):
            return None

    monkeypatch.setattr(flows, "get_client", lambda: _FakeClient())

    result = runner.invoke(flows.app, ["steps", "delete", "4314927", "2"], input="n\n")

    assert result.exit_code == 0, result.output
    assert calls == [], "delete_flow_step must not run when the user declines confirmation."
    assert "cancelled" in result.output.lower()


# ---- Fakes and tests for the --disabled flag bug ----
#
# create_flow() used to try unchecking a `#enabled` checkbox on
# configureflow.php to honor `enabled=False`. That element does not exist on
# the live create-flow page (confirmed by scanning every input/select/[id]/
# [class] element for "enable"/"disable"/"active"/"status" -- zero matches),
# so the check was always a silent no-op and every flow was created enabled
# regardless of --disabled. The real disable mechanism lives on flows.php:
# select the flow's row checkbox, invoke bulkDeactivate(app_id), and confirm
# the resulting dialog -- the same "With Selected" bulk action pattern
# delete_flow already uses for bulkDelete.


class _EmptyLocator:
    """A locator that matches nothing -- the default for any selector a test
    doesn't care about."""

    def count(self):
        return 0

    @property
    def first(self):
        return self


class _NoopLocator:
    """Accepts fill()/click() and reports empty; used for create_flow tests
    that stub out _save_flow/_disable_flow/get_flow so only the flow-name
    fill and flow_id-from-URL extraction in create_flow itself run for
    real."""

    def fill(self, value):
        return None

    def click(self):
        return None

    def count(self):
        return 0

    @property
    def first(self):
        return self


class _CreateFlowPage:
    def __init__(self, url):
        self.url = url

    def wait_for_selector(self, selector, timeout=0):
        return None

    def wait_for_timeout(self, ms):
        return None

    def locator(self, selector):
        return _NoopLocator()

    def get_by_role(self, role, name=None):
        return _NoopLocator()


def _create_flow_client(monkeypatch, url, disable_calls, get_flow_calls):
    """Build a GlobiflowClient wired to a minimal fake create-flow page, with
    _save_flow/_disable_flow/get_flow replaced by spies/no-ops so the test
    isolates create_flow's own dispatch logic (does it call _disable_flow
    when enabled=False, and never when enabled=True)."""
    page = _CreateFlowPage(url)
    client = GlobiflowClient()
    monkeypatch.setattr(client, "ensure_authenticated", lambda path="/": None)

    class _FakeBrowser:
        def get_page(self, url=None):
            return page

    monkeypatch.setattr(GlobiflowClient, "browser", property(lambda self: _FakeBrowser()))
    monkeypatch.setattr(client, "_save_flow", lambda page, timeout=2500: None)

    def _fake_disable_flow(flow_id, app_id):
        disable_calls.append((flow_id, app_id))

    monkeypatch.setattr(client, "_disable_flow", _fake_disable_flow)

    def _fake_get_flow(flow_id, include_steps=False):
        get_flow_calls.append(flow_id)
        return FlowDetail(id=flow_id, name="stub", enabled=True)

    monkeypatch.setattr(client, "get_flow", _fake_get_flow)
    return client, page


def test_create_flow_enabled_true_does_not_disable(monkeypatch):
    """Creating a flow with the default enabled=True must never touch the
    flows.php disable toggle."""
    disable_calls = []
    get_flow_calls = []
    client, _page = _create_flow_client(
        monkeypatch,
        "https://workflow-automation.podio.com/flows.php?node=4404950",
        disable_calls,
        get_flow_calls,
    )

    client.create_flow(app_id="30529466", trigger_code="M", name="Enabled Flow")

    assert disable_calls == [], "enabled=True must not call _disable_flow"
    assert get_flow_calls == ["4404950"]


def test_create_flow_disabled_calls_disable_flow_with_new_id(monkeypatch):
    """Creating a flow with enabled=False must disable the newly created
    flow_id via the flows.php toggle path before returning its details.

    Regression for the bug where --disabled silently created an enabled
    flow because the `#enabled` checkbox create_flow tried to uncheck does
    not exist on configureflow.php.
    """
    disable_calls = []
    get_flow_calls = []
    client, _page = _create_flow_client(
        monkeypatch,
        "https://workflow-automation.podio.com/flows.php?node=4404951",
        disable_calls,
        get_flow_calls,
    )

    client.create_flow(
        app_id="30529466", trigger_code="M", name="Disabled Flow", enabled=False
    )

    assert disable_calls == [("4404951", "30529466")], (
        "enabled=False must call _disable_flow with the newly created flow's "
        "ID and the app_id it belongs to"
    )
    assert get_flow_calls == ["4404951"]


class _TreeItemFake:
    def __init__(self, text, level, item_id=None):
        self._text = text
        self._level = level
        self._item_id = item_id

    def text_content(self):
        return self._text

    def get_attribute(self, name):
        if name == "aria-level":
            return self._level
        if name == "id":
            return self._item_id
        return None


class _TreeItemsListLocator:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _CheckboxLocator:
    def count(self):
        return 1

    @property
    def first(self):
        return self


class _DeactivateLinkLocator:
    def count(self):
        return 1

    @property
    def first(self):
        return self


class _OkButtonLocator:
    def __init__(self, state):
        self._state = state

    def count(self):
        return 1 if self._state.deactivate_called else 0

    @property
    def first(self):
        return self

    def click(self):
        self._state.ok_clicked = True
        if self._state.flips_state and self._state.checked and self._state.deactivate_called:
            self._state.img_src = "/images/icons/small/transmit_off.png"


class _ImgLocator:
    def __init__(self, state):
        self._state = state

    def count(self):
        return 1

    @property
    def first(self):
        return self

    def get_attribute(self, name):
        return self._state.img_src if name == "src" else None


class _RowLocator:
    def __init__(self, state):
        self._state = state

    def count(self):
        return 1

    @property
    def first(self):
        return self

    def locator(self, selector):
        assert selector == "img"
        return _ImgLocator(self._state)


class _FlowsPhpState:
    """Models one flow row on ``flows.php?app=<app_id>``, with a status icon
    that starts enabled (no "_off") and flips to the disabled variant once
    the checkbox is checked, bulkDeactivate is invoked for the right app,
    and the confirmation dialog's OK button is clicked -- mirroring the real
    workflow-automation.podio.com behavior confirmed live (transmit.png ->
    transmit_off.png).

    flips_state=False models a broken toggle (OK click has no effect), to
    prove _disable_flow raises rather than assuming success.
    """

    def __init__(self, flow_id, app_id="30529466", flips_state=True):
        self.flow_id = flow_id
        self.app_id = app_id
        self.flips_state = flips_state
        self.checked = False
        self.deactivate_called = False
        self.ok_clicked = False
        self.img_src = "/images/icons/small/transmit.png"


class _FlowsPhpPage:
    """Fake for a direct ``flows.php?app=<id>`` navigation -- a full page
    load, not the tree-walking AJAX flow list. No app-selection state is
    modelled because _disable_flow no longer walks the org/workspace tree
    (that per-app search loop -- shared by list_flows/get_flow/delete_flow
    -- has a confirmed live timing race; see the _disable_flow docstring)."""

    def __init__(self, state):
        self.state = state
        self.url = f"https://workflow-automation.podio.com/flows.php?app={state.app_id}"

    def wait_for_timeout(self, ms):
        return None

    def get_by_role(self, role, name=None):
        if role == "button" and name == "OK":
            return _OkButtonLocator(self.state)
        return _EmptyLocator()

    def locator(self, selector):
        if selector.startswith("input.bulkCheck[value="):
            if f'"{self.state.flow_id}"' in selector:
                return _CheckboxLocator()
            return _EmptyLocator()
        if selector == 'a[onclick*="bulkDeactivate"]':
            return _DeactivateLinkLocator()
        if selector.startswith("div.flowRowDiv:has(input.bulkCheck[value="):
            if f'"{self.state.flow_id}"' in selector:
                return _RowLocator(self.state)
            return _EmptyLocator()
        return _EmptyLocator()

    def evaluate(self, js):
        if "checked = true" in js and self.state.flow_id in js:
            self.state.checked = True
        elif js.startswith("bulkDeactivate(") and f"({self.state.app_id})" in js:
            self.state.deactivate_called = True
        return None


def _disable_flow_client(monkeypatch, state):
    page = _FlowsPhpPage(state)
    client = GlobiflowClient()
    monkeypatch.setattr(client, "ensure_authenticated", lambda path="/": None)

    class _FakeBrowser:
        def get_page(self, url=None):
            return page

    monkeypatch.setattr(GlobiflowClient, "browser", property(lambda self: _FakeBrowser()))
    return client


def test_disable_flow_toggles_and_reverifies_via_flows_php(monkeypatch):
    """_disable_flow must select the flow's row, trigger bulkDeactivate for
    its app, confirm the dialog, and re-read the row's icon afterward to
    prove the toggle actually took effect (not assume a click succeeded
    silently)."""
    state = _FlowsPhpState(flow_id="4404950", app_id="30529466")
    client = _disable_flow_client(monkeypatch, state)

    client._disable_flow("4404950", "30529466")

    assert state.checked is True
    assert state.deactivate_called is True
    assert state.ok_clicked is True
    assert state.img_src.endswith("transmit_off.png")


def test_disable_flow_raises_when_icon_does_not_flip(monkeypatch):
    """If the deactivate click does not actually flip the row's status
    icon, _disable_flow must raise instead of assuming the toggle
    succeeded."""
    state = _FlowsPhpState(flow_id="4404950", app_id="30529466", flips_state=False)
    client = _disable_flow_client(monkeypatch, state)

    try:
        client._disable_flow("4404950", "30529466")
        raise AssertionError("Expected ClientError when the toggle does not take effect")
    except client_module.ClientError as e:
        assert "was not disabled" in str(e)


# ---- Fakes and tests for get_flow/delete_flow/list_flows no longer
# tree-walking (the app-selection race) ----
#
# get_flow, delete_flow, and list_flows used to search every app by
# clicking through the org/workspace tree and reading a shared,
# AJAX-replaced flow-list panel -- a confirmed live timing race (see
# _disable_flow's docstring): clicking one tree item while the previous
# app's flow list is still being swapped out can make a stale,
# about-to-be-removed checkbox transiently match the wrong app. Each
# method now resolves its target app_id directly instead (via
# configureflow.php?id=<flow_id> for get_flow/delete_flow, or the tree
# item's own id="app-<id>_anchor" attribute for list_flows) and does a
# full-page ?app=<id> navigation with no clicking involved.
#
# _extract_flow_details also used to hardcode `enabled = True`
# unconditionally, so `flows get` reported every flow as enabled
# regardless of its real state -- which would have hidden the --disabled
# bug's fix, since a correctly-disabled flow would still read back as
# enabled. get_flow now reads enabled from the row icon, same as
# list_flows and _disable_flow.


class _FlowNameLocatorPresent:
    """Models `#flowName` on configureflow.php?id=<flow_id> -- present
    when the flow exists, used only for its count()."""

    def count(self):
        return 1


def _client_with_fake_page(monkeypatch, page):
    client = GlobiflowClient()
    monkeypatch.setattr(client, "ensure_authenticated", lambda path="/": None)

    class _FakeBrowser:
        def get_page(self, url=None):
            return page

    monkeypatch.setattr(GlobiflowClient, "browser", property(lambda self: _FakeBrowser()))
    return client


class _ResolveAppIdPage:
    """Models configureflow.php?id=<flow_id> for _resolve_flow_app_id."""

    def __init__(self, flow_found=True, app_id="30529466"):
        self.flow_found = flow_found
        self.app_id = app_id

    def wait_for_timeout(self, ms):
        return None

    def locator(self, selector):
        if selector == "#flowName":
            return _FlowNameLocatorPresent() if self.flow_found else _EmptyLocator()
        return _EmptyLocator()

    def evaluate(self, js):
        return self.app_id


def test_resolve_flow_app_id_extracts_app_id_from_inline_script(monkeypatch):
    page = _ResolveAppIdPage(flow_found=True, app_id="30529466")
    client = _client_with_fake_page(monkeypatch, page)

    assert client._resolve_flow_app_id("4404950") == "30529466"


def test_resolve_flow_app_id_raises_when_flow_not_found(monkeypatch):
    page = _ResolveAppIdPage(flow_found=False)
    client = _client_with_fake_page(monkeypatch, page)

    try:
        client._resolve_flow_app_id("4404950")
        raise AssertionError("Expected ClientError for a nonexistent flow")
    except client_module.ClientError as e:
        assert "not found" in str(e)


def test_resolve_flow_app_id_raises_when_app_id_missing_from_page(monkeypatch):
    page = _ResolveAppIdPage(flow_found=True, app_id=None)
    client = _client_with_fake_page(monkeypatch, page)

    try:
        client._resolve_flow_app_id("4404950")
        raise AssertionError("Expected ClientError when app id cannot be resolved")
    except client_module.ClientError as e:
        assert "Could not resolve app id" in str(e)


class _GetFlowImgLocator:
    def __init__(self, src):
        self._src = src

    def count(self):
        return 1

    @property
    def first(self):
        return self

    def get_attribute(self, name):
        return self._src if name == "src" else None


class _GetFlowHeadingLocator:
    def __init__(self, text):
        self._text = text

    def filter(self, has_text=None):
        return self if has_text and has_text in self._text else _EmptyLocator()

    def count(self):
        return 1

    @property
    def first(self):
        return self

    def text_content(self):
        return self._text


class _GetFlowRowLocator:
    def __init__(self, img_src):
        self._img_src = img_src
        self.clicked = False

    def count(self):
        return 1

    @property
    def first(self):
        return self

    def locator(self, selector):
        assert selector == "img"
        return _GetFlowImgLocator(self._img_src)

    def click(self):
        self.clicked = True


class _GetFlowResolvedPage:
    """Fake spanning both navigations get_flow now makes: first
    configureflow.php?id=<flow_id> (_resolve_flow_app_id), then
    flows.php?app=<app_id> (find the row, read its details)."""

    def __init__(self, flow_id, app_id, img_src, heading_text):
        self.flow_id = flow_id
        self.app_id = app_id
        self.row = _GetFlowRowLocator(img_src)
        self.heading = _GetFlowHeadingLocator(heading_text)

    def wait_for_timeout(self, ms):
        return None

    def locator(self, selector):
        if selector == "#flowName":
            return _FlowNameLocatorPresent()
        if selector.startswith("div.flowRowDiv:has(input.bulkCheck[value="):
            if f'"{self.flow_id}"' in selector:
                return self.row
            return _EmptyLocator()
        if selector == "h4":
            return self.heading
        return _EmptyLocator()

    def evaluate(self, js):
        return self.app_id


def test_get_flow_reads_enabled_from_row_icon(monkeypatch):
    """get_flow must resolve the flow's app id directly, read its enabled
    status from the flows.php row icon, and pass it into
    _extract_flow_details -- not rely on the old hardcoded True.
    """
    page = _GetFlowResolvedPage(
        flow_id="4404950",
        app_id="30529466",
        img_src="/images/icons/small/transmit_off.png",
        heading_text="Flow: My Disabled Flow (ID:4404950)",
    )
    client = _client_with_fake_page(monkeypatch, page)

    captured = {}

    def _fake_extract(page_arg, flow_id, enabled=True):
        captured["enabled"] = enabled
        return FlowDetail(id=flow_id, name="My Disabled Flow", enabled=enabled)

    monkeypatch.setattr(client, "_extract_flow_details", _fake_extract)

    result = client.get_flow("4404950")

    assert captured["enabled"] is False, (
        "get_flow must pass the row's real enabled state into "
        "_extract_flow_details instead of the old hardcoded True"
    )
    assert result.enabled is False
    assert page.row.clicked is True, "get_flow must click the row to load its detail view"


def test_get_flow_raises_when_heading_id_does_not_match(monkeypatch):
    """If the clicked row's detail heading doesn't carry the requested
    flow_id, get_flow must raise instead of returning the wrong flow."""
    page = _GetFlowResolvedPage(
        flow_id="4404950",
        app_id="30529466",
        img_src="/images/icons/small/transmit.png",
        heading_text="Flow: Some Other Flow (ID:9999999)",
    )
    client = _client_with_fake_page(monkeypatch, page)

    try:
        client.get_flow("4404950")
        raise AssertionError("Expected ClientError for a heading/id mismatch")
    except client_module.ClientError as e:
        assert "not found" in str(e)


# ---- Fakes and tests for delete_flow's resolve-then-navigate rewrite ----


class _DeleteFlowRowLocator:
    def __init__(self, state):
        self._state = state

    def count(self):
        return 0 if self._state.deleted else 1

    @property
    def first(self):
        return self


class _DeleteFlowCheckboxLocator:
    def __init__(self, state):
        self._state = state

    def count(self):
        return 0 if self._state.deleted else 1

    @property
    def first(self):
        return self


class _DeleteLinkLocator:
    def count(self):
        return 1

    @property
    def first(self):
        return self


class _ModalInputLocator:
    def __init__(self, state):
        self._state = state

    def count(self):
        return 1

    @property
    def last(self):
        return self

    def is_visible(self):
        return True

    def fill(self, value):
        self._state.modal_filled = value


class _OkButtonDeleteLocator:
    def __init__(self, state):
        self._state = state

    def count(self):
        return 1

    @property
    def first(self):
        return self

    def click(self):
        self._state.ok_clicked = True
        if (
            self._state.deletes_take_effect
            and self._state.modal_filled == "delete"
            and self._state.bulk_delete_called
        ):
            self._state.deleted = True


class _DeleteFlowState:
    def __init__(self, flow_id, app_id, deletes_take_effect=True):
        self.flow_id = flow_id
        self.app_id = app_id
        self.deletes_take_effect = deletes_take_effect
        self.checked = False
        self.bulk_delete_called = False
        self.modal_filled = None
        self.ok_clicked = False
        self.deleted = False


class _DeleteFlowPage:
    """Fake spanning both navigations delete_flow now makes: first
    configureflow.php?id=<flow_id> (_resolve_flow_app_id), then
    flows.php?app=<app_id> (select the row, bulkDelete, confirm)."""

    def __init__(self, state):
        self.state = state

    def wait_for_timeout(self, ms):
        return None

    def locator(self, selector):
        s = self.state
        if selector == "#flowName":
            return _FlowNameLocatorPresent()
        if selector.startswith("div.flowRowDiv:has(input.bulkCheck[value="):
            return _DeleteFlowRowLocator(s) if f'"{s.flow_id}"' in selector else _EmptyLocator()
        if selector.startswith("input.bulkCheck[value="):
            return _DeleteFlowCheckboxLocator(s) if f'"{s.flow_id}"' in selector else _EmptyLocator()
        if selector == 'a[onclick*="bulkDelete"]':
            return _DeleteLinkLocator()
        if selector == "input[type='text']":
            return _ModalInputLocator(s)
        return _EmptyLocator()

    def get_by_role(self, role, name=None):
        if role == "button" and name == "OK":
            return _OkButtonDeleteLocator(self.state)
        return _EmptyLocator()

    def evaluate(self, js):
        s = self.state
        if "AppId" in js:
            return s.app_id
        if "checked = true" in js and s.flow_id in js:
            s.checked = True
        elif js.startswith("bulkDelete(") and f"({s.app_id})" in js:
            s.bulk_delete_called = True
        return None


def test_delete_flow_resolves_app_id_and_deletes_via_bulk_action(monkeypatch):
    """delete_flow must resolve the owning app directly, select the row,
    invoke bulkDelete for that app, confirm the modal, and verify the row
    is actually gone afterward."""
    state = _DeleteFlowState(flow_id="4404950", app_id="30529466")
    page = _DeleteFlowPage(state)
    client = _client_with_fake_page(monkeypatch, page)

    assert client.delete_flow("4404950") is True
    assert state.checked is True
    assert state.bulk_delete_called is True
    assert state.modal_filled == "delete"
    assert state.ok_clicked is True


def test_delete_flow_raises_when_checkbox_still_present_after_confirm(monkeypatch):
    """If confirming the delete modal doesn't actually remove the flow's
    row, delete_flow must raise instead of assuming success."""
    state = _DeleteFlowState(flow_id="4404950", app_id="30529466", deletes_take_effect=False)
    page = _DeleteFlowPage(state)
    client = _client_with_fake_page(monkeypatch, page)

    try:
        client.delete_flow("4404950")
        raise AssertionError("Expected ClientError when the flow's row is still present")
    except client_module.ClientError as e:
        assert "still present on flows.php" in str(e)


# ---- Fakes and tests for list_flows' resolve-then-navigate rewrite ----


class _ListFlowsState:
    def __init__(self):
        self.visited_paths = []
        self.current_app_id = None


class _ListFlowsCheckboxLocator:
    def __init__(self, flow_id):
        self._flow_id = flow_id

    def count(self):
        return 1

    @property
    def first(self):
        return self

    def get_attribute(self, name):
        return self._flow_id if name == "value" else None


class _ListFlowsFlowDiv:
    def __init__(self, name, flow_id, img_src):
        self._name = name
        self._flow_id = flow_id
        self._img_src = img_src

    def text_content(self):
        return self._name

    def locator(self, selector):
        if selector == "input.bulkCheck":
            return _ListFlowsCheckboxLocator(self._flow_id)
        if selector == "img":
            return _GetFlowImgLocator(self._img_src)
        return _EmptyLocator()


class _ListFlowsItemsLocator:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _ListFlowsContainerLocator:
    def __init__(self, flow_divs):
        self._flow_divs = flow_divs

    def count(self):
        return 1

    @property
    def first(self):
        return self

    def locator(self, selector):
        if selector == "div[style*='cursor']":
            return _ListFlowsItemsLocator([])
        if selector == "> div":
            return _ListFlowsItemsLocator(self._flow_divs)
        return _ListFlowsItemsLocator([])


class _ListFlowsPage:
    def __init__(self, state, tree_items, flows_by_app):
        self.state = state
        self.tree_items = tree_items
        self.flows_by_app = flows_by_app

    def wait_for_selector(self, selector, timeout=0):
        return None

    def wait_for_timeout(self, ms):
        return None

    def get_by_role(self, role, name=None):
        return _EmptyLocator()

    def locator(self, selector):
        if selector == '[role="treeitem"]':
            return _TreeItemsListLocator(self.tree_items)
        if selector == "hr ~ div":
            items = self.flows_by_app.get(self.state.current_app_id, [])
            flow_divs = [_ListFlowsFlowDiv(name, fid, img) for (name, fid, img) in items]
            return _ListFlowsContainerLocator(flow_divs)
        return _EmptyLocator()


def _list_flows_client(monkeypatch, tree_items, flows_by_app):
    state = _ListFlowsState()
    page = _ListFlowsPage(state, tree_items, flows_by_app)
    client = GlobiflowClient()

    def _fake_ensure_authenticated(path="/"):
        state.visited_paths.append(path)
        match = re.search(r"app=(\d+)", path)
        state.current_app_id = match.group(1) if match else None

    monkeypatch.setattr(client, "ensure_authenticated", _fake_ensure_authenticated)

    class _FakeBrowser:
        def get_page(self, url=None):
            return page

    monkeypatch.setattr(GlobiflowClient, "browser", property(lambda self: _FakeBrowser()))
    return client, state, page


def test_list_flows_navigates_directly_per_app_using_tree_item_id(monkeypatch):
    """list_flows must resolve each app's id from its tree item's own
    id="app-<id>_anchor" attribute and navigate to it directly via
    /flows.php?app=<id> instead of clicking through the tree -- clicking
    races the AJAX-replaced flow panel (see _disable_flow's docstring for
    the confirmed live race)."""
    tree_items = [
        _TreeItemFake("Acme Org", "1"),
        _TreeItemFake("Marketing", "2"),
        _TreeItemFake("Content (2) 5", "3", item_id="app-30529466_anchor"),
        _TreeItemFake("Blogs", "3", item_id="app-30529455_anchor"),  # no count -> skipped
    ]
    flows_by_app = {
        "30529466": [("Flow A", "111", "/images/icons/small/transmit.png")],
    }
    client, state, page = _list_flows_client(monkeypatch, tree_items, flows_by_app)

    result = client.list_flows()

    assert [f.id for f in result] == ["111"]
    assert result[0].name == "Flow A"
    assert result[0].app_name == "Content"
    assert result[0].workspace_name == "Marketing"
    assert result[0].org_name == "Acme Org"
    assert result[0].enabled is True
    assert state.visited_paths == ["/flows.php", "/flows.php?app=30529466"]


def test_list_flows_raises_when_app_tree_item_has_no_resolvable_id(monkeypatch):
    """If an app tree item with a flow count doesn't carry a parseable
    id="app-<id>_anchor" attribute, list_flows must raise instead of
    silently skipping that app's flows."""
    tree_items = [
        _TreeItemFake("Acme Org", "1"),
        _TreeItemFake("Marketing", "2"),
        _TreeItemFake("Content (2) 5", "3", item_id="not-an-app-anchor"),
    ]
    client, state, page = _list_flows_client(monkeypatch, tree_items, {})

    try:
        client.list_flows()
        raise AssertionError("Expected ClientError when app id cannot be resolved from the tree")
    except client_module.ClientError as e:
        assert "Could not resolve app id" in str(e)
