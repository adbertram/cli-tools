"""Lightpanda-backed browser service for CLI tools.

Lightpanda is a lightweight browser engine that speaks CDP and works with
Puppeteer. This service implements the same synchronous surface as
``BrowserHarnessService`` and ``PlaywrightBrowserService``, allowing CLIs
to swap backends via environment variable without changing code.

Key differences from Chrome/browser-harness:
- Cannot use Chromium user-data-dir; cookies must be explicitly loaded/saved
- `--cookie` flag loads cookies read-only at serve start
- String-form `page.evaluate("() => ...")` can return `{}`; use function form
- No graphical rendering; may fail on sites requiring visual elements
- Lower memory footprint (~350MB vs ~1.8GB for Chrome)

The service launches `lightpanda serve` via subprocess and connects over CDP
using puppeteer-core (pyppeteer or playwright's bundled CDP).
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from . import BrowserHarnessError
from ._elements import _ServiceElement, _ServiceLocator


class LightpandaServiceError(BrowserHarnessError):
    """Error from LightpandaBrowserService operations."""


def _find_free_port() -> int:
    """Find an available local port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _find_lightpanda_binary() -> str:
    """Locate the Lightpanda binary.
    
    Looks for:
    1. CLI_TOOLS_LIGHTPANDA_BINARY env var
    2. `lightpanda` in PATH
    3. npx @lightpanda/browser cache
    
    Raises:
        LightpandaServiceError: When binary cannot be found.
    """
    # Check env var override
    if override := os.environ.get("CLI_TOOLS_LIGHTPANDA_BINARY"):
        if Path(override).is_file():
            return override
        raise LightpandaServiceError(
            f"CLI_TOOLS_LIGHTPANDA_BINARY points to non-existent file: {override}"
        )
    
    # Check PATH
    import shutil
    if path_bin := shutil.which("lightpanda"):
        return path_bin
    
    # Try npx cache (common install via `npx @lightpanda/browser`)
    # The exact path varies by npm/npx version, so we'll just tell users to install
    raise LightpandaServiceError(
        "Lightpanda binary not found. Install via npm/npx:\n"
        "  npm install -g @lightpanda/browser\n"
        "or set CLI_TOOLS_LIGHTPANDA_BINARY to the binary path."
    )


def _parse_window_size(window_size: str | None) -> tuple[int, int] | None:
    """Parse window size string like '1280x720' into (width, height)."""
    if not window_size:
        return None
    cleaned = window_size.lower().replace(",", "x")
    parts = cleaned.split("x")
    if len(parts) != 2:
        raise LightpandaServiceError(
            f"window_size must be formatted as WIDTHxHEIGHT, got {window_size!r}."
        )
    try:
        width = int(parts[0].strip())
        height = int(parts[1].strip())
    except ValueError as exc:
        raise LightpandaServiceError(
            f"window_size must contain integer width and height, got {window_size!r}."
        ) from exc
    if width <= 0 or height <= 0:
        raise LightpandaServiceError(
            f"window_size values must be positive, got {window_size!r}."
        )
    return width, height


class LightpandaBrowserService:
    """Synchronous browser service backed by Lightpanda + Puppeteer CDP.
    
    Lightpanda is a lightweight browser engine optimized for automation.
    This service launches `lightpanda serve` and connects via CDP using
    playwright's bundled Chromium CDP client (no external dependencies).
    """

    def __init__(
        self,
        session: str,
        *,
        timeout: int = 60,
    ):
        self.session = session
        self.default_timeout = timeout
        self._lightpanda_proc: Optional[subprocess.Popen] = None
        self._cdp_port: Optional[int] = None
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._opened = False
        self._user_data_dir: Optional[Path] = None
        self._cookie_file: Optional[Path] = None

    @staticmethod
    def _safe_url_for_log(url: str) -> str:
        """Redact query params and fragments from URLs for logs."""
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
        """Ensure browser is open, raise if not."""
        if not self._opened or self._page is None:
            raise LightpandaServiceError(
                f"No browser open for session '{self.session}'. Call browser_open() first."
            )

    def _page_info(self) -> Dict[str, Any]:
        """Return current page metadata."""
        if not self._opened or self._page is None:
            return {"url": "", "title": "", "console_errors": 0, "console_warnings": 0}
        try:
            # Use evaluate to get title since Playwright page.title() may not work
            title = self._page.evaluate("() => document.title") or ""
        except Exception:
            title = ""
        return {
            "url": self._page.url or "",
            "title": title,
            "console_errors": 0,
            "console_warnings": 0,
        }

    def _save_cookies(self) -> None:
        """Save current cookies to persistent file.
        
        Lightpanda's `--cookie` flag only loads cookies at serve start,
        so we must explicitly save after mutations. Uses CDP
        Network.getAllCookies + JSON format compatible with Lightpanda.
        """
        if not self._cookie_file or not self._context:
            return
        try:
            cookies = self._context.cookies()
            # Lightpanda expects array of {name, value, domain, path, ...}
            self._cookie_file.write_text(json.dumps(cookies, indent=2))
        except Exception as exc:
            # Non-fatal; log but don't block
            import logging
            logging.debug(f"Failed to save cookies for {self.session}: {exc}")

    def _load_cookies_from_file(self) -> None:
        """Load cookies from persistent file into current context."""
        if not self._cookie_file or not self._cookie_file.exists():
            return
        try:
            cookies = json.loads(self._cookie_file.read_text())
            if isinstance(cookies, list) and self._context:
                self._context.add_cookies(cookies)
        except Exception as exc:
            import logging
            logging.debug(f"Failed to load cookies for {self.session}: {exc}")

    def browser_open(
        self,
        url: Optional[str] = None,
        headed: bool = False,
        persistent_profile_dir: Optional[Path] = None,
        user_agent: Optional[str] = None,
        window_size: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Open Lightpanda browser and connect via CDP.
        
        Args:
            url: Optional URL to navigate to after opening
            headed: Ignored (Lightpanda has no graphical mode)
            persistent_profile_dir: Directory for cookie persistence
            user_agent: Optional user agent string
            window_size: Ignored (no visual rendering)
        
        Returns:
            Page info dict with url, title, etc.
        """
        if persistent_profile_dir is None:
            raise LightpandaServiceError(
                "browser_open: persistent_profile_dir is required. "
                "Pass config.get_persistent_profile_dir() from the caller."
            )
        
        if self._opened:
            self.browser_close()

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise LightpandaServiceError(
                "Playwright is required for Lightpanda CDP connection. "
                "Install it: uv add playwright"
            ) from exc

        # Set up persistent directory for cookies
        profile_dir = Path(persistent_profile_dir)
        profile_dir.mkdir(parents=True, exist_ok=True)
        self._user_data_dir = profile_dir
        self._cookie_file = profile_dir / "cookies.json"

        # Find Lightpanda binary
        try:
            lightpanda = _find_lightpanda_binary()
        except LightpandaServiceError:
            raise

        # Allocate port for CDP
        self._cdp_port = _find_free_port()

        # Build Lightpanda serve command
        args = [
            lightpanda,
            "serve",
            "--host", "127.0.0.1",
            "--port", str(self._cdp_port),
        ]
        
        # Load cookies if file exists
        if self._cookie_file.exists():
            args.extend(["--cookie", str(self._cookie_file)])

        # Launch Lightpanda
        try:
            self._lightpanda_proc = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            raise LightpandaServiceError(
                f"Failed to spawn Lightpanda: {exc}"
            ) from exc

        # Wait for CDP endpoint to be available
        max_wait = 10  # seconds
        start = time.time()
        cdp_url = f"http://127.0.0.1:{self._cdp_port}"
        
        while time.time() - start < max_wait:
            try:
                # Try to connect via Playwright CDP
                self._playwright = sync_playwright().start()
                self._browser = self._playwright.chromium.connect_over_cdp(cdp_url)
                break
            except Exception:
                if self._playwright:
                    try:
                        self._playwright.stop()
                    except Exception:
                        pass
                    self._playwright = None
                time.sleep(0.25)
        else:
            # Timeout
            self._terminate_lightpanda()
            raise LightpandaServiceError(
                f"Lightpanda did not expose CDP on port {self._cdp_port} within {max_wait}s"
            )

        try:
            # Get or create page
            contexts = self._browser.contexts
            if contexts:
                self._context = contexts[0]
                pages = self._context.pages
                self._page = pages[0] if pages else self._context.new_page()
            else:
                self._context = self._browser.new_context()
                self._page = self._context.new_page()
            
            # Set timeouts
            self._page.set_default_timeout(self.default_timeout * 1000)
            self._page.set_default_navigation_timeout(self.default_timeout * 1000)
            
            self._opened = True

            # Navigate if URL provided
            if url:
                self.page_goto(url)

            return self._page_info()
            
        except Exception as exc:
            self.browser_close()
            raise LightpandaServiceError(
                f"Failed to initialize Lightpanda page: {exc}"
            ) from exc

    def _terminate_lightpanda(self) -> None:
        """Terminate Lightpanda serve process."""
        if self._lightpanda_proc is None:
            return
        try:
            self._lightpanda_proc.terminate()
            try:
                self._lightpanda_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._lightpanda_proc.kill()
                self._lightpanda_proc.wait(timeout=5)
        except Exception:
            pass
        finally:
            self._lightpanda_proc = None

    def browser_close(self) -> Dict[str, Any]:
        """Close browser and terminate Lightpanda process."""
        # Save cookies before closing
        self._save_cookies()
        
        page = self._page
        context = self._context
        browser = self._browser
        playwright = self._playwright
        
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._opened = False
        
        try:
            if page:
                try:
                    page.close()
                except Exception:
                    pass
        finally:
            try:
                if context:
                    context.close()
            finally:
                try:
                    if browser:
                        browser.close()
                finally:
                    try:
                        if playwright:
                            playwright.stop()
                    finally:
                        self._terminate_lightpanda()
        
        return {"success": True, "message": "Browser closed"}

    def page_goto(self, url: str, wait_until: str | None = "domcontentloaded") -> Dict[str, Any]:
        """Navigate to URL."""
        self._require_open()
        self._page.goto(url, wait_until=wait_until or "domcontentloaded")
        return self._page_info()

    def goto(self, url: str, wait_until: str = None) -> None:
        """Navigate to URL (Playwright-compatible alias)."""
        self.page_goto(url, wait_until=wait_until or "domcontentloaded")

    def evaluate(self, js: str, arg: Any = None) -> Any:
        """Evaluate JavaScript in page context.
        
        Note: Use function form for Lightpanda, not string form.
        String `"() => ..."` may return `{}`, but function form works.
        """
        self._require_open()
        if arg is None:
            return self._page.evaluate(js)
        return self._page.evaluate(js, arg)

    def iframe_target(self, url_substr: str) -> Optional[str]:
        """Find iframe URL containing substring."""
        self._require_open()
        if not url_substr:
            raise LightpandaServiceError("iframe_target: url_substr must be non-empty")
        for frame in self._page.frames:
            if url_substr in (frame.url or ""):
                return frame.url
        return None

    def evaluate_in_iframe(self, url_substr: str, js: str, arg: Any = None) -> Any:
        """Evaluate JS in iframe matching URL substring."""
        self._require_open()
        frame = next(
            (f for f in self._page.frames if url_substr in (f.url or "")),
            None,
        )
        if frame is None:
            return None
        if arg is None:
            return frame.evaluate(js)
        return frame.evaluate(js, arg)

    def page_eval(self, js: str, arg: Any = None) -> Dict[str, Any]:
        """Evaluate JS and return in dict (legacy compatibility)."""
        return {"result": self.evaluate(js, arg)}

    def keyboard_press(self, key: str) -> Dict[str, Any]:
        """Press keyboard key."""
        self._require_open()
        self._page.keyboard.press(key)
        return self._page_info()

    def type_text(self, text: str) -> Dict[str, Any]:
        """Type text into focused element."""
        self._require_open()
        self._page.keyboard.type(text)
        return self._page_info()

    def cookie_list(self) -> List[Dict[str, Any]]:
        """Return all cookies from current context."""
        self._require_open()
        cookies = self._context.cookies()
        if not isinstance(cookies, list):
            raise LightpandaServiceError(
                f"Lightpanda context.cookies() returned unexpected payload: {cookies!r}"
            )
        return cookies

    def localstorage_list(self) -> List[Dict[str, str]]:
        """Return localStorage entries as list of dicts."""
        result = self.evaluate(
            "() => Object.entries(localStorage).map(([key, value]) => ({key, value}))"
        )
        return result or []

    def data_delete(self) -> Dict[str, Any]:
        """Delete persistent data (cookies file)."""
        self.browser_close()
        if self._cookie_file and self._cookie_file.exists():
            try:
                self._cookie_file.unlink()
            except OSError:
                pass
        return {"success": True, "message": "Session data deleted"}

    def locator(self, selector: str) -> _ServiceLocator:
        """Return locator for selector."""
        return _ServiceLocator(self, selector)

    def get_by_role(self, role: str, *, name=None, exact: bool = False) -> _ServiceLocator:
        """Return locator by ARIA role."""
        return _ServiceLocator.from_role(self, role, name, exact=exact)

    def get_by_placeholder(self, text: str) -> _ServiceLocator:
        """Return locator by placeholder text."""
        return _ServiceLocator(self, f'[placeholder="{text}"]')

    def wait_for_timeout(self, ms: int) -> None:
        """Sleep for milliseconds."""
        time.sleep(ms / 1000)

    def wait_for_selector(
        self,
        selector: str,
        *,
        state: str = "visible",
        timeout: int = 30000,
    ) -> Optional[_ServiceElement]:
        """Wait for selector to reach state."""
        valid_states = ("attached", "visible", "hidden", "detached")
        if state not in valid_states:
            raise LightpandaServiceError(
                f"wait_for_selector: state must be one of {valid_states}, got {state!r}"
            )
        self._require_open()
        self._page.wait_for_selector(selector, state=state, timeout=timeout)
        if state in ("hidden", "detached"):
            return None
        return _ServiceElement(self, css=selector)

    def query_selector(self, selector: str) -> Optional[_ServiceElement]:
        """Query for selector, return element or None."""
        self._require_open()
        present = self.evaluate(
            f"() => !!document.querySelector({json.dumps(selector)})"
        )
        if not present:
            return None
        return _ServiceElement(self, css=selector)

    def fill(self, selector: str, text: str) -> None:
        """Fill input element."""
        self._require_open()
        _ServiceElement(self, css=selector).fill(text)

    def aria_snapshot(self, selector: str = "body", *, timeout: int = 5000) -> str:
        """Capture accessibility tree snapshot."""
        self._require_open()
        # Lightpanda may not support full a11y tree; return simplified version
        try:
            return self._page.locator(selector).aria_snapshot(timeout=timeout)
        except Exception:
            # Fallback to text content if a11y not supported
            text = self.evaluate(
                f"() => document.querySelector({json.dumps(selector)})?.innerText || ''"
            )
            return f"- text: {text}" if text else ""

    @property
    def url(self) -> str:
        """Return current URL."""
        try:
            return self._page_info().get("url", "")
        except Exception:
            return ""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        try:
            self.browser_close()
        except LightpandaServiceError:
            pass
        return False
