"""Declarative Vues login through the shared persistent browser engine.

Vues signs in only with Google or Apple (Supabase GoTrue, project
ycfkjzqusvyzbrisjziy). `auth login` runs the standard headed browser flow: the
person signs in on vues.app and presses Enter, then the post-login hook saves
the Supabase session from the vues.app ``sb-<ref>-auth-token`` cookie
(@supabase/ssr: ``base64-`` prefixed base64url JSON, split into ``.0``/``.1``
chunks when large) as runtime auth state.

There is deliberately no AUTH_CHECK_URL: after login the CLI is HTTP-only, so
the shared engine answers "is this profile signed in?" from the saved session
(``Config.has_saved_session``) and `auth status`/`auth test` verify it with a
live HTTP call (``BROWSER_SESSION_REQUIRES_API_TEST``). Opening vues.app again
would also let the web app replay the refresh token the CLI already rotated,
which makes Supabase revoke the whole session.
"""
from cli_tools_shared.auth import BrowserAutomation

from .client import SESSION_COOKIE, save_browser_session


class VuesBrowser(BrowserAutomation):
    LOGIN_URL = "https://vues.app/login"
    # The Vues login page, an unauthenticated app route (both end on /login)
    # and the Google/Apple sign-in pages all mean "not signed in yet".
    AUTH_URL_PATTERN = r"/login(?:/|\?|$)|accounts\.google\.com|appleid\.apple\.com"
    # @supabase/ssr keeps the session in this cookie (verified 2026-10-15 on the
    # signed-in profile; localStorage holds only ``<cookie>-user``).
    AUTH_COOKIE_PATTERNS = [rf"^{SESSION_COOKIE}(?:\.\d+)?$"]
    SESSION_NAME = "vues"
    # Post-login hook (declared, not overridden): save the session for HTTP use.
    _on_authenticated = save_browser_session
