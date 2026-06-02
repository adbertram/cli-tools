"""Webwright-backed browser service for CLI tools.

This module adapts Webwright's deterministic local browser environment to the
same synchronous, Playwright-shaped surface used by ``BrowserAutomation``. It
does not run Webwright's model loop; CLI commands keep deterministic control of
navigation, selectors, cookies, and storage.
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


class WebwrightServiceError(BrowserHarnessError):
    """Error from WebwrightBrowserService operations."""


def _load_local_browser_environment():
    try:
        from webwright.environments.local_browser import LocalBrowserEnvironment
    except ImportError as exc:
        raise WebwrightServiceError(
            "Webwright is not installed in this CLI environment. Install it for "
            "the tool, for example: uv add "
            "'webwright @ git+https://github.com/microsoft/Webwright.git'."
        ) from exc
    return LocalBrowserEnvironment


def _parse_window_size(window_size: str | None) -> tuple[int, int] | None:
    if not window_size:
        return None
    cleaned = window_size.lower().replace(",", "x")
    parts = cleaned.split("x")
    if len(parts) != 2:
        raise WebwrightServiceError(
            f"window_size must be formatted as WIDTHxHEIGHT, got {window_size!r}."
        )
    try:
        width = int(parts[0].strip())
        height = int(parts[1].strip())
    except ValueError as exc:
        raise WebwrightServiceError(
            f"window_size must contain integer width and height, got {window_size!r}."
        ) from exc
    if width <= 0 or height <= 0:
        raise WebwrightServiceError(
            f"window_size values must be positive, got {window_size!r}."
        )
    return width, height


class WebwrightBrowserService:
    """Synchronous browser service backed by Webwright LocalBrowserEnvironment."""

    def __init__(
        self,
        session: str,
        *,
        browser_mode: str = "local_persistent",
        timeout: int = 60,
        local_cdp_url: Optional[str] = None,
        local_cdp_executable: Optional[str] = None,
        local_cdp_new_page: Optional[bool] = None,
        local_cdp_close_page_on_exit: Optional[bool] = None,
        local_cdp_close_started_browser_on_exit: Optional[bool] = None,
    ):
        self.session = session
        self.browser_mode = browser_mode
        self.default_timeout = timeout
        self.local_cdp_url = local_cdp_url
        self.local_cdp_executable = local_cdp_executable
        self.local_cdp_new_page = local_cdp_new_page
        self.local_cdp_close_page_on_exit = local_cdp_close_page_on_exit
        self.local_cdp_close_started_browser_on_exit = local_cdp_close_started_browser_on_exit
        self._environment = None
        self._opened = False
        self._user_data_dir: Optional[Path] = None

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
        if not self._opened or self._environment is None:
            raise WebwrightServiceError(
                f"No browser open for session '{self.session}'. Call browser_open() first."
            )

    def _page(self):
        self._require_open()
        page = getattr(self._environment, "_page", None)
        if page is None:
            raise WebwrightServiceError(
                f"Webwright did not expose a page for session '{self.session}'."
            )
        return page

    def _context(self):
        self._require_open()
        context = getattr(self._environment, "_context", None)
        if context is None:
            raise WebwrightServiceError(
                f"Webwright did not expose a browser context for session '{self.session}'."
            )
        return context

    def _run(self, coro):
        self._require_open()
        return self._environment._run(coro)

    def _run_on_page(self, factory):
        page = self._page()
        return self._run(factory(page))

    def _page_info(self) -> Dict[str, Any]:
        if not self._opened or self._environment is None:
            return {"url": "", "title": "", "console_errors": 0, "console_warnings": 0}
        page = self._page()
        title = ""
        try:
            title = self._run(page.title())
        except Exception:
            title = ""
        return {
            "url": getattr(page, "url", "") or "",
            "title": title,
            "console_errors": 0,
            "console_warnings": 0,
        }

    def browser_open(
        self,
        url: Optional[str] = None,
        headed: bool = False,
        persistent_profile_dir: Optional[Path] = None,
        user_agent: Optional[str] = None,
        window_size: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Open a Webwright local browser against a persistent profile."""
        if persistent_profile_dir is None:
            raise WebwrightServiceError(
                "browser_open: persistent_profile_dir is required. "
                "Pass config.get_persistent_profile_dir() from the caller."
            )
        if headed and os.getenv("CLI_TOOL_TEST_NO_HEADED_BROWSER") == "1":
            headed = False
        if self._opened:
            self.browser_close()

        profile_dir = Path(persistent_profile_dir)
        profile_dir.mkdir(parents=True, exist_ok=True)
        self._user_data_dir = profile_dir

        width_height = _parse_window_size(window_size)
        launch_args: list[str] = []
        if user_agent:
            launch_args.append(f"--user-agent={user_agent}")

        output_dir = profile_dir.parent / "webwright" / self.session
        kwargs: dict[str, Any] = {
            "browser_mode": self.browser_mode,
            "headless": not headed,
            "output_dir": output_dir,
            "user_data_dir": profile_dir,
            "browser_timeout_ms": self.default_timeout * 1000,
            "browser_navigation_timeout_ms": self.default_timeout * 1000,
            "launch_args": launch_args,
        }
        if self.local_cdp_url is not None:
            kwargs["local_cdp_url"] = self.local_cdp_url
        if self.local_cdp_executable is not None:
            kwargs["local_cdp_executable"] = self.local_cdp_executable
        if self.local_cdp_new_page is not None:
            kwargs["local_cdp_new_page"] = self.local_cdp_new_page
        if self.local_cdp_close_page_on_exit is not None:
            kwargs["local_cdp_close_page_on_exit"] = self.local_cdp_close_page_on_exit
        if self.local_cdp_close_started_browser_on_exit is not None:
            kwargs["local_cdp_close_started_browser_on_exit"] = (
                self.local_cdp_close_started_browser_on_exit
            )
        if width_height is not None:
            kwargs["browser_width"], kwargs["browser_height"] = width_height

        env_cls = _load_local_browser_environment()
        environment = env_cls(**kwargs)
        self._environment = environment
        try:
            environment.prepare(
                task=f"Open {url}" if url else "Open browser",
                task_id=self.session,
                start_url=url,
            )
            self._opened = True
            return self._page_info()
        except Exception as exc:
            self._environment = None
            self._opened = False
            raise WebwrightServiceError(f"Failed to open Webwright browser: {exc}") from exc

    def browser_close(self) -> Dict[str, Any]:
        environment = self._environment
        self._environment = None
        self._opened = False
        if environment is not None:
            try:
                environment.close()
            except Exception as exc:
                raise WebwrightServiceError(
                    f"Failed to close Webwright browser: {exc}"
                ) from exc
        return {"success": True, "message": "Browser closed"}

    def page_goto(self, url: str, wait_until: str | None = "domcontentloaded") -> Dict[str, Any]:
        self._run_on_page(lambda page: page.goto(url, wait_until=wait_until))
        return self._page_info()

    def goto(self, url: str, wait_until: str = None) -> None:
        self.page_goto(url, wait_until=wait_until or "domcontentloaded")

    def evaluate(self, js: str, arg: Any = None) -> Any:
        if arg is None:
            return self._run_on_page(lambda page: page.evaluate(js))
        return self._run_on_page(lambda page: page.evaluate(js, arg))

    def iframe_target(self, url_substr: str) -> Optional[str]:
        """Return the URL of the first iframe containing ``url_substr``."""
        if not url_substr:
            raise WebwrightServiceError("iframe_target: url_substr must be non-empty")
        page = self._page()
        for frame in page.frames:
            if url_substr in (frame.url or ""):
                return frame.url
        return None

    def evaluate_in_iframe(self, url_substr: str, js: str, arg: Any = None) -> Any:
        """Run JS inside the first iframe whose URL contains ``url_substr``."""
        page = self._page()
        frame = next((candidate for candidate in page.frames if url_substr in (candidate.url or "")), None)
        if frame is None:
            return None
        if arg is None:
            return self._run(frame.evaluate(js))
        return self._run(frame.evaluate(js, arg))

    def page_eval(self, js: str, arg: Any = None) -> Dict[str, Any]:
        return {"result": self.evaluate(js, arg)}

    def keyboard_press(self, key: str) -> Dict[str, Any]:
        self._run_on_page(lambda page: page.keyboard.press(key))
        return self._page_info()

    def type_text(self, text: str) -> Dict[str, Any]:
        self._run_on_page(lambda page: page.keyboard.type(text))
        return self._page_info()

    def cookie_list(self) -> List[Dict[str, Any]]:
        context = self._context()
        cookies = self._run(context.cookies())
        if not isinstance(cookies, list):
            raise WebwrightServiceError(
                f"Webwright context.cookies() returned unexpected payload: {cookies!r}"
            )
        return cookies

    def localstorage_list(self) -> List[Dict[str, str]]:
        result = self.evaluate(
            "() => Object.entries(localStorage).map(([key, value]) => ({key, value}))"
        )
        return result or []

    def data_delete(self) -> Dict[str, Any]:
        self.browser_close()
        if self._user_data_dir is not None and self._user_data_dir.exists():
            shutil.rmtree(self._user_data_dir)
        return {"success": True, "message": "Session data deleted"}

    def locator(self, selector: str) -> _ServiceLocator:
        return _ServiceLocator(self, selector)

    def get_by_role(self, role: str, *, name=None) -> _ServiceLocator:
        return _ServiceLocator.from_role(self, role, name)

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
            raise WebwrightServiceError(
                f"wait_for_selector: state must be one of {valid_states}, got {state!r}"
            )
        self._run_on_page(
            lambda page: page.wait_for_selector(selector, state=state, timeout=timeout)
        )
        if state in ("hidden", "detached"):
            return None
        return _ServiceElement(self, css=selector)

    def query_selector(self, selector: str) -> Optional[_ServiceElement]:
        present = self.evaluate(
            f"() => !!document.querySelector({json.dumps(selector)})"
        )
        if not present:
            return None
        return _ServiceElement(self, css=selector)

    def aria_snapshot(self, selector: str = "body", *, timeout: int = 5000) -> str:
        async def _snapshot(page):
            return await page.locator(selector).aria_snapshot(timeout=timeout)

        return self._run_on_page(_snapshot)

    @property
    def url(self) -> str:
        try:
            return self._page_info().get("url", "")
        except Exception:
            return ""
