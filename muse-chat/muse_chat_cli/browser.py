"""Browser automation for MuseChat."""

from cli_tools_shared.auth import BrowserAutomation


class MuseChatBrowser(BrowserAutomation):
    """Browser automation for MuseChat via cli_tools_shared.auth.BrowserAutomation.

    Declarative hooks only — no methods. The base class handles auth lifecycle
    using these class-level constants. See
    <cli-tools-root>/_repo/skills/cli-tool-browser-expert/SKILL.md for
    selector validation guidance.
    """

    SESSION_NAME = "muse-chat"
    LOGIN_URL = "https://muse.ai/"
    AUTH_CHECK_URL = "https://muse.ai/"
    AUTH_CHECK_TTL = 0
    AUTH_URL_PATTERN = r"facebook\.com/.*/login|/login|/register"
    AUTH_SUCCESS_SELECTOR = 'textarea[aria-label="Message"]'
    AUTH_LOGIN_FORM_SELECTOR = (
        'input[aria-label="Mobile number or email"], '
        'input[placeholder*="email" i]'
    )
