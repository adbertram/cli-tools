"""Browser session automation for Progress ServiceNow."""

from cli_tools_shared.auth import BrowserAutomation

from .sso import run_sso_login


class ProgressServiceNowBrowser(BrowserAutomation):
    """BrowserAutomation hooks for Progress ServiceNow authentication.

    progress1.service-now.com authenticates through the Progress Entra tenant,
    so an expired session turns every ServiceNow URL into a Microsoft sign-in
    page. That sign-in is a multi-step challenge (password, then an
    Authenticator push that has to be swapped for an SMS code), which the
    selector/secret constants cannot express, so it is declared as an
    ``AUTH_LOGIN_HANDLER``. ``cli_tools_shared`` still owns the login
    lifecycle; :mod:`progress_servicenow_cli.sso` owns only the page
    choreography and the credential/MFA sources.
    """

    SESSION_NAME = "progress-servicenow"
    LOGIN_URL = "https://progress1.service-now.com/esc"
    AUTH_CHECK_URL = "https://progress1.service-now.com/esc"
    AUTH_URL_PATTERN = r"login\.microsoftonline\.com"
    AUTH_COOKIE_PATTERNS = [r"^glide_session_store$"]

    AUTH_LOGIN_HANDLER = staticmethod(run_sso_login)

    #: LastPass entry id holding the Progress SSO account credentials.
    LASTPASS_ENTRY = "4250464594169840461"

    #: Domain Entra requires on the account name (the sign-in page states it).
    LOGIN_EMAIL_DOMAIN = "progress.com"
