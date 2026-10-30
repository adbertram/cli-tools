"""Browser automation for MuseChat.

Muse keeps the URL at ``/`` when its web session expires and swaps the chat
UI for a logged-out landing page whose
``section[data-testid="native-auth-access-pane"]`` lists saved accounts.
Clicking the saved "Log in as ... using Facebook" card in the CLI's own
persistent profile re-authenticates through Facebook SSO with no password
(validated live 2026-10-30). The composer appears within about 6 seconds.
"""

from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError

COMPOSER_SELECTOR = 'textarea[aria-label="Message"]'
LOGIN_PANE_SELECTOR = 'section[data-testid="native-auth-access-pane"]'
SAVED_ACCOUNT_SELECTOR = (
    '[data-testid="native-auth-account-list"] '
    'button[aria-label^="Log in as "][aria-label$=" using Facebook"]'
)
SAVED_ACCOUNT_WAIT_MS = 10000
SAVED_ACCOUNT_LOGIN_TIMEOUT_MS = 30000
LOGIN_PANE_STATE = "login_pane"

# Resolves once Muse settles: "" when the composer is present and the
# logged-out pane is absent, "login_pane" when the pane is shown, and
# "no_composer" when neither appears within the bound.
AUTH_STATE_JS = r"""
async () => {
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    if (document.querySelector('section[data-testid="native-auth-access-pane"]')) return 'login_pane';
    if (document.querySelector('textarea[aria-label="Message"]')) return '';
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  return 'no_composer';
}
"""


def _log_in_with_saved_account(browser, page) -> None:
    """Resume the session by clicking the saved Facebook account card."""
    if page.evaluate(AUTH_STATE_JS) == "":
        return
    # The account list renders shortly after the pane itself.
    try:
        page.wait_for_selector(SAVED_ACCOUNT_SELECTOR, timeout=SAVED_ACCOUNT_WAIT_MS)
    except Exception as exc:
        raise BrowserAutomationError(
            "Muse is signed out and shows no saved account to resume headlessly."
        ) from exc
    page.locator(SAVED_ACCOUNT_SELECTOR).first.click()
    try:
        page.wait_for_selector(COMPOSER_SELECTOR, timeout=SAVED_ACCOUNT_LOGIN_TIMEOUT_MS)
    except Exception as exc:
        raise BrowserAutomationError(
            "Muse did not show the message composer after resuming the saved account."
        ) from exc


class MuseChatBrowser(BrowserAutomation):
    """Browser used by ``auth`` commands; ``auth login`` stays a headed login."""

    SESSION_NAME = "muse-chat"
    LOGIN_URL = "https://muse.ai/"
    AUTH_CHECK_URL = "https://muse.ai/"
    AUTH_CHECK_TTL = 0
    AUTH_URL_PATTERN = r"facebook\.com/.*/login|/login|/register"
    AUTH_FAILURE_PAGE_JS = AUTH_STATE_JS
    AUTH_SUCCESS_SELECTOR = COMPOSER_SELECTOR
    AUTH_LOGIN_FORM_SELECTOR = (
        f'{LOGIN_PANE_SELECTOR}, '
        'input[aria-label="Mobile number or email"], '
        'input[placeholder*="email" i]'
    )


class MuseChatSessionBrowser(MuseChatBrowser):
    """Browser used by chat commands; ``ensure_fresh_session`` resumes headlessly."""

    AUTH_LOGIN_HANDLER = staticmethod(_log_in_with_saved_account)
    AUTH_LOGIN_SETTLE_MS = 0
