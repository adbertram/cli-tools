"""Lightpanda-backed browser service for CLI tools.

Lightpanda is a lightweight browser engine that speaks CDP. This service
implements the same synchronous surface as ``BrowserHarnessService`` and
``PlaywrightBrowserService``, allowing CLIs to swap backends via environment
variable without changing code.

Key differences from Chrome/browser-harness:
- Cannot use Chromium user-data-dir; cookies must be explicitly loaded/saved
- `--cookie` flag loads cookies read-only at serve start
- No lifecycle events (domcontentloaded, load); uses raw CDP navigation
- No graphical rendering; may fail on sites requiring visual elements
- Lower memory footprint (~350MB vs ~1.8GB for Chrome)

The service launches `lightpanda serve` via subprocess and connects using raw
CDP commands via cdp-use (Target.createTarget, Page.navigate, Runtime.evaluate).
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
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
    3. ~/.cache/lightpanda-node/lightpanda (common npm cache location)
    
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
    
    # Check npm cache (common on macOS)
    cache_path = Path.home() / ".cache" / "lightpanda-node" / "lightpanda"
    if cache_path.is_file():
        return str(cache_path)
    
    # Not found
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


def _wait_for_cdp_ready(port: int, timeout: float = 10.0) -> str:
    """Poll /json/version until CDP endpoint is ready.
    
    Returns the webSocketDebuggerUrl once Lightpanda is serving.
    Raises LightpandaServiceError on timeout.
    """
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/json/version"
    
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                if response.status == 200:
                    data = json.loads(response.read())
                    ws_url = data.get("webSocketDebuggerUrl")
                    if ws_url:
                        return ws_url
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            pass
        time.sleep(0.25)
    
    raise LightpandaServiceError(
        f"Lightpanda did not expose CDP on port {port} within {timeout}s"
    )


class LightpandaBrowserService:
    """Synchronous browser service backed by Lightpanda + raw CDP.
    
    Lightpanda is a lightweight browser engine optimized for automation.
    This service launches `lightpanda serve` and connects via raw CDP
    commands using cdp-use (Target.createTarget, Page.navigate, etc.).
    
    Note: Lightpanda does not emit lifecycle events (domcontentloaded, load)
    that Playwright/Puppeteer wait on, so we use raw CDP navigation instead.
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
        self._cdp_ws_url: Optional[str] = None
        self._cdp = None  # cdp-use Client
        self._target_id: Optional[str] = None
        self._session_id: Optional[str] = None
        self._opened = False
        self._user_data_dir: Optional[Path] = None
        self._cookie_file: Optional[Path] = None
        self._current_url = ""

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
        if not self._opened or self._cdp is None:
            raise LightpandaServiceError(
                f"No browser open for session '{self.session}'. Call browser_open() first."
            )

    def _page_info(self) -> Dict[str, Any]:
        """Return current page metadata."""
        if not self._opened:
            return {"url": "", "title": "", "console_errors": 0, "console_warnings": 0}
        try:
            title = self.evaluate("() => document.title") or ""
        except Exception:
            title = ""
        return {
            "url": self._current_url,
            "title": title,
            "console_errors": 0,
            "console_warnings": 0,
        }

    def _cdp_call(self, method: str, **params) -> Any:
        """Call a CDP method on the current session."""
        if not self._cdp or not self._session_id:
            raise LightpandaServiceError("CDP session not established")
        return self._cdp.send(method, params, session_id=self._session_id)

    def _save_cookies(self) -> None:
        """Save current cookies to persistent file.
        
        Lightpanda's `--cookie` flag only loads cookies at serve start,
        so we must explicitly save after mutations using CDP.
        """
        if not self._cookie_file:
            return
        try:
            cookies = self.cookie_list()
            self._cookie_file.write_text(json.dumps(cookies, indent=2))
        except Exception:
            # Non-fatal; cookies may not be critical
            pass

    def browser_open(
        self,
        url: Optional[str] = None,
        headed: bool = False,
        persistent_profile_dir: Optional[Path] = None,
        user_agent: Optional[str] = None,
        window_size: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Open Lightpanda browser and connect via raw CDP.
        
        Args:
            url: Optional URL to navigate to after opening
            headed: Ignored (Lightpanda has no graphical mode)
            persistent_profile_dir: Directory for cookie persistence
            user_agent: Optional user agent string (ignored for now)
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

        # Wait for CDP endpoint to be ready (poll /json/version first)
        try:
            self._cdp_ws_url = _wait_for_cdp_ready(self._cdp_port, timeout=10.0)
        except LightpandaServiceError:
            self._terminate_lightpanda()
            raise

        # Connect via cdp-use
        try:
            from cdp_use import Client
            self._cdp = Client(self._cdp_ws_url)
            
            # Create a target (page)
            result = self._cdp.send("Target.createTarget", {"url": "about:blank"})
            self._target_id = result.get("targetId")
            
            # Attach to target to get session
            attach_result = self._cdp.send("Target.attachToTarget", {
                "targetId": self._target_id,
                "flatten": True,
            })
            self._session_id = attach_result.get("sessionId")
            
            if not self._session_id:
                raise LightpandaServiceError("Failed to establish CDP session")
            
            self._opened = True
            
            # Navigate if URL provided
            if url:
                self.page_goto(url)
            else:
                self._current_url = "about:blank"

            return self._page_info()
            
        except Exception as exc:
            self._terminate_lightpanda()
            if self._cdp:
                try:
                    self._cdp.close()
                except Exception:
                    pass
                self._cdp = None
            raise LightpandaServiceError(
                f"Failed to connect to Lightpanda via CDP: {exc}"
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
        
        cdp = self._cdp
        self._cdp = None
        self._session_id = None
        self._target_id = None
        self._opened = False
        self._current_url = ""
        
        try:
            if cdp:
                cdp.close()
        finally:
            self._terminate_lightpanda()
        
        return {"success": True, "message": "Browser closed"}

    def page_goto(self, url: str, wait_until: str | None = None) -> Dict[str, Any]:
        """Navigate to URL using raw CDP (no lifecycle wait).
        
        Note: wait_until is ignored; Lightpanda doesn't emit lifecycle events.
        We use Page.navigate then wait a fixed time for the page to load.
        """
        self._require_open()
        
        try:
            # Navigate via CDP
            self._cdp_call("Page.enable")
            result = self._cdp_call("Page.navigate", url=url)
            
            # Check for immediate error
            if "errorText" in result:
                raise LightpandaServiceError(
                    f"Navigation failed: {result['errorText']}"
                )
            
            # Wait for page to settle (no lifecycle events in Lightpanda)
            # Use a short fixed wait + check if document is ready
            time.sleep(0.5)
            
            # Verify page is accessible
            try:
                self.evaluate("() => document.readyState")
            except Exception:
                # Page not ready yet, wait a bit more
                time.sleep(1.0)
            
            self._current_url = url
            
        except Exception as exc:
            if not isinstance(exc, LightpandaServiceError):
                raise LightpandaServiceError(
                    f"Failed to navigate to {url}: {exc}"
                ) from exc
            raise
        
        return self._page_info()

    def goto(self, url: str, wait_until: str = None) -> None:
        """Navigate to URL (Playwright-compatible alias)."""
        self.page_goto(url, wait_until=wait_until)

    def evaluate(self, js: str, arg: Any = None) -> Any:
        """Evaluate JavaScript in page context using raw CDP.
        
        Wraps string functions in immediate invocation.
        """
        self._require_open()
        
        # Wrap callable expressions
        expression = js.strip()
        if expression.startswith("(") or expression.startswith("async ("):
            # Function form - wrap in call
            if arg is not None:
                expression = f"({expression})({json.dumps(arg)})"
            else:
                expression = f"({expression})()"
        
        try:
            result = self._cdp_call(
                "Runtime.evaluate",
                expression=expression,
                returnByValue=True,
                awaitPromise=True,
            )
            
            if "exceptionDetails" in result:
                details = result["exceptionDetails"]
                error_text = details.get("text", "JavaScript evaluation failed")
                # Return None for common undefined/null errors instead of raising
                if "undefined" in error_text.lower() or "null" in error_text.lower():
                    return None
                raise LightpandaServiceError(f"{error_text}; expression: {js[:200]}")
            
            result_obj = result.get("result", {})
            if "value" in result_obj:
                return result_obj["value"]
            
            # Handle unserializable values
            if "unserializableValue" in result_obj:
                value = result_obj["unserializableValue"]
                if value == "NaN":
                    return float("nan")
                if value == "Infinity":
                    return float("inf")
                if value == "-Infinity":
                    return float("-inf")
                return value
            
            return None
            
        except Exception as exc:
            if not isinstance(exc, LightpandaServiceError):
                raise LightpandaServiceError(f"Eval error: {exc}") from exc
            raise

    def iframe_target(self, url_substr: str) -> Optional[str]:
        """Find iframe URL containing substring.
        
        Note: Limited iframe support in Lightpanda.
        """
        self._require_open()
        if not url_substr:
            raise LightpandaServiceError("iframe_target: url_substr must be non-empty")
        
        # Try to find iframes via DOM
        try:
            iframes = self.evaluate("""
                () => {
                    const frames = document.querySelectorAll('iframe');
                    return Array.from(frames).map(f => f.src || '');
                }
            """)
            if isinstance(iframes, list):
                for url in iframes:
                    if url_substr in str(url):
                        return str(url)
        except Exception:
            pass
        
        return None

    def evaluate_in_iframe(self, url_substr: str, js: str, arg: Any = None) -> Any:
        """Evaluate JS in iframe - limited support in Lightpanda."""
        # Lightpanda has limited iframe support; return None
        return None

    def page_eval(self, js: str, arg: Any = None) -> Dict[str, Any]:
        """Evaluate JS and return in dict (legacy compatibility)."""
        return {"result": self.evaluate(js, arg)}

    def keyboard_press(self, key: str) -> Dict[str, Any]:
        """Press keyboard key via CDP."""
        self._require_open()
        
        # Map common key names
        key_map = {
            "Enter": "\r",
            "Tab": "\t",
            "Escape": "\x1b",
        }
        key_to_send = key_map.get(key, key)
        
        try:
            self._cdp_call("Input.dispatchKeyEvent", type="keyDown", text=key_to_send)
            self._cdp_call("Input.dispatchKeyEvent", type="keyUp", text=key_to_send)
        except Exception as exc:
            raise LightpandaServiceError(f"Failed to press key {key}: {exc}") from exc
        
        return self._page_info()

    def type_text(self, text: str) -> Dict[str, Any]:
        """Type text into focused element."""
        self._require_open()
        
        try:
            for char in text:
                self._cdp_call("Input.dispatchKeyEvent", type="char", text=char)
        except Exception as exc:
            raise LightpandaServiceError(f"Failed to type text: {exc}") from exc
        
        return self._page_info()

    def cookie_list(self) -> List[Dict[str, Any]]:
        """Return all cookies via CDP."""
        self._require_open()
        
        try:
            result = self._cdp_call("Network.getAllCookies")
            cookies = result.get("cookies", [])
            if not isinstance(cookies, list):
                raise LightpandaServiceError(
                    f"Network.getAllCookies returned unexpected payload: {result!r}"
                )
            return cookies
        except Exception as exc:
            if not isinstance(exc, LightpandaServiceError):
                raise LightpandaServiceError(f"Failed to get cookies: {exc}") from exc
            raise

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
        
        # Poll for selector
        deadline = time.time() + (timeout / 1000.0)
        poll_interval = 0.1
        
        while time.time() < deadline:
            if state == "attached":
                exists = self.evaluate(
                    f"() => !!document.querySelector({json.dumps(selector)})"
                )
                if exists:
                    return _ServiceElement(self, css=selector)
            elif state == "visible":
                visible = self.evaluate(
                    f"() => {{ const el = document.querySelector({json.dumps(selector)}); "
                    f"return el && el.offsetParent !== null; }}"
                )
                if visible:
                    return _ServiceElement(self, css=selector)
            elif state == "detached":
                exists = self.evaluate(
                    f"() => !!document.querySelector({json.dumps(selector)})"
                )
                if not exists:
                    return None
            else:  # hidden
                visible = self.evaluate(
                    f"() => {{ const el = document.querySelector({json.dumps(selector)}); "
                    f"return el && el.offsetParent !== null; }}"
                )
                if not visible:
                    return None
            
            time.sleep(poll_interval)
        
        raise LightpandaServiceError(
            f"wait_for_selector: timed out after {timeout}ms waiting "
            f"for selector {selector!r} to be {state}"
        )

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
        """Capture accessibility tree snapshot (simplified for Lightpanda)."""
        self._require_open()
        # Lightpanda doesn't support full a11y tree; return simplified text
        try:
            text = self.evaluate(
                f"() => document.querySelector({json.dumps(selector)})?.innerText || ''"
            )
            return f"- text: {text}" if text else ""
        except Exception:
            return ""

    @property
    def url(self) -> str:
        """Return current URL."""
        return self._current_url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        try:
            self.browser_close()
        except LightpandaServiceError:
            pass
        return False
