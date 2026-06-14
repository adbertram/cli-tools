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

import hashlib
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._debug_logging import get_debug_logger
from .output import print_info, print_success
from .browser import BrowserHarnessService, BrowserHarnessError

logger = get_debug_logger("cli_tools.auth")


class BrowserAutomationError(Exception):
    """Browser automation error."""

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
    AUTH_COOKIE_PATTERNS = []    # Cookie name regexes indicating auth
    AUTH_SUCCESS_URL = ""        # URL pattern indicating successful login
    AUTH_SUCCESS_SELECTOR = ""   # CSS/locator selector visible when authenticated
    AUTH_LOGIN_FORM_SELECTOR = ""  # CSS/locator selector for login-form elements; ABSENT → authenticated
    AUTH_UNAVAILABLE_SELECTOR = ""  # CSS/locator selector — if visible, authenticated but not available
    AUTH_STORAGE_KEY = ""        # localStorage key; True if key exists and has a value
    LOGIN_TIMEOUT = 300          # Seconds to wait for manual login
    SESSION_NAME = ""            # Named session used for the per-tool user-data-dir

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

    def _prompt_enter_eof_safe(self, message: str = "") -> None:
        """Block until the user presses Enter; tolerate non-TTY stdin.

        ``input()`` raises ``EOFError`` when stdin is closed or piped. Fall
        back to ``/dev/tty`` for the controlling terminal; if even that is
        unavailable, exit with status 2 — never silently treat the missing
        confirmation as "login succeeded".
        """
        try:
            input(message)
            return
        except EOFError:
            pass

        try:
            with open("/dev/tty", "r") as tty:
                if message:
                    sys.stderr.write(message)
                    sys.stderr.flush()
                tty.readline()
        except OSError as e:
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
            return AuthResult(authenticated=False, available=False, live_check=True)

    def authenticate(self, force: bool = False):
        """Interactive login via headed persistent browser."""
        logger.debug("authenticate: force=%s session=%s", force, self._session_name())

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

        self._prompt_enter_eof_safe()

        self._service = svc
        self._page = svc

        has_hook = type(self)._on_authenticated is not BrowserAutomation._on_authenticated
        page = svc
        try:
            page.wait_for_timeout(2000)
            if has_hook:
                logger.debug("authenticate: running post-auth hook")
                self._on_authenticated(page)
            if not self._check_auth(page):
                raise BrowserAutomationError("Browser session is not authenticated after login.")
        finally:
            self.close()

        persisted = self.is_authenticated()
        self.close()
        if not persisted:
            raise BrowserAutomationError(
                "Browser session did not persist after reopening. "
                "Log in again and ensure the service keeps the session across browser restarts."
            )

        self._auth_verified_at = time.time()
        logger.debug("authenticate: complete")
        print_success("Authentication complete.")

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

    def get_page(self, url: str = None) -> BrowserHarnessService:
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
            self.close()
            return result
        except Exception as e:
            return {"authenticated": False, "error": str(e)}

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

    def _check_auth(self, page) -> bool:
        """Check if page indicates authenticated state."""
        # Cookie-backed browser auth does not need page metadata. Some sites
        # keep the document load active long enough that URL/title inspection
        # can block the CDP session before cookies are read.
        if self.AUTH_COOKIE_PATTERNS:
            try:
                cookies = page.cookie_list()
                auth_cookies = self._get_auth_cookies(cookies)
                return len(auth_cookies) > 0
            except Exception as e:
                logger.debug("_check_auth: cookie check failed: %s", e)
                return False

        url = page.url

        # 0. Explicit auth-failure page check
        if self._is_auth_failure_page(page):
            logger.debug("_check_auth: on auth-failure page (url=%s), returning False", url)
            return False

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
