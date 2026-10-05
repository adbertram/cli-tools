"""Playwright-backed browser service for CLI tools.

This service implements the same small synchronous surface as
``BrowserHarnessService`` while launching a persistent Chrome profile through
Playwright. It is intentionally optional: tools that need it add ``playwright``
to their own dependencies.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from . import BrowserHarnessError
from ._elements import _ServiceElement, _ServiceLocator
from .processes import (
    ProfileInUseError,
    ProcessCommand,
    ProcessTableUnavailableError,
    acquire_profile_lifecycle_lock,
    command_user_data_dir,
    format_profile_in_use_message,
    list_process_commands,
    pid_is_running,
    profile_process_owner,
    profile_process_pids,
    remove_stale_profile_artifacts,
    release_profile_lifecycle_lock,
    resolve_user_data_dir,
)


# Playwright default Chromium switches that swap the OS cookie-encryption key
# for a mock one. Stripped so Playwright and the CDP backend share one key.
_MOCK_KEYCHAIN_DEFAULT_ARGS = ("--use-mock-keychain", "--password-store=basic")


class PlaywrightServiceError(BrowserHarnessError):
    """Error from PlaywrightBrowserService operations."""


def _chrome_binary() -> str:
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    raise PlaywrightServiceError(
        "Could not locate a Chrome/Chromium binary. Install Google Chrome "
        "or set CLI_TOOLS_CHROME_BINARY."
    )


def _parse_window_size(window_size: str | None) -> tuple[int, int] | None:
    if not window_size:
        return None
    cleaned = window_size.lower().replace(",", "x")
    parts = cleaned.split("x")
    if len(parts) != 2:
        raise PlaywrightServiceError(
            f"window_size must be formatted as WIDTHxHEIGHT, got {window_size!r}."
        )
    try:
        width = int(parts[0].strip())
        height = int(parts[1].strip())
    except ValueError as exc:
        raise PlaywrightServiceError(
            f"window_size must contain integer width and height, got {window_size!r}."
        ) from exc
    if width <= 0 or height <= 0:
        raise PlaywrightServiceError(
            f"window_size values must be positive, got {window_size!r}."
        )
    return width, height


class PlaywrightBrowserService:
    """Synchronous browser service backed by Playwright persistent context."""

    def __init__(
        self,
        session: str,
        *,
        timeout: int = 60,
        executable_path: Optional[str] = None,
    ):
        self.session = session
        self.default_timeout = timeout
        self.executable_path = executable_path
        self._playwright = None
        self._context = None
        self._page = None
        self._opened = False
        self._user_data_dir: Optional[Path] = None
        self._lifecycle_lock_file = None
        self._lifecycle_lock_profile: Optional[Path] = None

    @staticmethod
    def _safe_url_for_log(url: str) -> str:
        if not url:
            return ""
        try:
            parts = urlsplit(url)
            query = "&".join(
                f"{name}=<redacted>"
                for name, _value in parse_qsl(parts.query, keep_blank_values=True)
            )
            fragment = "<redacted>" if parts.fragment else ""
            return urlunsplit((parts.scheme, parts.netloc, parts.path, query, fragment))
        except Exception:
            return "<unparseable url>"

    def _require_open(self) -> None:
        if not self._opened or self._context is None or self._page is None:
            raise PlaywrightServiceError(
                f"No browser open for session '{self.session}'. Call browser_open() first."
            )

    def _page_info(self) -> Dict[str, Any]:
        if not self._opened or self._page is None:
            return {"url": "", "title": "", "console_errors": 0, "console_warnings": 0}
        try:
            title = self._page.title()
        except Exception:
            title = ""
        return {
            "url": self._page.url or "",
            "title": title,
            "console_errors": 0,
            "console_warnings": 0,
        }

    def _list_process_table(self) -> List[ProcessCommand]:
        """Return process-table rows for the local process table."""
        try:
            return list_process_commands()
        except ProcessTableUnavailableError:
            raise
        except RuntimeError as exc:
            raise PlaywrightServiceError(f"Failed to inspect process table: {exc}") from exc

    def _list_process_commands(self) -> List[tuple[int, str, str]]:
        """Return legacy `(pid, stat, command)` process rows."""
        return [(proc.pid, proc.stat, proc.command) for proc in self._list_process_table()]

    def _session_process_pids(self) -> List[int]:
        """Return PIDs for Chrome helpers using this service's profile."""
        if self._user_data_dir is None:
            return []
        return profile_process_pids(self._user_data_dir, processes=self._list_process_table())

    def _resolved_user_data_dir(self) -> Optional[Path]:
        if self._user_data_dir is None:
            return None
        return resolve_user_data_dir(self._user_data_dir)

    def _profile_owner(self):
        user_data_dir = self._resolved_user_data_dir()
        if user_data_dir is None:
            return None
        return profile_process_owner(
            user_data_dir,
            processes=self._list_process_table(),
        )

    def _profile_owner_error(
        self,
        owner,
        *,
        parent_command_unavailable: bool = False,
    ) -> PlaywrightServiceError:
        return PlaywrightServiceError(
            format_profile_in_use_message(
                self._resolved_user_data_dir(),
                owner,
                parent_command_unavailable=parent_command_unavailable,
            )
        )

    def _acquire_profile_lifecycle_lock(self) -> None:
        """Serialize browser ownership for this exact resolved profile."""
        user_data_dir = self._resolved_user_data_dir()
        if user_data_dir is None:
            raise PlaywrightServiceError("Cannot lock a browser profile before it is resolved.")
        if self._lifecycle_lock_file is not None:
            if self._lifecycle_lock_profile == user_data_dir:
                return
            raise PlaywrightServiceError("Cannot switch Chrome profiles while the current profile is open.")
        self._lifecycle_lock_file = acquire_profile_lifecycle_lock(user_data_dir)
        self._lifecycle_lock_profile = user_data_dir

    def _release_profile_lifecycle_lock(self) -> None:
        """Release this service's persistent-profile ownership lock."""
        if self._lifecycle_lock_file is None:
            return
        try:
            release_profile_lifecycle_lock(self._lifecycle_lock_file)
        finally:
            self._lifecycle_lock_file = None
            self._lifecycle_lock_profile = None

    @staticmethod
    def _command_user_data_dir(command: str) -> Optional[str]:
        return command_user_data_dir(command)

    def _raise_if_profile_in_use(self) -> None:
        try:
            owner = self._profile_owner()
        except ProcessTableUnavailableError as exc:
            raise PlaywrightServiceError(
                f"Cannot verify whether Chrome profile {self._resolved_user_data_dir()} is in use "
                "because the process table cannot be inspected."
            ) from exc
        if owner is not None:
            raise self._profile_owner_error(owner)

    def _cleanup_stale_profile_locks(self) -> None:
        """Remove singleton artifacts only after proving no profile owner exists."""
        user_data_dir = self._resolved_user_data_dir()
        if user_data_dir is None:
            return
        try:
            remove_stale_profile_artifacts(
                user_data_dir,
                owner_lookup=self._profile_owner,
                process_is_running=pid_is_running,
            )
        except ProfileInUseError as exc:
            raise self._profile_owner_error(
                exc.owner,
                parent_command_unavailable=exc.parent_command_unavailable,
            ) from exc
        except ProcessTableUnavailableError as exc:
            raise PlaywrightServiceError(
                f"Cannot remove stale Chrome profile artifacts for {user_data_dir} because "
                "the process table cannot be inspected."
            ) from exc
        except OSError as exc:
            raise PlaywrightServiceError(
                f"Failed to remove stale browser lock file for {user_data_dir}: {exc}"
            ) from exc

    def browser_open(
        self,
        url: Optional[str] = None,
        headed: bool = False,
        persistent_profile_dir: Optional[Path] = None,
        user_agent: Optional[str] = None,
        window_size: Optional[str] = None,
    ) -> Dict[str, Any]:
        if persistent_profile_dir is None:
            raise PlaywrightServiceError(
                "browser_open: persistent_profile_dir is required. "
                "Pass config.get_persistent_profile_dir() from the caller."
            )
        if headed and os.getenv("CLI_TOOL_TEST_NO_HEADED_BROWSER") == "1":
            headed = False
        if self._opened:
            self.browser_close()

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise PlaywrightServiceError(
                "Playwright is not installed in this CLI environment."
            ) from exc

        profile_dir = resolve_user_data_dir(persistent_profile_dir)
        profile_dir.mkdir(parents=True, exist_ok=True)
        self._user_data_dir = profile_dir
        self._acquire_profile_lifecycle_lock()

        try:
            self._cleanup_stale_profile_locks()

            launch_args = [
                "--restore-last-session",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=AutomationControlled,Translate",
            ]
            if user_agent:
                launch_args.append(f"--user-agent={user_agent}")

            width_height = _parse_window_size(window_size)
            kwargs: dict[str, Any] = {
                "headless": not headed,
                "executable_path": self.executable_path or os.getenv("CLI_TOOLS_CHROME_BINARY") or _chrome_binary(),
                "args": launch_args,
                # Playwright's defaults make Chrome encrypt cookies with a mock
                # key. The CDP backend (plain Chrome) uses the real OS keychain
                # key on the same shared user-data-dir, so each backend purged
                # the other's cookies as undecryptable. Use the real keychain.
                "ignore_default_args": list(_MOCK_KEYCHAIN_DEFAULT_ARGS),
                "timeout": self.default_timeout * 1000,
            }
            if width_height is not None:
                kwargs["viewport"] = {"width": width_height[0], "height": width_height[1]}

            self._playwright = sync_playwright().start()
            self._context = self._playwright.chromium.launch_persistent_context(
                str(profile_dir),
                **kwargs,
            )
            self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
            self._page.set_default_timeout(self.default_timeout * 1000)
            self._page.set_default_navigation_timeout(self.default_timeout * 1000)
            self._opened = True
            if url:
                self.page_goto(url)
            return self._page_info()
        except Exception as exc:
            self._opened = False
            try:
                if self._context is not None:
                    self._context.close()
            finally:
                self._context = None
                self._page = None
                if self._playwright is not None:
                    self._playwright.stop()
                    self._playwright = None
                self._release_profile_lifecycle_lock()
            raise PlaywrightServiceError(f"Failed to open Playwright browser: {exc}") from exc

    @staticmethod
    def _reset_tabs_for_restore(context, page) -> None:
        """Leave exactly one blank tab so the next launch restores nothing.

        ``--restore-last-session`` keeps session-only cookies across launches
        but also reopens every tab from the last run; on the shared profile
        that reloaded other CLIs' login pages on every launch
        (agent-issues#530). One ``about:blank`` tab keeps the restore.
        """
        for other in list(context.pages):
            if other is not page:
                other.close()
        page.goto("about:blank")

    def _close_browser_locked(self) -> None:
        """Close Playwright-owned state while the profile lock remains held."""
        context = self._context
        page = self._page
        playwright = self._playwright
        self._context = None
        self._page = None
        self._playwright = None
        self._opened = False
        try:
            if context is not None:
                try:
                    if page is not None:
                        self._reset_tabs_for_restore(context, page)
                finally:
                    context.close()
        finally:
            if playwright is not None:
                playwright.stop()

    def browser_close(self) -> Dict[str, Any]:
        try:
            self._close_browser_locked()
        finally:
            self._release_profile_lifecycle_lock()
        return {"success": True, "message": "Browser closed"}

    def page_goto(self, url: str, wait_until: str | None = "domcontentloaded") -> Dict[str, Any]:
        self._require_open()
        self._page.goto(url, wait_until=wait_until or "domcontentloaded")
        return self._page_info()

    def goto(self, url: str, wait_until: str = None) -> None:
        self.page_goto(url, wait_until=wait_until or "domcontentloaded")

    def evaluate(self, js: str, arg: Any = None) -> Any:
        self._require_open()
        if arg is None:
            return self._page.evaluate(js)
        return self._page.evaluate(js, arg)

    def iframe_target(self, url_substr: str) -> Optional[str]:
        self._require_open()
        if not url_substr:
            raise PlaywrightServiceError("iframe_target: url_substr must be non-empty")
        for frame in self._page.frames:
            if url_substr in (frame.url or ""):
                return frame.url
        return None

    def evaluate_in_iframe(self, url_substr: str, js: str, arg: Any = None) -> Any:
        self._require_open()
        frame = next(
            (candidate for candidate in self._page.frames if url_substr in (candidate.url or "")),
            None,
        )
        if frame is None:
            return None
        if arg is None:
            return frame.evaluate(js)
        return frame.evaluate(js, arg)

    def page_eval(self, js: str, arg: Any = None) -> Dict[str, Any]:
        return {"result": self.evaluate(js, arg)}

    def keyboard_press(self, key: str) -> Dict[str, Any]:
        self._require_open()
        self._page.keyboard.press(key)
        return self._page_info()

    def type_text(self, text: str) -> Dict[str, Any]:
        self._require_open()
        self._page.keyboard.type(text)
        return self._page_info()

    def cookie_list(self) -> List[Dict[str, Any]]:
        self._require_open()
        cookies = self._context.cookies()
        if not isinstance(cookies, list):
            raise PlaywrightServiceError(
                f"Playwright context.cookies() returned unexpected payload: {cookies!r}"
            )
        return cookies

    def localstorage_list(self) -> List[Dict[str, str]]:
        result = self.evaluate(
            "() => Object.entries(localStorage).map(([key, value]) => ({key, value}))"
        )
        return result or []

    def data_delete(self) -> Dict[str, Any]:
        user_data_dir = self._resolved_user_data_dir()
        if user_data_dir is None:
            return {"success": True, "message": "Session data deleted"}
        try:
            self._acquire_profile_lifecycle_lock()
            self._close_browser_locked()
            self._raise_if_profile_in_use()
            if user_data_dir.exists():
                shutil.rmtree(user_data_dir)
            return {"success": True, "message": "Session data deleted"}
        finally:
            self._release_profile_lifecycle_lock()

    def locator(self, selector: str) -> _ServiceLocator:
        return _ServiceLocator(self, selector)

    def get_by_role(self, role: str, *, name=None, exact: bool = False) -> _ServiceLocator:
        return _ServiceLocator.from_role(self, role, name, exact=exact)

    def get_by_placeholder(self, text: str) -> _ServiceLocator:
        return _ServiceLocator(self, f'[placeholder="{text}"]')

    def wait_for_timeout(self, ms: int) -> None:
        time.sleep(ms / 1000)

    def wait_for_selector(
        self,
        selector: str,
        *,
        state: str = "visible",
        timeout: int = 30000,
    ) -> Optional[_ServiceElement]:
        valid_states = ("attached", "visible", "hidden", "detached")
        if state not in valid_states:
            raise PlaywrightServiceError(
                f"wait_for_selector: state must be one of {valid_states}, got {state!r}"
            )
        self._require_open()
        self._page.wait_for_selector(selector, state=state, timeout=timeout)
        if state in ("hidden", "detached"):
            return None
        return _ServiceElement(self, css=selector)

    def query_selector(self, selector: str) -> Optional[_ServiceElement]:
        self._require_open()
        present = self.evaluate(
            f"() => !!document.querySelector({json.dumps(selector)})"
        )
        if not present:
            return None
        return _ServiceElement(self, css=selector)

    def fill(self, selector: str, text: str) -> None:
        """Fill the first element matching ``selector`` with ``text``.

        Playwright-compatible page-level shim: callers written against the
        Playwright ``page.fill(selector, text)`` API expect this method on the
        page object. Resolves ``selector`` against the live DOM and reuses the
        same fill behavior as the element/locator wrappers, mirroring
        :meth:`BrowserHarnessService.fill` so both browser backends expose the
        same page-level surface.
        """
        self._require_open()
        _ServiceElement(self, css=selector).fill(text)

    def aria_snapshot(self, selector: str = "body", *, timeout: int = 5000) -> str:
        self._require_open()
        return self._page.locator(selector).aria_snapshot(timeout=timeout)

    @property
    def url(self) -> str:
        try:
            return self._page_info().get("url", "")
        except Exception:
            return ""
