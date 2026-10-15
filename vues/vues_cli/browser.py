"""Declarative Vues login through the shared persistent browser engine.

Vues signs in only with Google or Apple (Supabase GoTrue, project
ycfkjzqusvyzbrisjziy), so the login page blocks automated browsers and
`auth login` opens a real one for the person to complete the provider sign-in
by hand (MANUAL_LOGIN). The resulting Supabase session lives in the page's
localStorage under ``sb-<ref>-auth-token``; the client reads it once and then
talks to the Vues API (api.evrgreen.ai) over plain HTTP.
"""
from cli_tools_shared.auth import BrowserAutomation

from .config import SUPABASE_REF


class VuesBrowser(BrowserAutomation):
    LOGIN_URL = "https://vues.app/login"
    AUTH_CHECK_URL = "https://vues.app/clipper"
    # Both the login page and an unauthenticated app route end on /login.
    AUTH_URL_PATTERN = r"/login(?:/|\?|$)"
    AUTH_SUCCESS_URL = r"/clipper"
    # Supabase stores the session here once Google/Apple sign-in completes.
    AUTH_STORAGE_KEY = f"sb-{SUPABASE_REF}-auth-token"
    SESSION_NAME = "vues"
    MANUAL_LOGIN = True
