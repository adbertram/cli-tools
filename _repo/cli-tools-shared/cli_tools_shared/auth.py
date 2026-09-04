"""Shared browser automation module for CLI tools.

Persistent Chromium user-data-dir model: cookies, localStorage, IndexedDB,
service workers, and cache all persist natively in
``<browser_data_dir>/chromium-profile/``. HTTP-backed code paths fetch cookies
live from the running browser-harness daemon via
:meth:`BrowserAutomation.live_cookies`.

CLI tools subclass :class:`BrowserAutomation` and declare class-level hooks::

    class MyBrowser(BrowserAutomation):
        LOGIN_URL = "https://example.com/login"
        AUTH_CHECK_URL = "https://example.com/dashboard"
        AUTH_URL_PATTERN = r"/login"
        SESSION_NAME = "mysite"
"""

import base64
import binascii
import hashlib
import hmac
import json
import os
import random
import re
import struct
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ._debug_logging import get_debug_logger
from .exceptions import ClientError
from .output import print_info, print_success, print_warning
from .browser import BrowserHarnessService, BrowserHarnessError
from .browser.processes import (
    list_process_commands,
    profile_process_pids,
    terminate_profile_processes,
)

logger = get_debug_logger("cli_tools.auth")


class BrowserAutomationError(ClientError):
    """Browser automation error.

    Subclasses :class:`~cli_tools_shared.exceptions.ClientError` so the shared
    ``run_app`` error path (which catches ``ClientError``) prints browser
    failures -- including HTTP 429/5xx error pages, see
    :meth:`BrowserAutomation._raise_for_http_error_status` -- as one-line
    errors instead of tracebacks.
    """

    def __init__(self, message: str, cause: Exception = None):
        self.message = message
        self.cause = cause
        super().__init__(message)


@dataclass(frozen=True)
class AuthResult:
    """Result of an authentication check. Truthy when authenticated."""
    authenticated: bool
    live_check: bool
    available: bool = True

    def __bool__(self) -> bool:
        return self.authenticated


# --- Interstitial walls -----------------------------------------------------
# Sites front their real content with walls that all look like "the page did
# not load" to a downstream selector wait, but need opposite handling. A tool
# declares its walls as ``BrowserAutomation.INTERSTITIALS`` and the base class
# resolves them on every navigation, so the tool stays declarative and every
# browser-backed command inherits the handling.

#: Wait the wall out in place. For a SELF-CLEARING JS check that redirects
#: itself to the requested content (Cloudflare "Checking your browser", eBay's
#: "Pardon Our Interruption"). Re-navigating abandons the redirect the site
#: just issued and spends another request against its rate budget.
INTERSTITIAL_SETTLE = "settle"
#: Re-navigate after a jittered exponential backoff. For a server-side error
#: or rate wall that only clears once the request rate drops.
INTERSTITIAL_RELOAD = "reload"
#: Stop immediately. For a real human-verification challenge, which is never
#: solved, clicked through, or reloaded around.
INTERSTITIAL_ABORT = "abort"


@dataclass(frozen=True)
class Interstitial:
    """One declarative wall rule.

    Markers are lowercase substrings. ``url_markers`` are matched against the
    page URL; ``title_markers`` against the document title; ``body_markers``
    against the title and visible body text together. Keep body markers narrow
    — phrases like "something went wrong" legitimately appear inside real page
    content and will misfire.

    Rules are evaluated in declaration order and the first match wins, so
    declare ``INTERSTITIAL_ABORT`` rules first: a human-verification wall must
    never be masked by a broader retryable rule.
    """

    kind: str
    label: str
    strategy: str = INTERSTITIAL_RELOAD
    url_markers: Tuple[str, ...] = field(default_factory=tuple)
    title_markers: Tuple[str, ...] = field(default_factory=tuple)
    body_markers: Tuple[str, ...] = field(default_factory=tuple)

    def matches(self, url: str = "", title: str = "", body: str = "") -> bool:
        url_l = (url or "").lower()
        title_l = (title or "").lower()
        text = f"{title_l} {(body or '').lower()}"
        return (
            any(m in url_l for m in self.url_markers)
            or any(m in title_l for m in self.title_markers)
            or any(m in text for m in self.body_markers)
        )


def classify_interstitial(
    rules, url: str = "", title: str = "", body: str = ""
) -> Optional[Interstitial]:
    """Return the first :class:`Interstitial` in ``rules`` matching the page.

    ``None`` means the page is real content. Exposed at module level so a tool
    can classify a page-state dict it already captured (e.g. inside a scraper's
    own blocker check) against the same rules the navigation path uses.
    """
    for rule in rules:
        if rule.matches(url=url, title=title, body=body):
            return rule
    return None


# --- Main-document HTTP status --------------------------------------------
# Chromium exposes the real HTTP status of the main document via Navigation
# Timing Level 2. A site answering 429 (rate limit) or >=500 (outage) renders
# a normal-looking error document at the requested URL, so a scraper that only
# reads the DOM records the error page as valid (often empty) content --
# silent data loss. ``HTTP_ERROR_STATUS_JS`` lets the engine read the status
# after a navigation settles and refuse to hand the error page back as data.
HTTP_ERROR_STATUS_JS = """() => {
  const nav = performance.getEntriesByType('navigation');
  const entry = nav && nav.length ? nav[0] : null;
  return entry && Number.isFinite(entry.responseStatus) ? entry.responseStatus : null;
}"""


# Daemon-key sanity: ``BU_NAME`` is used as the AF_UNIX socket basename under
# ``/tmp/cli-tools-bh/<key>``; macOS caps paths at 104 bytes. Hash long or
# unsafe keys to a short, deterministic prefix.
_SAFE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def _safe_daemon_key(session: str) -> str:
    """Return a daemon-safe key for ``session``.

    Short, alnum-plus-underscore-dash names pass through. Anything longer
    than 32 chars or containing other characters is hashed to ``bh-<sha8>``.
    """
    if not session:
        raise BrowserAutomationError("Daemon session key must be non-empty")
    if _SAFE_KEY_RE.fullmatch(session):
        return session
    return f"bh-{hashlib.sha256(session.encode()).hexdigest()[:8]}"


def _generate_totp_code(secret: str, *, timestamp: Optional[float] = None) -> str:
    """Generate the current six-digit RFC 6238 code for a Base32 seed."""
    normalized = re.sub(r"\s+", "", secret).upper()
    if not normalized:
        raise BrowserAutomationError(
            "Browser-login TOTP secret is not valid Base32."
        )
    normalized += "=" * ((8 - len(normalized) % 8) % 8)
    try:
        key = base64.b32decode(normalized, casefold=True)
    except (binascii.Error, ValueError, TypeError) as exc:
        raise BrowserAutomationError(
            "Browser-login TOTP secret is not valid Base32."
        ) from exc
    counter = int((time.time() if timestamp is None else timestamp) // 30)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = int.from_bytes(digest[offset:offset + 4], "big") & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


class BrowserAutomation:
    """Base class for browser automation in CLI tools.

    Persistent Chromium user-data-dir per profile holds cookies,
    localStorage, IndexedDB, service workers, and cache — there is no
    snapshot/restore. Subclasses declare hooks; the base class drives
    headed login and headless command execution against the persistent
    profile.
    """

    # --- Class-level hooks (subclasses override) ---
    AUTH_CHECK_TTL = 300  # Seconds to cache a successful auth check (0 = always live)
    LOGIN_URL = ""
    AUTH_CHECK_URL = ""
    AUTH_URL_PATTERN = ""        # Regex — URL matches → user is on login page
    AUTH_FAILURE_URL_PATTERN = ""  # Regex — URL matches → service requires re-auth/confirmation
    # JS evaluated on the auth-check page; truthy result → NOT authenticated.
    # For services that serve a URL-preserving error/interstitial at the
    # authenticated URL, so URL patterns alone report a false healthy session.
    AUTH_FAILURE_PAGE_JS = ""
    AUTH_COOKIE_PATTERNS = []    # Cookie name regexes indicating auth
    AUTH_SUCCESS_URL = ""        # URL pattern indicating successful login
    AUTH_SUCCESS_SELECTOR = ""   # CSS/locator selector visible when authenticated
    AUTH_LOGIN_FORM_SELECTOR = ""  # CSS/locator selector for login-form elements; ABSENT → authenticated
    AUTH_LOGIN_FORM_LINK_SELECTOR = ""  # Link on LOGIN_URL to follow when the credential form lives on a page behind it
    AUTH_LOGIN_USERNAME_SELECTOR = ""  # Selector for an approved non-interactive username field
    AUTH_LOGIN_PASSWORD_SELECTOR = ""  # Selector for an approved non-interactive password field
    AUTH_LOGIN_SUBMIT_SELECTOR = ""  # Selector for an approved non-interactive submit control
    AUTH_LOGIN_ERROR_SELECTOR = ""  # Selector visible when submitted credentials are rejected
    AUTH_LOGIN_USERNAME_SECRET = ""  # CLI-tools secret-manager name
    AUTH_LOGIN_PASSWORD_SECRET = ""  # CLI-tools secret-manager name
    AUTH_LOGIN_TOTP_SELECTOR = ""  # Selector for a TOTP challenge input
    AUTH_LOGIN_TOTP_SUBMIT_SELECTOR = ""  # Selector for the TOTP submit control
    AUTH_LOGIN_TOTP_SECRET = ""  # CLI-tools secret-manager Base32 seed name
    AUTH_LOGIN_AUTOMATION_TIMEOUT = 30  # Seconds to reach authenticated state after submit
    AUTH_UNAVAILABLE_SELECTOR = ""  # CSS/locator selector — if visible, authenticated but not available
    AUTH_STORAGE_KEY = ""        # localStorage key; True if key exists and has a value
    LOGIN_TIMEOUT = 300          # Seconds to wait for manual login
    SESSION_NAME = ""            # Named session used for the per-tool user-data-dir
    # Token-cookie auth check (declarative). When AUTH_TOKEN_COOKIE is set, the
    # auth check decodes that cookie's JWT and treats the session as
    # authenticated only when 'aud'/'x-user-context-type' are NOT in the reject
    # lists. It polls for a guest→authenticated token upgrade (some sites mint a
    # short-lived guest token on load, then upgrade it).
    AUTH_TOKEN_COOKIE = ""
    AUTH_TOKEN_REJECT_AUD = ()       # JWT 'aud' values meaning NOT authenticated
    AUTH_TOKEN_REJECT_CONTEXT = ()   # 'x-user-context-type' values meaning NOT authenticated
    AUTH_TOKEN_POLL_SECONDS = 6
    # Bot-protection challenge settling. A managed Cloudflare/DataDome challenge
    # clears with no interaction, but it can take most of a minute, so a single
    # immediate check after login reports a false block. Tools behind such a
    # wall raise AUTH_CHALLENGE_ATTEMPTS; the default of 1 keeps the historic
    # single check for every other tool.
    AUTH_CHALLENGE_ATTEMPTS = 1
    AUTH_CHALLENGE_POLL_MS = 3000
    # Interstitial walls served INSTEAD of the requested content (see the
    # Interstitial dataclass above). Declare them most-severe first. The
    # default empty tuple keeps navigation unchanged for tools that declare
    # none. When set, get_page returns only once the page has settled onto
    # real content, or raises naming the specific wall — so a downstream
    # selector wait can never misdiagnose the failure as "element not found".
    INTERSTITIALS: Tuple[Interstitial, ...] = ()
    INTERSTITIAL_MAX_ATTEMPTS = 4       # Navigation attempts (first load + reloads)
    INTERSTITIAL_BASE_DELAY_MS = 4000   # Backoff before the first reload
    INTERSTITIAL_MAX_DELAY_MS = 32000   # Ceiling for the exponential ramp
    INTERSTITIAL_JITTER_RATIO = 0.5     # Extra 0..N x base, so retries desynchronize
    INTERSTITIAL_SETTLE_TIMEOUT_MS = 20000  # Budget for a self-clearing wall
    INTERSTITIAL_POLL_INTERVAL_MS = 1000    # Poll cadence while it clears
    # Real HTTP status of the main document (see HTTP_ERROR_STATUS_JS). When
    # True (default), get_page raises after navigation once the settled page
    # turns out to be an HTTP 429 or >=500 error document, so the error page
    # is never scraped as if it were content. Opt out per tool with False;
    # the check is skipped whenever the status cannot be read.
    HTTP_ERROR_STATUS_RAISE = True
    # Automation-free login. When True, authenticate() opens a PLAIN browser (no
    # --remote-debugging-port, no CDP, no webdriver patching) for the user to log
    # in by hand — for sites whose login flow blocks automated browsers — then
    # reads the resulting session through the normal cookie path.
    MANUAL_LOGIN = False
    # Fully non-interactive login. A callable ``(browser, page) -> None`` that
    # completes a site-specific sign-in on the already-open HEADLESS page.
    # Declare it with ``staticmethod(...)`` so the subclass stays declarative.
    #
    # Use it when the identity provider's sign-in flow is a multi-step
    # challenge the selector/secret constants above cannot express (an
    # alternate-factor picker, a code delivered out of band, a consent
    # interstitial). When set, ``authenticate()`` never opens a headed browser
    # and never waits on a terminal: this class still owns the login lifecycle
    # (when to sign in, how to verify, how to persist), the handler owns only
    # the choreography on the page.
    AUTH_LOGIN_HANDLER = None
    # Milliseconds to let the login page settle before the handler runs.
    AUTH_LOGIN_SETTLE_MS = 5000

    def __init__(self, config):
        self.config = config
        self._page: Optional[BrowserHarnessService] = None
        self._service: Optional[BrowserHarnessService] = None
        self._auth_verified_at: float = 0

    # --- Config accessors ---

    def _get_browser_data_dir(self) -> Path:
        if hasattr(self.config, "get_browser_data_dir"):
            return self.config.get_browser_data_dir()
        if hasattr(self.config, "browser_data_dir"):
            d = self.config.browser_data_dir
            return d if isinstance(d, Path) else Path(d)
        raise BrowserAutomationError(
            "Config must provide get_browser_data_dir() or browser_data_dir"
        )

    def _get_persistent_profile_dir(self) -> Path:
        """Path to the persistent Chromium user-data-dir for this profile."""
        if hasattr(self.config, "get_persistent_profile_dir"):
            return self.config.get_persistent_profile_dir()
        return self._get_browser_data_dir() / "chromium-profile"

    def _tool_name(self) -> str:
        if hasattr(self.config, "_tool_name"):
            return self.config._tool_name
        return self.config.__class__.__name__.lower().replace("config", "") or "default"

    def _profile_name(self) -> str:
        """Active profile name. Defaults to ``default`` when the config
        does not expose ``get_active_profile_name``.
        """
        if hasattr(self.config, "get_active_profile_name"):
            try:
                name = self.config.get_active_profile_name()
            except Exception:  # pragma: no cover — defensive
                name = ""
            if name:
                return name
        return "default"

    def _headless_enabled(self) -> bool:
        if hasattr(self.config, "headless"):
            return bool(self.config.headless)
        if getattr(type(self), "AUTOMATION_HEADED", False):
            return False
        return True

    def _browser_user_agent(self) -> str:
        if hasattr(self.config, "browser_user_agent"):
            return str(self.config.browser_user_agent)
        return ""

    def _browser_window_size(self) -> str:
        if hasattr(self.config, "browser_window_size"):
            return str(self.config.browser_window_size)
        return ""

    def _session_name(self) -> str:
        """Daemon-scope name: ``<tool>-<profile>``.

        ``SESSION_NAME`` (set by subclasses) is treated as the tool component.
        Falls back to the config-derived tool name.
        """
        tool = self.SESSION_NAME or self._tool_name()
        if not tool:
            raise BrowserAutomationError(
                "BrowserAutomation: tool/session name must be non-empty"
            )
        profile = self._profile_name()
        if not profile:
            raise BrowserAutomationError(
                "BrowserAutomation: profile name must be non-empty"
            )
        return f"{tool}-{profile}"

    def _get_service(self) -> BrowserHarnessService:
        """Get a cached :class:`BrowserHarnessService` for this profile."""
        if self._service is None:
            self._service = BrowserHarnessService(
                _safe_daemon_key(self._session_name())
            )
        return self._service

    _safe_url_for_log = staticmethod(BrowserHarnessService._safe_url_for_log)

    def _prompt_enter_eof_safe(self, message: str = "", *, allow_no_tty: bool = False) -> bool:
        """Block until the user presses Enter; tolerate non-TTY stdin.

        ``input()`` raises ``EOFError`` when stdin is closed or piped. Fall
        back to ``/dev/tty`` for the controlling terminal. For manual browser
        login in non-interactive runtimes, callers may opt into a browser-close
        completion signal instead of exiting immediately.
        """
        try:
            input(message)
            return True
        except EOFError:
            pass

        try:
            with open("/dev/tty", "r") as tty:
                if message:
                    sys.stderr.write(message)
                    sys.stderr.flush()
                tty.readline()
                return True
        except OSError as e:
            if allow_no_tty:
                sys.stderr.write(
                    "Browser auth is running without an interactive terminal "
                    f"({e}).\n"
                    "Continuing with the browser completion signal configured "
                    "for this login flow.\n"
                )
                return False
            sys.stderr.write(
                "Browser auth requires an interactive terminal to confirm "
                f"login completion, but stdin and /dev/tty are unavailable ({e}).\n"
                "Re-run 'auth login' from an interactive shell.\n"
            )
            sys.exit(2)

    # ==================== Public Interface ====================

    def is_authenticated(self) -> AuthResult:
        """Check auth via live browser check, with TTL caching."""
        if self.AUTH_CHECK_TTL and self._auth_verified_at:
            elapsed = time.time() - self._auth_verified_at
            if elapsed < self.AUTH_CHECK_TTL:
                logger.debug("is_authenticated: cached=True (%.0fs ago, ttl=%ds)",
                             elapsed, self.AUTH_CHECK_TTL)
                return AuthResult(authenticated=True, live_check=False)

        if not self.AUTH_CHECK_URL:
            # No live check possible — fall back to the on-disk profile check.
            saved = self.config.has_saved_session() if hasattr(self.config, "has_saved_session") else False
            logger.debug("is_authenticated: no AUTH_CHECK_URL, falling back to has_saved_session=%s", saved)
            if saved:
                self._auth_verified_at = time.time()
            return AuthResult(authenticated=saved, live_check=True, available=saved)

        try:
            page = self.get_page(self.AUTH_CHECK_URL)
            if not self.AUTH_COOKIE_PATTERNS:
                page.wait_for_timeout(2000)
            result = self._check_auth(page)
            available = self._check_available(page) if result else True
            logger.debug("is_authenticated: live check result=%s available=%s", result, available)
            if result:
                self._auth_verified_at = time.time()
            return AuthResult(authenticated=result, available=available, live_check=True)
        except Exception as e:
            logger.debug("is_authenticated: live check failed: %s", e)
            if isinstance(e, BrowserAutomationError):
                raise
            raise BrowserAutomationError(
                f"Browser authentication check unavailable: {e}",
                cause=e,
            ) from e
        finally:
            self.close()

    def authenticate(self, force: bool = False):
        """Interactive login via headed persistent browser."""
        logger.debug("authenticate: force=%s session=%s", force, self._session_name())

        if type(self).AUTH_LOGIN_HANDLER is not None:
            return self._authenticate_noninteractive(force)

        if self.MANUAL_LOGIN:
            return self._authenticate_manual(force)

        has_saved = (
            self.config.has_saved_session()
            if hasattr(self.config, "has_saved_session")
            else False
        )
        if has_saved and not force:
            logger.debug("authenticate: saved session already exists, skipping interactive login")
            return

        if force:
            logger.debug("authenticate: force=True, clearing existing session")
            self.clear_session()

        print_info(f"Opening browser for login at: {self.LOGIN_URL}")
        print_info("Log in, then press Enter here to save the session and close the browser.")

        svc = self._get_service()
        try:
            svc.browser_open(
                self.LOGIN_URL,
                headed=True,
                persistent_profile_dir=self._get_persistent_profile_dir(),
            )
        except BrowserHarnessError as e:
            logger.debug("authenticate: browser open FAILED: %s", e)
            raise BrowserAutomationError(f"Failed to open browser: {e}") from e

        confirmed = self._prompt_enter_eof_safe(allow_no_tty=True)
        if not confirmed:
            print_info(
                "No interactive terminal is available; verifying the browser "
                "session directly."
            )

        self._service = svc
        self._page = svc

        has_hook = type(self)._on_authenticated is not BrowserAutomation._on_authenticated
        page = svc
        try:
            page.wait_for_timeout(2000)
            if not confirmed and not self._check_auth_settled(page):
                self._complete_noninteractive_login(page)
            if has_hook:
                logger.debug("authenticate: running post-auth hook")
                self._on_authenticated(page)
            if self.AUTH_CHECK_URL:
                # Verify against the same ground truth `is_authenticated()` uses.
                # The headed browser can be left on any post-login landing page
                # (or a redirect target with a query string), so checking the
                # current page would report a false negative.
                logger.debug("authenticate: navigating to AUTH_CHECK_URL for final verification")
                page.goto(self.AUTH_CHECK_URL)
                if not self.AUTH_COOKIE_PATTERNS:
                    page.wait_for_timeout(2000)
            if not self._check_auth_settled(page):
                raise BrowserAutomationError("Browser session is not authenticated after login.")
        finally:
            self.close()

        persisted = self.is_authenticated()
        if not persisted:
            raise BrowserAutomationError(
                "Browser session did not persist after reopening. "
                "Log in again and ensure the service keeps the session across browser restarts."
            )

        self._auth_verified_at = time.time()
        logger.debug("authenticate: complete")
        print_success("Authentication complete.")

    def _authenticate_noninteractive(self, force: bool = False) -> None:
        """Sign in headlessly through ``AUTH_LOGIN_HANDLER``.

        No terminal prompt and no visible browser window: this path exists so a
        session whose identity provider requires a multi-step challenge can be
        refreshed by automation.

        ``force`` does NOT wipe the persistent profile here. The Chromium
        user-data-dir carries the identity provider's device-trust and
        "remember this device" state; discarding it guarantees a fresh MFA
        challenge on every refresh. A successful sign-in overwrites the session
        cookies regardless. (Same reasoning as :meth:`_authenticate_manual`.)

        Raises:
            BrowserAutomationError: When the handler finishes without an
                authenticated session, or when that session does not survive a
                browser restart.
        """
        logger.debug("_authenticate_noninteractive: force=%s", force)
        has_saved = (
            self.config.has_saved_session()
            if hasattr(self.config, "has_saved_session")
            else False
        )
        if has_saved and not force:
            logger.debug("_authenticate_noninteractive: saved session present, nothing to do")
            return

        handler = type(self).AUTH_LOGIN_HANDLER
        page = self.get_page(self.LOGIN_URL)
        try:
            page.wait_for_timeout(self.AUTH_LOGIN_SETTLE_MS)
            handler(self, page)
            if self.AUTH_CHECK_URL:
                # Verify against the same ground truth ``is_authenticated()``
                # uses; the flow can land on any post-login page.
                page.goto(self.AUTH_CHECK_URL)
                page.wait_for_timeout(2000)
            if not self._check_auth_settled(page):
                raise BrowserAutomationError(
                    "Non-interactive login finished but the session is not authenticated "
                    f"at {self.AUTH_CHECK_URL or page.url}."
                )
        finally:
            self.close()

        self._auth_verified_at = 0
        if not self.is_authenticated():
            raise BrowserAutomationError(
                "Browser session did not persist after reopening. The service did not keep "
                "the session across browser restarts."
            )
        self._auth_verified_at = time.time()
        logger.debug("_authenticate_noninteractive: complete")
        print_success("Authentication complete.")

    def _complete_noninteractive_login(self, page) -> None:
        """Submit explicitly configured browser credentials without a terminal."""
        settings = (
            self.AUTH_LOGIN_USERNAME_SELECTOR,
            self.AUTH_LOGIN_PASSWORD_SELECTOR,
            self.AUTH_LOGIN_SUBMIT_SELECTOR,
            self.AUTH_LOGIN_USERNAME_SECRET,
            self.AUTH_LOGIN_PASSWORD_SECRET,
        )
        if not any(settings):
            return
        if not all(settings):
            raise BrowserAutomationError(
                "Non-interactive browser login is partially configured; username/password "
                "selectors, submit selector, and both secret names are required."
            )

        # Some services open LOGIN_URL on a landing page that only links to the
        # real credential form (e.g. a marketing page whose "LOGIN" link starts
        # a stateful /oauth/authorize redirect). Follow that link first so the
        # selectors below are matched against the form, not the landing page.
        if self.AUTH_LOGIN_FORM_LINK_SELECTOR and not self._is_login_page(page):
            login_link = page.locator(self.AUTH_LOGIN_FORM_LINK_SELECTOR)
            if login_link.count() == 0:
                raise BrowserAutomationError(
                    "Non-interactive browser login could not find the login-form link "
                    f"{self.AUTH_LOGIN_FORM_LINK_SELECTOR!r} on {page.url}."
                )
            href = login_link.first.get_attribute("href")
            if not href:
                raise BrowserAutomationError(
                    f"Login-form link {self.AUTH_LOGIN_FORM_LINK_SELECTOR!r} has no href."
                )
            page.goto(href)
            page.wait_for_selector(
                self.AUTH_LOGIN_USERNAME_SELECTOR, state="visible", timeout=15000
            )

        totp_settings = (
            self.AUTH_LOGIN_TOTP_SELECTOR,
            self.AUTH_LOGIN_TOTP_SUBMIT_SELECTOR,
            self.AUTH_LOGIN_TOTP_SECRET,
        )
        if any(totp_settings) and not all(totp_settings):
            raise BrowserAutomationError(
                "Non-interactive browser TOTP is partially configured; input selector, "
                "submit selector, and secret name are required."
            )

        controls = (
            ("username", page.locator(self.AUTH_LOGIN_USERNAME_SELECTOR)),
            ("password", page.locator(self.AUTH_LOGIN_PASSWORD_SELECTOR)),
            ("submit", page.locator(self.AUTH_LOGIN_SUBMIT_SELECTOR)),
        )
        for label, locator in controls:
            if locator.count() != 1 or not locator.first.is_visible():
                raise BrowserAutomationError(
                    f"Non-interactive browser login requires one visible {label} control."
                )
        if not controls[2][1].first.is_enabled():
            raise BrowserAutomationError(
                "Non-interactive browser login submit control is disabled."
            )

        from .config import read_cli_tool_secret, secret_manager_set_command

        username = read_cli_tool_secret(self.AUTH_LOGIN_USERNAME_SECRET)
        password = read_cli_tool_secret(self.AUTH_LOGIN_PASSWORD_SECRET)
        if username is None:
            raise BrowserAutomationError(
                "Missing browser-login username secret. Set it with: "
                f"{secret_manager_set_command(self.AUTH_LOGIN_USERNAME_SECRET)}"
            )
        if password is None:
            raise BrowserAutomationError(
                "Missing browser-login password secret. Set it with: "
                f"{secret_manager_set_command(self.AUTH_LOGIN_PASSWORD_SECRET)}"
            )

        try:
            page.fill(self.AUTH_LOGIN_USERNAME_SELECTOR, username)
            page.fill(self.AUTH_LOGIN_PASSWORD_SELECTOR, password)
            controls[2][1].first.click()
        finally:
            username = None
            password = None

        deadline = time.time() + self.AUTH_LOGIN_AUTOMATION_TIMEOUT
        totp_submitted = False
        while time.time() < deadline:
            page.wait_for_timeout(1000)
            if self.AUTH_LOGIN_ERROR_SELECTOR:
                error = page.locator(self.AUTH_LOGIN_ERROR_SELECTOR)
                if error.count() and error.first.is_visible():
                    raise BrowserAutomationError(
                        "Browser login credentials were rejected by the service."
                    )
            if self._check_auth(page):
                return
            if all(totp_settings) and not totp_submitted:
                totp_input = page.locator(self.AUTH_LOGIN_TOTP_SELECTOR)
                if totp_input.count() == 1 and totp_input.first.is_visible():
                    totp_submit = page.locator(self.AUTH_LOGIN_TOTP_SUBMIT_SELECTOR)
                    if totp_submit.count() != 1 or not totp_submit.first.is_visible():
                        raise BrowserAutomationError(
                            "Non-interactive browser TOTP requires one visible submit control."
                        )
                    if not totp_submit.first.is_enabled():
                        raise BrowserAutomationError(
                            "Non-interactive browser TOTP submit control is disabled."
                        )
                    totp_secret = read_cli_tool_secret(self.AUTH_LOGIN_TOTP_SECRET)
                    if totp_secret is None:
                        raise BrowserAutomationError(
                            "Missing browser-login TOTP secret. Set the Base32 seed with: "
                            f"{secret_manager_set_command(self.AUTH_LOGIN_TOTP_SECRET)}"
                        )
                    totp_code = None
                    try:
                        totp_code = _generate_totp_code(totp_secret)
                        page.fill(self.AUTH_LOGIN_TOTP_SELECTOR, totp_code)
                        totp_submit.first.click()
                        totp_submitted = True
                    finally:
                        totp_secret = None
                        totp_code = None
        raise BrowserAutomationError(
            "Non-interactive browser login did not reach an authenticated state "
            f"within {self.AUTH_LOGIN_AUTOMATION_TIMEOUT} seconds."
        )

    # ---- Automation-free login (MANUAL_LOGIN) ----

    def _authenticate_manual(self, force: bool = False) -> None:
        """Interactive login WITHOUT browser automation (no CDP attached).

        For sites whose login flow rejects CDP-driven browsers (bot detection).
        Launches a PLAIN browser bound to the persistent profile, waits for the
        user to log in by hand (OTP/CAPTCHA/passkey all work), then reads the
        resulting session through the normal cookie path. ``force`` does NOT
        wipe the profile here: preserving the user-data-dir keeps device-trust
        cookies that help the manual login pass risk scoring; the fresh login
        overwrites the session cookies regardless.
        """
        from .browser.driver import _chrome_binary

        # Release any CDP browser (e.g. from a pre-login auth check) so the
        # persistent profile is unlocked for the plain browser.
        self.close()

        profile_dir = self._get_persistent_profile_dir()
        profile_dir.mkdir(parents=True, exist_ok=True)

        chrome = os.environ.get("CLI_TOOLS_CHROME_BINARY") or _chrome_binary()
        args = [
            chrome,
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            self.LOGIN_URL,
        ]
        print_info("Opening a normal browser window for login (no automation attached).")
        print_info("Log in fully — finish any OTP/CAPTCHA — until your account page is visible.")
        print_info("Then come back here and press Enter to capture the session.")

        proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        try:
            confirmed = self._prompt_enter_eof_safe(allow_no_tty=True)
            if not confirmed:
                self._wait_for_manual_browser_close(proc, profile_dir)
        finally:
            self._quit_login_chrome(proc, profile_dir)

        if not self.is_authenticated():
            raise BrowserAutomationError(
                "Session is still not authenticated. Make sure you completed "
                "login (your account page was visible) before pressing Enter, "
                "then run login again."
            )
        self._auth_verified_at = time.time()
        print_success("Authentication complete.")

    def _wait_for_manual_browser_close(self, proc, profile_dir) -> None:
        """Wait until the user closes the plain browser for this profile."""
        deadline = time.time() + self.LOGIN_TIMEOUT
        saw_profile_process = False
        while time.time() < deadline:
            try:
                pids = profile_process_pids(
                    profile_dir,
                    processes=list_process_commands(),
                )
            except RuntimeError as exc:
                raise BrowserAutomationError(
                    f"Failed to inspect browser processes for manual login: {exc}"
                ) from exc
            if pids:
                saw_profile_process = True
            elif saw_profile_process or proc.poll() is not None:
                return
            time.sleep(1)
        raise BrowserAutomationError(
            "Timed out waiting for the manual login browser window to close."
        )

    def _quit_login_chrome(self, proc, profile_dir) -> None:
        """Quit the plain login browser bound to this profile so cookies flush
        and the user-data-dir lock is released. Scoped to THIS profile's
        ``--user-data-dir`` so the user's other browser windows are untouched.
        """
        try:
            proc.terminate()
        except Exception:
            pass
        terminate_profile_processes(profile_dir)
        time.sleep(3)
        lock = Path(profile_dir) / "SingletonLock"
        try:
            if lock.is_symlink() or lock.exists():
                lock.unlink()
        except OSError:
            pass

    # ---- Token-cookie auth check (AUTH_TOKEN_COOKIE) ----

    def _check_token_cookie_auth(self, page) -> bool:
        """True when ``AUTH_TOKEN_COOKIE`` holds an authenticated-user JWT.

        Polls for a guest→authenticated token upgrade (some sites mint a
        short-lived guest token on page load, then upgrade it after a
        validation XHR), returning True as soon as an accepted token appears.
        """
        polls = max(1, int(self.AUTH_TOKEN_POLL_SECONDS))
        for attempt in range(polls):
            try:
                cookies = page.cookie_list()
            except Exception:
                return False
            token = next(
                (c.get("value") for c in cookies
                 if c.get("name") == self.AUTH_TOKEN_COOKIE and c.get("value")),
                None,
            )
            if token and self._token_is_authenticated(token):
                return True
            if attempt < polls - 1:
                try:
                    page.wait_for_timeout(1000)
                except Exception:
                    break
        return False

    def _token_is_authenticated(self, token: str) -> bool:
        """Decode a JWT and accept it unless its claims are in the reject lists.

        A malformed payload (non-3-part, bad base64, JSON non-object, or no
        ``aud``) is treated as not-authenticated rather than raising.
        """
        parts = (token or "").split(".")
        if len(parts) < 2:
            return False
        try:
            payload = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
        except Exception:
            return False
        if not isinstance(claims, dict):
            return False
        aud = claims.get("aud")
        if not aud or aud in self.AUTH_TOKEN_REJECT_AUD:
            return False
        if claims.get("x-user-context-type") in self.AUTH_TOKEN_REJECT_CONTEXT:
            return False
        return True

    def live_cookies(self) -> list:
        """Return current cookies from the running browser via CDP.

        Opens a headless browser against the persistent profile when the
        daemon is not already running. The persistent Chromium profile is
        the single source of truth.
        """
        svc = self._get_service()
        if not svc._opened:
            try:
                svc.browser_open(
                    self.AUTH_CHECK_URL,
                    headed=not self._headless_enabled(),
                    persistent_profile_dir=self._get_persistent_profile_dir(),
                    user_agent=self._browser_user_agent(),
                    window_size=self._browser_window_size(),
                )
            except BrowserHarnessError as e:
                raise BrowserAutomationError(str(e)) from e
        return svc.cookie_list()

    # ---------------- Interstitial resolution ----------------

    def _interstitial_page_state(self, page) -> Tuple[str, str, str]:
        """Return ``(url, title, body)`` for interstitial classification.

        Body text is only fetched when a declared rule actually needs it —
        reading ``innerText`` on every navigation is not free. A probe can
        fail transiently mid-navigation; that is not proof of a wall, so it
        degrades to empty text and lets the URL carry the classification.
        """
        try:
            url = page.url or ""
        except Exception:
            url = ""
        try:
            title = page.evaluate("document.title") or ""
        except Exception:
            title = ""

        if not any(rule.body_markers for rule in self.INTERSTITIALS):
            return url, title, ""
        try:
            body = page.evaluate(
                "document.body ? document.body.innerText.slice(0, 2000) : ''"
            ) or ""
        except Exception:
            body = ""
        return url, title, body

    def _classify_page_interstitial(self, page) -> Optional[Interstitial]:
        """Classify the live page against this tool's declared walls."""
        url, title, body = self._interstitial_page_state(page)
        return classify_interstitial(
            self.INTERSTITIALS, url=url, title=title, body=body
        )

    def _interstitial_delay_ms(self, attempt: int) -> int:
        """Jittered exponential backoff, in ms, before reload ``attempt``."""
        base = min(
            self.INTERSTITIAL_BASE_DELAY_MS * (2 ** (attempt - 1)),
            self.INTERSTITIAL_MAX_DELAY_MS,
        )
        return int(base * (1 + random.random() * self.INTERSTITIAL_JITTER_RATIO))

    def _raise_for_interstitial_abort(self, rule: Interstitial, page) -> None:
        """Hard stop on a wall that must never be automated around."""
        try:
            url = page.url or ""
        except Exception:
            url = ""
        raise BrowserAutomationError(
            f"Reached a {rule.label} wall at {self._safe_url_for_log(url)}. "
            "This cannot be resolved automatically. Re-run auth login for the "
            "browser session from an interactive shell and complete the "
            "verification in the CLI-owned browser profile."
        )

    def _settle_interstitial(self, page) -> Optional[Interstitial]:
        """Resolve the page to real content, or report the blocking wall.

        Returns ``None`` once the page is real content, otherwise the rule a
        reload has to clear. A ``settle`` wall is polled out in place because
        it redirects itself; an ``abort`` wall raises immediately.
        """
        rule = self._classify_page_interstitial(page)
        if rule is None:
            return None
        if rule.strategy == INTERSTITIAL_ABORT:
            self._raise_for_interstitial_abort(rule, page)
        if rule.strategy != INTERSTITIAL_SETTLE:
            return rule

        waited = 0
        while waited < self.INTERSTITIAL_SETTLE_TIMEOUT_MS:
            print_warning(
                f"{rule.label} interstitial detected -- waiting for it to "
                f"clear ({waited // 1000}s/"
                f"{self.INTERSTITIAL_SETTLE_TIMEOUT_MS // 1000}s)"
            )
            page.wait_for_timeout(self.INTERSTITIAL_POLL_INTERVAL_MS)
            waited += self.INTERSTITIAL_POLL_INTERVAL_MS
            rule = self._classify_page_interstitial(page)
            if rule is None:
                return None
            if rule.strategy == INTERSTITIAL_ABORT:
                self._raise_for_interstitial_abort(rule, page)
            if rule.strategy != INTERSTITIAL_SETTLE:
                return rule
        return rule

    def _resolve_interstitials(self, page, url: str = None):
        """Return ``page`` once it holds real content, or raise naming the wall."""
        if not self.INTERSTITIALS:
            return page

        target = url or page.url
        for attempt in range(1, self.INTERSTITIAL_MAX_ATTEMPTS + 1):
            rule = self._settle_interstitial(page)
            if rule is None:
                return page

            if attempt >= self.INTERSTITIAL_MAX_ATTEMPTS:
                raise BrowserAutomationError(
                    f"A {rule.label} interstitial was served for {target!r} "
                    f"and did not clear after {self.INTERSTITIAL_MAX_ATTEMPTS} "
                    "navigation attempts. The site is rate-limiting this "
                    "session; wait a few minutes before retrying, or re-run "
                    "auth login for the browser session to refresh it."
                )

            delay_ms = self._interstitial_delay_ms(attempt)
            print_warning(
                f"{rule.label} interstitial detected (attempt {attempt}/"
                f"{self.INTERSTITIAL_MAX_ATTEMPTS}) -- retrying {target} in "
                f"{delay_ms / 1000:.1f}s"
            )
            page.wait_for_timeout(delay_ms)
            page.goto(target)
            self._raise_if_auth_failure_page(page)

        raise AssertionError("unreachable: interstitial loop must return or raise")

    def _main_document_http_status(self, page) -> Optional[int]:
        """The main document's real HTTP status, or None when unreadable."""
        try:
            value = page.evaluate(HTTP_ERROR_STATUS_JS)
        except Exception:
            logger.debug("_main_document_http_status: evaluate failed", exc_info=True)
            return None
        return value if isinstance(value, int) else None

    def _raise_for_http_error_status(self, page) -> None:
        """Refuse to hand back a 429/5xx error document as if it were content.

        A site answering HTTP 429 (rate limit) or >=500 (outage) renders a
        normal-looking error page at the requested URL; a scraper that only
        reads the DOM records that error page as valid (often empty) data.
        Microworkers.com hit this live on 2026-09-04: /jobs.php answered 429,
        the task-list extractor found zero rows, and discovery logged an
        ``ok`` envelope with 0 tasks while ~1600 were actually available.
        Opt out per tool with ``HTTP_ERROR_STATUS_RAISE = False``.
        """
        if not self.HTTP_ERROR_STATUS_RAISE:
            return
        status = self._main_document_http_status(page)
        if status is None or (status < 500 and status != 429):
            return
        try:
            url = page.evaluate("() => location.href")
        except Exception:
            url = ""
        raise BrowserAutomationError(
            f"The site answered HTTP {status} for the main document at "
            f"{self._safe_url_for_log(url)} -- likely rate limiting or an "
            "outage. Refusing to treat the error page as content; retry later."
        )

    def get_page(self, url: str = None) -> BrowserHarnessService:
        """Get a page backed by the persistent profile, past any interstitial.

        Navigates via :meth:`_navigate_page`, then resolves any wall declared
        in ``INTERSTITIALS`` so callers only ever receive real content, then
        raises if that real content is actually an HTTP 429/5xx error document
        (:meth:`_raise_for_http_error_status`).
        """
        page = self._navigate_page(url)
        page = self._resolve_interstitials(page, url)
        self._raise_for_http_error_status(page)
        return page

    def _navigate_page(self, url: str = None) -> BrowserHarnessService:
        """Get a :class:`BrowserHarnessService` backed by the persistent profile.

        On first call, opens a headless browser bound to the persistent
        user-data-dir and navigates to ``url`` (or ``AUTH_CHECK_URL``).
        Subsequent calls reuse the same daemon; if ``url`` is given, it
        navigates there first.
        """
        logger.debug("get_page: url=%s has_existing_page=%s", url, self._page is not None)

        if self._page is not None:
            if url:
                logger.debug("get_page: reusing existing page, navigating to %s", url)
                self._page.goto(url)
                self._raise_if_auth_failure_page(self._page)
            return self._page

        # Check for a prewarmed browser from the credential gate
        prewarmed = getattr(self.config, '_prewarmed_browser', None)
        if prewarmed is not None and prewarmed._page is not None:
            self.config._prewarmed_browser = None  # consume it
            self._service = prewarmed._service
            self._page = prewarmed._page
            self._auth_verified_at = prewarmed._auth_verified_at
            prewarmed._service = None
            prewarmed._page = None
            logger.debug("get_page: adopted prewarmed browser (skipping launch)")
            if url:
                self._page.goto(url)
                self._raise_if_auth_failure_page(self._page)
            return self._page

        svc = self._get_service()
        target_url = url or self.AUTH_CHECK_URL
        try:
            svc.browser_open(
                target_url,
                headed=not self._headless_enabled(),
                persistent_profile_dir=self._get_persistent_profile_dir(),
                user_agent=self._browser_user_agent(),
                window_size=self._browser_window_size(),
            )
        except BrowserHarnessError as e:
            raise BrowserAutomationError(str(e)) from e

        self._page = svc
        self._raise_if_auth_failure_page(self._page)
        logger.debug("get_page: ready")
        return self._page

    def clear_session(self) -> None:
        """Wipe the persistent profile and invalidate the cached service.

        Propagates failures from the underlying ``data_delete()`` — no
        silent recovery (one execution path, fail loudly).
        """
        self._auth_verified_at = 0
        svc = self._get_service()
        if getattr(svc, "_user_data_dir", None) is None:
            svc._user_data_dir = self._get_persistent_profile_dir()
        svc.data_delete()
        self._service = None
        self._page = None

    def login(self, force: bool = False) -> Dict[str, Any]:
        """Interactive login returning the dict expected by ``create_auth_app``."""
        logger.debug("login: force=%s", force)
        try:
            self.authenticate(force=force)
            return {"success": True, "message": "Session saved. Browser closed."}
        except Exception as e:
            logger.debug("login: authenticate failed: %s", e)
            return {"success": False, "message": str(e)}

    def close(self) -> None:
        logger.debug("close: closing browser session")
        try:
            self._get_service().browser_close()
        except BrowserHarnessError:
            pass
        self._page = None
        self._service = None

    def test_session(self) -> Dict[str, Any]:
        """Headless verification — navigate to AUTH_CHECK_URL and check auth."""
        logger.debug("test_session: AUTH_CHECK_URL=%s", self.AUTH_CHECK_URL)
        has_saved = (
            self.config.has_saved_session()
            if hasattr(self.config, "has_saved_session")
            else False
        )
        if not has_saved:
            return {"authenticated": False, "error": "No saved session"}

        try:
            page = self.get_page(self.AUTH_CHECK_URL)
            page.wait_for_timeout(2000)
            current_url = page.url
            authenticated = self._check_auth(page)
            result = {"authenticated": authenticated, "url": current_url}
            return result
        except Exception as e:
            return {"authenticated": False, "error": str(e)}
        finally:
            self.close()

    # ==================== Overridable Hooks ====================

    def _is_login_page(self, url_or_page) -> bool:
        url = url_or_page if isinstance(url_or_page, str) else url_or_page.url
        if self.AUTH_URL_PATTERN:
            result = bool(re.search(self.AUTH_URL_PATTERN, url))
            logger.debug("_is_login_page: url=%s pattern=%r match=%s", url, self.AUTH_URL_PATTERN, result)
            return result
        return False

    def _is_auth_failure_page(self, url_or_page) -> bool:
        url = url_or_page if isinstance(url_or_page, str) else url_or_page.url
        if self.AUTH_FAILURE_URL_PATTERN:
            result = bool(re.search(self.AUTH_FAILURE_URL_PATTERN, url))
            logger.debug(
                "_is_auth_failure_page: url=%s pattern=%r match=%s",
                url,
                self.AUTH_FAILURE_URL_PATTERN,
                result,
            )
            return result
        return False

    def _is_auth_failure_content(self, url_or_page) -> bool:
        """Return True when AUTH_FAILURE_PAGE_JS reports a failed page fetch.

        A page that cannot be inspected (no ``evaluate``, or a script error) is
        not treated as a failure: the URL-based checks stay the ground truth.
        """
        if not self.AUTH_FAILURE_PAGE_JS:
            return False
        evaluate = getattr(url_or_page, "evaluate", None)
        if not callable(evaluate):
            return False
        try:
            failed = bool(evaluate(self.AUTH_FAILURE_PAGE_JS))
        except Exception as e:
            logger.debug("_is_auth_failure_content: page inspection failed: %s", e)
            return False
        logger.debug("_is_auth_failure_content: failed=%s", failed)
        return failed

    def _raise_if_auth_failure_page(self, page) -> None:
        if not self.AUTH_FAILURE_URL_PATTERN:
            return
        if not self._is_auth_failure_page(page):
            return
        safe_url = self._safe_url_for_log(page.url)
        raise BrowserAutomationError(
            "Browser session reached an authentication/security challenge at "
            f"{safe_url}. Re-run auth login for the browser session from an "
            "interactive shell and complete the verification in the CLI-owned "
            "browser profile."
        )

    def _check_auth(self, page) -> bool:
        """Check if page indicates authenticated state."""
        # Explicit service failure walls override cookie presence. Some sites
        # keep normal tracking/session cookies on captcha or challenge pages.
        if self.AUTH_FAILURE_URL_PATTERN and self._is_auth_failure_page(page):
            logger.debug(
                "_check_auth: on auth-failure page (url=%s), returning False",
                page.url,
            )
            return False

        # Content-level failure wall: an error/interstitial served at the
        # authenticated URL keeps every URL pattern happy, so the browser looks
        # healthy while it cannot actually fetch the page.
        if self._is_auth_failure_content(page):
            logger.debug(
                "_check_auth: auth-check page reported a failed fetch (url=%s), returning False",
                page.url,
            )
            return False

        # Token-cookie audience check takes precedence when configured: the only
        # reliable signal for sites that mint a guest token even when logged out.
        if self.AUTH_TOKEN_COOKIE:
            return self._check_token_cookie_auth(page)

        # Cookie-backed browser auth does not need page metadata. Some sites
        # keep the document load active long enough that URL/title inspection
        # can block the CDP session before cookies are read.
        if self.AUTH_COOKIE_PATTERNS:
            cookies = page.cookie_list()
            auth_cookies = self._get_auth_cookies(cookies)
            return len(auth_cookies) > 0

        url = page.url

        # 1. Login/auth page check
        if self._is_login_page(page):
            logger.debug("_check_auth: on login/auth page (url=%s), returning False", url)
            return False

        # 2. Negative login-form check
        if self.AUTH_LOGIN_FORM_SELECTOR:
            try:
                visible = page.locator(self.AUTH_LOGIN_FORM_SELECTOR).first.is_visible(timeout=500)
                logger.debug("_check_auth: login_form_selector visible=%s (authenticated=%s)",
                             visible, not visible)
                return not visible
            except Exception as e:
                logger.debug("_check_auth: login-form check failed: %s", e)
                return False

        # 3. DOM element check
        if self.AUTH_SUCCESS_SELECTOR:
            try:
                visible = page.locator(self.AUTH_SUCCESS_SELECTOR).first.is_visible(timeout=500)
                return visible
            except Exception as e:
                logger.debug("_check_auth: selector check failed: %s", e)
                return False

        # 4. localStorage check
        if self.AUTH_STORAGE_KEY:
            try:
                items = page.localstorage_list()
                return any(i['key'] == self.AUTH_STORAGE_KEY and i['value'] for i in items)
            except Exception as e:
                logger.debug("_check_auth: localStorage check failed: %s", e)
                return False

        # 5. Success URL pattern
        if self.AUTH_SUCCESS_URL:
            return bool(re.search(self.AUTH_SUCCESS_URL, url))

        # 6. Fallback: not on login/failure page
        return not self._is_login_page(page)

    def _check_auth_settled(self, page) -> bool:
        """Check auth, polling while a bot-protection challenge clears.

        Behaves exactly like ``_check_auth`` unless the subclass raises
        ``AUTH_CHALLENGE_ATTEMPTS``. The page owns the delay, so the wait is a
        count of attempts rather than a wall clock.
        """
        attempts = max(1, int(self.AUTH_CHALLENGE_ATTEMPTS))
        for attempt in range(attempts):
            if self._check_auth(page):
                return True
            if attempt == attempts - 1:
                break
            logger.debug(
                "_check_auth_settled: attempt %d/%d not authenticated, waiting %dms",
                attempt + 1, attempts, self.AUTH_CHALLENGE_POLL_MS,
            )
            page.wait_for_timeout(self.AUTH_CHALLENGE_POLL_MS)
        return False

    def _check_available(self, page) -> bool:
        if not self.AUTH_UNAVAILABLE_SELECTOR:
            return True
        try:
            visible = page.locator(self.AUTH_UNAVAILABLE_SELECTOR).first.is_visible(timeout=500)
            return not visible
        except Exception:
            return True

    def _on_authenticated(self, page) -> None:
        """Called after successful authentication with a headless page."""
        pass

    def _get_auth_cookies(self, cookies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not self.AUTH_COOKIE_PATTERNS:
            return cookies
        now = time.time()
        auth_cookies = []
        for cookie in cookies:
            name = cookie.get("name", "")
            expires = cookie.get("expires", -1)
            if 0 < expires < now:
                continue
            for pattern in self.AUTH_COOKIE_PATTERNS:
                if re.search(pattern, name, re.IGNORECASE):
                    auth_cookies.append(cookie)
                    break
        return auth_cookies

    # ==================== Context Manager ====================

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


class WebwrightBrowserAutomation(BrowserAutomation):
    """BrowserAutomation variant backed by Webwright's local browser service.

    Subclasses use the same declarative auth hooks as ``BrowserAutomation``
    (``LOGIN_URL``, ``AUTH_CHECK_URL``, selectors, cookie patterns, and so on)
    while swapping only the underlying browser service.
    """

    WEBWRIGHT_BROWSER_MODE = "local_persistent"
    WEBWRIGHT_LOCAL_CDP_URL = None
    WEBWRIGHT_LOCAL_CDP_EXECUTABLE = None
    WEBWRIGHT_LOCAL_CDP_NEW_PAGE = None
    WEBWRIGHT_LOCAL_CDP_CLOSE_PAGE_ON_EXIT = None
    WEBWRIGHT_LOCAL_CDP_CLOSE_STARTED_BROWSER_ON_EXIT = None

    def _get_service(self):
        if self._service is None:
            from .browser.webwright import WebwrightBrowserService

            self._service = WebwrightBrowserService(
                _safe_daemon_key(self._session_name()),
                browser_mode=self.WEBWRIGHT_BROWSER_MODE,
                local_cdp_url=self.WEBWRIGHT_LOCAL_CDP_URL,
                local_cdp_executable=self.WEBWRIGHT_LOCAL_CDP_EXECUTABLE,
                local_cdp_new_page=self.WEBWRIGHT_LOCAL_CDP_NEW_PAGE,
                local_cdp_close_page_on_exit=self.WEBWRIGHT_LOCAL_CDP_CLOSE_PAGE_ON_EXIT,
                local_cdp_close_started_browser_on_exit=(
                    self.WEBWRIGHT_LOCAL_CDP_CLOSE_STARTED_BROWSER_ON_EXIT
                ),
            )
        return self._service
class PlaywrightBrowserAutomation(BrowserAutomation):
    """BrowserAutomation variant backed by Playwright persistent Chrome."""

    PLAYWRIGHT_EXECUTABLE_PATH = None

    def _get_service(self):
        if self._service is None:
            from .browser.playwright_service import PlaywrightBrowserService

            self._service = PlaywrightBrowserService(
                _safe_daemon_key(self._session_name()),
                executable_path=self.PLAYWRIGHT_EXECUTABLE_PATH,
            )
        return self._service
