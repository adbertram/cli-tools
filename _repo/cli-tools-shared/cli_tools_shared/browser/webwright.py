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
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlsplit, urlunsplit
from urllib.request import urlopen

from . import BrowserHarnessError
from ._elements import _ServiceElement, _ServiceLocator
from .playwright_service import _chrome_binary
from .processes import (
    ProcessTableUnavailableError,
    ProfileLifecycleLock,
    find_free_loopback_port,
    profile_process_pids,
    remove_stale_profile_lock_files,
    terminate_process,
)


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
        browser_mode: str = "local_cdp",
        timeout: int = 60,
        local_cdp_url: Optional[str] = None,
        local_cdp_executable: Optional[str] = None,
        local_cdp_new_page: Optional[bool] = None,
        local_cdp_close_page_on_exit: Optional[bool] = None,
    ):
        self.session = session
        self.browser_mode = browser_mode
        self.default_timeout = timeout
        self.local_cdp_url = local_cdp_url
        self.local_cdp_executable = local_cdp_executable
        self.local_cdp_new_page = local_cdp_new_page
        self.local_cdp_close_page_on_exit = local_cdp_close_page_on_exit
        self._environment = None
        self._opened = False
        self._user_data_dir: Optional[Path] = None
        self._chrome_process: Optional[subprocess.Popen] = None
        self._cdp_port: Optional[int] = None
        self._profile_lifecycle_lock: Optional[ProfileLifecycleLock] = None

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

    def _profile_process_pids(self) -> list[int]:
        if self._user_data_dir is None:
            return []
        return profile_process_pids(self._user_data_dir)

    def _raise_if_profile_in_use(self) -> None:
        try:
            pids = self._profile_process_pids()
        except ProcessTableUnavailableError as exc:
            raise WebwrightServiceError(
                "Cannot verify ownership of the Webwright Chrome profile because "
                "process-table inspection is unavailable."
            ) from exc
        if pids:
            raise WebwrightServiceError(
                "Webwright profile is already in use by Chrome process(es) "
                f"{', '.join(str(pid) for pid in pids)}: {self._user_data_dir}"
            )

    def _owned_cdp_process_pids(self, port: int) -> list[int]:
        if self._user_data_dir is None:
            return []
        return profile_process_pids(
            self._user_data_dir,
            remote_debugging_port=port,
        )

    def _acquire_profile_lifecycle_lock(self) -> None:
        if self._profile_lifecycle_lock is not None:
            return
        if self._user_data_dir is None:
            raise WebwrightServiceError("Cannot lock a browser profile before it is resolved.")
        lock = ProfileLifecycleLock(self._user_data_dir)
        try:
            lock.acquire()
        except Exception:
            raise
        self._profile_lifecycle_lock = lock

    def _release_profile_lifecycle_lock(self) -> None:
        lock = self._profile_lifecycle_lock
        if lock is None:
            return
        try:
            lock.release()
        finally:
            self._profile_lifecycle_lock = None

    def _remove_stale_profile_locks(self) -> None:
        """Remove lock files only after proving that no browser owns the profile."""
        self._raise_if_profile_in_use()
        if self._user_data_dir is None:
            return
        try:
            remove_stale_profile_lock_files(self._user_data_dir)
        except OSError as exc:
            raise WebwrightServiceError(
                f"Failed to remove stale browser lock files for {self._user_data_dir}: {exc}"
            ) from exc

    def _wait_for_owned_cdp_endpoint(self) -> str:
        """Return the reachable endpoint for this service's owned CDP process.

        ``DevToolsActivePort`` is written only when Chrome receives
        ``--remote-debugging-port=0``.  This service deliberately picks a
        unique non-zero loopback port so it can verify the exact Chrome
        process before attaching, therefore endpoint readiness must be
        established by polling the CDP endpoint itself rather than that file.
        """
        if self._user_data_dir is None or self._cdp_port is None:
            raise WebwrightServiceError("Cannot resolve a CDP endpoint before the profile is set.")
        endpoint = f"http://127.0.0.1:{self._cdp_port}"
        deadline = time.monotonic() + self.default_timeout
        while time.monotonic() < deadline:
            if self._chrome_process is not None and self._chrome_process.poll() is not None:
                raise WebwrightServiceError(
                    "Chrome exited before it exposed a CDP endpoint for "
                    f"profile {self._user_data_dir}."
                )
            try:
                owned_pids = self._owned_cdp_process_pids(self._cdp_port)
            except ProcessTableUnavailableError as exc:
                raise WebwrightServiceError(
                    "Cannot verify ownership of the Webwright Chrome CDP endpoint "
                    "because process-table inspection is unavailable."
                ) from exc
            if self._chrome_process is None or self._chrome_process.pid not in owned_pids:
                raise WebwrightServiceError(
                    "The CDP endpoint is not owned by this Webwright Chrome "
                    f"process for profile {self._user_data_dir}."
                )
            try:
                with urlopen(f"{endpoint}/json/version", timeout=0.5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if response.status == 200 and payload.get("webSocketDebuggerUrl"):
                    return endpoint
            except (OSError, json.JSONDecodeError):
                pass
            time.sleep(0.1)
        raise WebwrightServiceError(
            "Chrome did not expose an owned CDP endpoint within "
            f"{self.default_timeout}s for profile {self._user_data_dir}."
        )

    def _launch_owned_chrome(
        self,
        *,
        headed: bool,
        launch_args: list[str],
        window_size: tuple[int, int] | None,
    ) -> str:
        if self._user_data_dir is None:
            raise WebwrightServiceError("Cannot launch Chrome before the profile is set.")
        chrome = (
            self.local_cdp_executable
            or os.getenv("CLI_TOOLS_CHROME_BINARY")
            or _chrome_binary()
        )
        self._cdp_port = find_free_loopback_port()
        args = [
            chrome,
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={self._cdp_port}",
            f"--user-data-dir={self._user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            *launch_args,
        ]
        if window_size is not None:
            args.append(f"--window-size={window_size[0]},{window_size[1]}")
        if not headed:
            args.append("--headless=new")
        try:
            # Launch the app binary directly. On macOS, ``open -na`` returns
            # before Chrome and cannot be used as the owned process handle.
            self._chrome_process = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            raise WebwrightServiceError(f"Failed to launch owned Chrome: {exc}") from exc
        return self._wait_for_owned_cdp_endpoint()

    def _terminate_owned_chrome(self) -> None:
        """Stop only this service's profile-and-CDP-port process set."""
        process = self._chrome_process
        port = self._cdp_port
        if process is None or port is None:
            raise WebwrightServiceError(
                "Cannot verify the owned Webwright Chrome process before close."
            )
        try:
            try:
                owned_pids = self._owned_cdp_process_pids(port)
            except ProcessTableUnavailableError as exc:
                raise WebwrightServiceError(
                    "Cannot verify that the owned Webwright Chrome process closed "
                    "because process-table inspection is unavailable."
                ) from exc
            if process.pid not in owned_pids:
                raise WebwrightServiceError(
                    "The Webwright Chrome process no longer matches its managed "
                    f"profile and CDP port {port}; refusing broad profile teardown."
                )
            for pid in owned_pids:
                terminate_process(pid)
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            remaining = self._owned_cdp_process_pids(port)
            if remaining:
                raise WebwrightServiceError(
                    "Chrome process(es) still own the managed Webwright CDP endpoint "
                    f"after close: {', '.join(str(pid) for pid in remaining)}."
                )
        except ProcessTableUnavailableError as exc:
            raise WebwrightServiceError(
                "Cannot verify that the owned Webwright Chrome process closed "
                "because process-table inspection is unavailable."
            ) from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise WebwrightServiceError(f"Failed to stop owned Chrome: {exc}") from exc
        finally:
            self._chrome_process = None
            self._cdp_port = None

    def browser_open(
        self,
        url: Optional[str] = None,
        headed: bool = False,
        persistent_profile_dir: Optional[Path] = None,
        user_agent: Optional[str] = None,
        window_size: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Open Webwright against a Chrome process owned by this service."""
        if persistent_profile_dir is None:
            raise WebwrightServiceError(
                "browser_open: persistent_profile_dir is required. "
                "Pass config.get_persistent_profile_dir() from the caller."
            )
        if self.browser_mode != "local_cdp":
            raise WebwrightServiceError(
                "WebwrightBrowserService supports only local_cdp because "
                "local_persistent inherits Playwright mock-keychain arguments."
            )
        if self.local_cdp_url is not None:
            raise WebwrightServiceError(
                "local_cdp_url is not supported for managed persistent profiles. "
                "WebwrightBrowserService launches and verifies its own ephemeral "
                "loopback CDP endpoint."
            )
        if headed and os.getenv("CLI_TOOL_TEST_NO_HEADED_BROWSER") == "1":
            headed = False
        if self._opened:
            self.browser_close()

        profile_dir = Path(persistent_profile_dir)
        profile_dir.mkdir(parents=True, exist_ok=True)
        self._user_data_dir = profile_dir

        width_height = _parse_window_size(window_size)
        launch_args: list[str] = ["--restore-last-session"]
        if user_agent:
            launch_args.append(f"--user-agent={user_agent}")

        output_dir = profile_dir.parent / "webwright" / self.session
        environment = None
        try:
            self._acquire_profile_lifecycle_lock()
            self._remove_stale_profile_locks()
            cdp_endpoint = self._launch_owned_chrome(
                headed=headed,
                launch_args=launch_args,
                window_size=width_height,
            )
            # ``headless`` is enacted by the Chrome process we launch. Upstream
            # local_cdp ignores its own headless config, so never delegate that
            # decision to Webwright or allow it to autostart/attach to port 9222.
            kwargs: dict[str, Any] = {
                "browser_mode": "local_cdp",
                "headless": not headed,
                "output_dir": output_dir,
                "user_data_dir": profile_dir,
                "browser_timeout_ms": self.default_timeout * 1000,
                "browser_navigation_timeout_ms": self.default_timeout * 1000,
                "launch_args": launch_args,
                "local_cdp_url": cdp_endpoint,
                "local_cdp_auto_start": False,
            }
            if self.local_cdp_new_page is not None:
                kwargs["local_cdp_new_page"] = self.local_cdp_new_page
            if self.local_cdp_close_page_on_exit is not None:
                kwargs["local_cdp_close_page_on_exit"] = self.local_cdp_close_page_on_exit
            if width_height is not None:
                kwargs["browser_width"], kwargs["browser_height"] = width_height

            env_cls = _load_local_browser_environment()
            environment = env_cls(**kwargs)
            self._environment = environment
            environment.prepare(
                task=f"Open {url}" if url else "Open browser",
                task_id=self.session,
                start_url=url,
            )
            self._opened = True
            return self._page_info()
        except Exception as exc:
            try:
                if environment is not None:
                    environment.close()
            finally:
                try:
                    if self._chrome_process is not None:
                        self._terminate_owned_chrome()
                finally:
                    self._environment = None
                    self._opened = False
                    self._release_profile_lifecycle_lock()
            raise WebwrightServiceError(f"Failed to open Webwright browser: {exc}") from exc

    def _reset_tabs_for_restore(self) -> None:
        """Leave one blank tab before closing this service's owned profile."""
        environment = self._environment
        if environment is None:
            return
        context = self._context()
        page = self._page()
        for other in list(context.pages):
            if other is not page:
                self._run(other.close())
        self._run(page.goto("about:blank"))

    def browser_close(self) -> Dict[str, Any]:
        environment = self._environment
        close_owned_browser = self._opened
        close_error = None
        try:
            if environment is not None:
                try:
                    self._reset_tabs_for_restore()
                finally:
                    environment.close()
        except Exception as exc:
            close_error = exc
        finally:
            try:
                if close_owned_browser:
                    self._terminate_owned_chrome()
            finally:
                self._environment = None
                self._opened = False
                self._release_profile_lifecycle_lock()
        if close_error is not None:
            raise WebwrightServiceError(
                f"Failed to close Webwright browser: {close_error}"
            ) from close_error
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
            self._raise_if_profile_in_use()
            shutil.rmtree(self._user_data_dir)
        return {"success": True, "message": "Session data deleted"}

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
