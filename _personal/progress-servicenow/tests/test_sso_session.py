"""Regression tests for the two reported session defects.

1. An expired browser session could not be refreshed: ``auth status`` and
   ``auth test`` reported ``authenticated: false`` and nothing re-authenticated
   the Progress Entra SSO session.
2. Ticket commands scraped the SSO login page and reported it as ticket data —
   ``ticket get`` returned ``description = "Enter password"`` with exit 0, and
   ``ticket list`` printed "No tickets found." with exit 0.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from cli_tools_shared.auth import BrowserAutomation
from cli_tools_shared.exceptions import ClientError

from progress_servicenow_cli import client as client_mod, sso
from progress_servicenow_cli.browser import ProgressServiceNowBrowser
from progress_servicenow_cli.client import ProgressServicenowClient

from conftest import LIVE_FORM_SNAPSHOT, SSO_LOGIN_SNAPSHOT, SSO_LOGIN_URL, TICKET_URL


# ---------------------------------------------------------------------------
# Defect 2: no page from the SSO login flow may ever be parsed as ticket data.
# ---------------------------------------------------------------------------


class FakePage:
    def __init__(self, url):
        self.url = url


class GuardedClient:
    """Minimal stand-in exposing the attributes the guarded methods read."""

    def __init__(self, url, snapshot=SSO_LOGIN_SNAPSHOT):
        self._page = FakePage(url)
        self._svc = self
        self._snapshot_text = snapshot
        self.navigated = []

    def _get_page(self):
        return self._page

    def page_goto(self, url):
        self.navigated.append(url)


def test_guard_rejects_the_microsoft_sso_host():
    with pytest.raises(ClientError) as exc:
        client_mod._raise_if_not_servicenow(SSO_LOGIN_URL)
    assert "Not authenticated" in str(exc.value)
    assert "SSO login page" in str(exc.value)
    assert "auth login --force" in str(exc.value)


def test_guard_rejects_any_non_servicenow_host():
    with pytest.raises(ClientError, match="expected a page on service-now.com"):
        client_mod._raise_if_not_servicenow("https://example.com/whatever")


def test_guard_rejects_the_servicenow_login_page():
    with pytest.raises(ClientError, match="its own login page"):
        client_mod._raise_if_not_servicenow(
            "https://progress1.service-now.com/esc?id=login&redirect=%2Fesc"
        )


def test_guard_allows_a_real_ticket_url():
    client_mod._raise_if_not_servicenow(TICKET_URL)


def test_snapshot_guard_rejects_a_captured_sign_in_page():
    with pytest.raises(ClientError, match="is the SSO login page"):
        client_mod._raise_if_login_snapshot(SSO_LOGIN_SNAPSHOT, TICKET_URL)


def test_snapshot_guard_allows_a_real_catalog_form():
    client_mod._raise_if_login_snapshot(LIVE_FORM_SNAPSHOT, TICKET_URL)


def test_guarded_snapshot_raises_instead_of_returning_login_page_fields(monkeypatch):
    """The parsers must never see the login page — no 'Enter password' as data."""
    monkeypatch.setattr(client_mod, "_bytecode_snapshot", lambda self: SSO_LOGIN_SNAPSHOT)
    client = GuardedClient(SSO_LOGIN_URL)
    with pytest.raises(ClientError, match="Not authenticated"):
        client_mod._guarded_snapshot(client)


def test_guarded_snapshot_rejects_a_login_page_served_from_the_servicenow_host(monkeypatch):
    monkeypatch.setattr(client_mod, "_bytecode_snapshot", lambda self: SSO_LOGIN_SNAPSHOT)
    client = GuardedClient(TICKET_URL)
    with pytest.raises(ClientError, match="is the SSO login page"):
        client_mod._guarded_snapshot(client)


def test_guarded_snapshot_returns_a_real_servicenow_snapshot(monkeypatch):
    monkeypatch.setattr(client_mod, "_bytecode_snapshot", lambda self: LIVE_FORM_SNAPSHOT)
    client = GuardedClient(TICKET_URL, snapshot=LIVE_FORM_SNAPSHOT)
    assert client_mod._guarded_snapshot(client) == LIVE_FORM_SNAPSHOT


def test_guarded_navigate_fails_when_the_request_lands_on_sso(monkeypatch):
    monkeypatch.setattr(
        client_mod, "_bytecode_navigate", lambda self, url: self.navigated.append(url)
    )
    client = GuardedClient(SSO_LOGIN_URL)
    with pytest.raises(ClientError, match="Not authenticated"):
        client_mod._guarded_navigate(client, TICKET_URL)
    assert client.navigated == [TICKET_URL]


def test_every_read_path_is_guarded():
    """`_navigate` and `_snapshot` are the only page funnels — both are guarded."""
    assert ProgressServicenowClient._navigate is client_mod._guarded_navigate
    assert ProgressServicenowClient._snapshot is client_mod._guarded_snapshot


def test_catalog_page_refuses_an_unauthenticated_page():
    client = GuardedClient(SSO_LOGIN_URL)
    client.config = type("Config", (), {"base_url": "https://progress1.service-now.com/esc"})()
    client._ensure_browser = lambda: None
    client._navigate = lambda url: None
    client._wait = lambda ms: None
    with pytest.raises(ClientError, match="Not authenticated"):
        client_mod._catalog_page(client)


# ---------------------------------------------------------------------------
# Defect 1: the Entra SSO session must be refreshable without a human.
# ---------------------------------------------------------------------------


def test_browser_declares_a_noninteractive_login_handler():
    """The subclass stays declarative; the shared engine owns the lifecycle."""
    assert BrowserAutomation.AUTH_LOGIN_HANDLER is None
    assert ProgressServiceNowBrowser.AUTH_LOGIN_HANDLER is sso.run_sso_login
    assert ProgressServiceNowBrowser.authenticate is BrowserAutomation.authenticate
    assert ProgressServiceNowBrowser.LASTPASS_ENTRY
    assert ProgressServiceNowBrowser.LOGIN_EMAIL_DOMAIN == "progress.com"


def test_noninteractive_login_path_is_selected_and_never_opens_a_headed_browser():
    """``authenticate`` routes to the headless handler, not the prompt flow."""
    calls = []

    class FakeBrowser(ProgressServiceNowBrowser):
        def _session_name(self):
            return "progress-servicenow-test"

        def _authenticate_noninteractive(self, force=False):
            calls.append(force)

        def _authenticate_manual(self, force=False):  # pragma: no cover - must not run
            raise AssertionError("manual login must not be used")

    browser = FakeBrowser.__new__(FakeBrowser)
    BrowserAutomation.authenticate(browser, force=True)
    assert calls == [True]


@pytest.mark.parametrize(
    "state,expected",
    [
        # Entra's combined view shows both boxes but consumes only the username.
        ({"password_ready": True, "username_ready": True}, sso.STEP_USERNAME),
        ({"password_ready": True}, sso.STEP_PASSWORD),
        ({"username_ready": True}, sso.STEP_USERNAME),
        ({"push_challenge": True}, sso.STEP_OPEN_FACTOR_PICKER),
        ({"factor_picker_ready": True, "push_challenge": True}, sso.STEP_REQUEST_SMS),
        ({"otc_ready": True, "factor_picker_ready": True}, sso.STEP_ENTER_SMS_CODE),
        ({"kmsi_ready": True, "password_ready": True}, sso.STEP_STAY_SIGNED_IN),
        ({}, sso.STEP_WAIT),
    ],
)
def test_select_step_ordering(state, expected):
    assert sso.select_step(state) == expected


def test_login_email_applies_the_required_upn_format():
    assert sso.login_email("bertram", "progress.com") == "bertram@progress.com"
    assert sso.login_email("bertram@progress.com", "progress.com") == "bertram@progress.com"


def test_login_email_rejects_an_empty_vault_username():
    with pytest.raises(ClientError, match="empty"):
        sso.login_email("   ", "progress.com")


def test_lastpass_value_rejects_an_unsupported_field():
    with pytest.raises(ClientError, match="Unsupported LastPass field"):
        sso.lastpass_value("entry", "totp")


class RecordingPage:
    """Records the ordered page interactions a step performs."""

    url = "https://login.microsoftonline.com/tenant/saml2"

    def __init__(self, *, username_visible=True, username_value="bertram@progress.com"):
        self.events = []
        self._username_visible = username_visible
        self._username_value = username_value

    def fill(self, selector, text):
        self.events.append(("fill", selector, len(text)))

    def wait_for_timeout(self, ms):
        self.events.append(("wait", ms))

    def locator(self, selector):
        return RecordingLocator(self, selector)


class RecordingLocator:
    def __init__(self, page, selector):
        self._page = page
        self._selector = selector

    def count(self):
        if self._selector == sso.USERNAME_SELECTOR:
            return 1 if self._page._username_visible else 0
        return 1

    @property
    def first(self):
        return self

    def is_visible(self):
        return self.count() == 1

    def is_enabled(self):
        return True

    def is_checked(self):
        return False

    def evaluate(self, _expression):
        return self._page._username_value

    def click(self):
        self._page.events.append(("click", self._selector))


def test_password_is_filled_then_allowed_to_settle_before_submit(monkeypatch):
    """Entra ignores a submit click issued in the same tick as the input event."""
    monkeypatch.setattr(sso, "lastpass_value", lambda entry, field: "s3cret-value")
    page = RecordingPage()
    login = sso.ProgressSsoLogin(
        SimpleNamespace(), page, lastpass_entry="entry", email_domain="progress.com"
    )

    login._submit_password()

    assert page.events == [
        ("fill", sso.PASSWORD_SELECTOR, len("s3cret-value")),
        ("wait", sso.FIELD_SETTLE_MS),
        ("click", sso.SUBMIT_SELECTOR),
    ]


def test_username_step_submits_only_the_username(monkeypatch):
    """The combined view discards a pre-filled password, so send one field."""
    monkeypatch.setattr(sso, "lastpass_value", lambda entry, field: "bertram")
    page = RecordingPage(username_value="")
    login = sso.ProgressSsoLogin(
        SimpleNamespace(), page, lastpass_entry="entry", email_domain="progress.com"
    )

    login._submit_username()

    assert page.events == [
        ("fill", sso.USERNAME_SELECTOR, len("bertram@progress.com")),
        ("wait", sso.FIELD_SETTLE_MS),
        ("click", sso.SUBMIT_SELECTOR),
    ]


@pytest.mark.parametrize(
    "message,is_prompt",
    [
        ("Please enter your password.", True),
        ("Enter your password", True),
        ("Enter a valid email address, phone number, or Skype name.", False),
        ("Your account or password is incorrect.", False),
    ],
)
def test_empty_field_prompts_are_not_credential_rejections(message, is_prompt):
    assert sso.is_empty_field_prompt(message) is is_prompt


class ScriptedLogin(sso.ProgressSsoLogin):
    """Drives the sign-in state machine through a scripted page sequence."""

    def __init__(self, views, authenticated_after):
        self.views = list(views)
        self.authenticated_after = authenticated_after
        self.actions = []
        self.current_view = ({}, "")
        browser = SimpleNamespace(
            _check_auth=lambda page: len(self.actions) >= self.authenticated_after
        )
        page = SimpleNamespace(
            wait_for_timeout=lambda ms: None,
            url="https://login.microsoftonline.com/tenant/login",
        )
        super().__init__(browser, page, lastpass_entry="entry", email_domain="progress.com")

    def view_signature(self):
        """Advance the script; the last scripted view persists, as a real one would."""
        if self.views:
            self.current_view = self.views.pop(0)
        state, heading = self.current_view
        return (sso.select_step(state), heading)

    def _raise_on_rejected_credentials(self):
        return None

    def _raise_on_phone_confirmation(self):
        return None

    def _submit_password(self):
        self.actions.append("password")

    def _submit_username(self):
        self.actions.append("username")

    def _open_factor_picker(self):
        self.actions.append("open_picker")

    def _request_sms(self):
        self.actions.append("request_sms")

    def _enter_sms_code(self):
        self.actions.append("enter_code")

    def _stay_signed_in(self):
        self.actions.append("kmsi")


COMBINED = {"username_ready": True, "password_ready": True}


def test_each_view_is_acted_on_exactly_once():
    """Entra re-renders a view while it works; never resubmit a secret."""
    login = ScriptedLogin(
        views=[
            (COMBINED, "Sign in"),                                  # run: username
            (COMBINED, "Sign in"),                                  # settle: still working
            ({"password_ready": True}, "Enter password"),           # settle: advanced
            ({"password_ready": True}, "Enter password"),           # run: password
            ({"password_ready": True}, "Enter password"),           # settle: still working
            ({"push_challenge": True}, "Approve sign in request"),  # settle: advanced
            ({"push_challenge": True}, "Approve sign in request"),  # run: open picker
            ({"factor_picker_ready": True}, "Verify your identity"),
            ({"factor_picker_ready": True}, "Verify your identity"),  # run: request SMS
            ({"otc_ready": True}, "Enter code"),
            ({"otc_ready": True}, "Enter code"),                    # run: enter code
        ],
        authenticated_after=5,
    )
    login.run()
    assert login.actions == [
        "username",
        "password",
        "open_picker",
        "request_sms",
        "enter_code",
    ]


def test_the_password_view_is_reached_before_the_password_is_ever_sent():
    """The combined view must not receive the password: Entra discards it."""
    login = ScriptedLogin(
        views=[(COMBINED, "Sign in")] * 3 + [({"password_ready": True}, "Enter password")],
        authenticated_after=1,
    )
    login.run()
    assert login.actions == ["username"]


def test_a_view_that_never_advances_fails_loudly(monkeypatch):
    monkeypatch.setattr(sso, "STEP_SETTLE_SECONDS", 0.01)
    login = ScriptedLogin(
        views=[({"password_ready": True}, "Enter password")], authenticated_after=99
    )
    with pytest.raises(ClientError, match="stalled"):
        login.run()
    assert login.actions == ["password"]


def test_sign_in_that_never_completes_fails_loudly(monkeypatch):
    monkeypatch.setattr(sso, "LOGIN_TIMEOUT_SECONDS", 0.01)
    login = ScriptedLogin(views=[({}, "")], authenticated_after=99)
    with pytest.raises(ClientError, match="did not complete within"):
        login.run()
    assert login.actions == []


def _message(text, when, *, from_me=False):
    return {"text": text, "date": when.isoformat(), "is_from_me": from_me}


def test_find_sms_code_returns_the_newest_microsoft_code():
    requested = datetime(2026, 8, 21, 14, 0, 0)
    rows = [
        _message("Use verification code 111111 for Microsoft authentication.", requested),
        _message(
            "Use verification code 222222 for Microsoft authentication.",
            requested + timedelta(seconds=40),
        ),
    ]
    assert sso.find_sms_code(rows, requested) == "222222"


def test_find_sms_code_ignores_a_code_from_before_the_request():
    requested = datetime(2026, 8, 21, 14, 0, 0)
    rows = [
        _message(
            "Use verification code 333333 for Microsoft authentication.",
            requested - timedelta(minutes=10),
        )
    ]
    with pytest.raises(ClientError, match="No Microsoft verification text"):
        sso.find_sms_code(rows, requested)


def test_find_sms_code_ignores_unrelated_and_outbound_messages():
    requested = datetime(2026, 8, 21, 14, 0, 0)
    rows = [
        _message("Your Spectrum code is 445566", requested + timedelta(seconds=5)),
        _message(
            "Use verification code 778899 for Microsoft authentication.",
            requested + timedelta(seconds=5),
            from_me=True,
        ),
    ]
    with pytest.raises(ClientError, match="No Microsoft verification text"):
        sso.find_sms_code(rows, requested)


def test_find_sms_code_tolerates_messages_db_clock_skew():
    requested = datetime(2026, 8, 21, 14, 0, 0)
    rows = [
        _message(
            "Use verification code 909090 for Microsoft authentication.",
            requested - timedelta(seconds=10),
        )
    ]
    assert sso.find_sms_code(rows, requested) == "909090"
