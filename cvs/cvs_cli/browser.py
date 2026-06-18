"""Browser automation for CVS CLI.

Declarative only — all auth-lifecycle behavior lives in
``cli_tools_shared.auth.BrowserAutomation``. CVS needs two non-default hooks:

* ``MANUAL_LOGIN`` — CVS's login flow rejects CDP-driven browsers (Akamai
  bot detection → "problem with your network address"), so login opens a plain
  browser for the user to log in by hand.
* ``AUTH_TOKEN_COOKIE`` + reject lists — a logged-out CVS session still mints an
  ``access_token`` cookie, but with ``aud == "guest-flow"``. Decoding the
  token's audience is the only reliable auth signal; the URL/selector
  heuristics false-positive on a dead session.
"""
from cli_tools_shared.auth import BrowserAutomation


class CvsBrowser(BrowserAutomation):
    SESSION_NAME = "cvs"
    LOGIN_URL = "https://www.cvs.com/account-login/look-up"
    AUTH_CHECK_URL = "https://www.cvs.com/pharmacy/rx/prescriptions"
    AUTH_URL_PATTERN = r"/account-login"
    MANUAL_LOGIN = True
    AUTH_TOKEN_COOKIE = "access_token"
    AUTH_TOKEN_REJECT_AUD = ("guest-flow",)
    AUTH_TOKEN_REJECT_CONTEXT = ("guest",)
