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

The service launches `lightpanda serve` via subprocess and connects using
CDPClient (async) with a background event loop via run_coroutine_threadsafe.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import subprocess
import threading
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


def _is_cloudflare_blocked(title: str, body: str, url: str, status_code: Optional[int] = None) -> bool:
    """Detect if page shows Cloudflare challenge/block.
    
    Args:
        title: Page title (lowercased)
        body: Page body text (lowercased) 
        url: Current URL
        status_code: HTTP status code if available
        
    Returns:
        True if page appears to be Cloudflare-blocked
    """
    # Check HTTP 403
    if status_code == 403:
        return True
    
    # Check title/body markers (case-insensitive)
    title_lower = title.lower()
    body_lower = body.lower()
    
    cf_markers = [
        "just a moment",
        "checking your browser",
        "attention required",
        "cloudflare",
        "please enable javascript",
        "enable cookies",
    ]
    
    return any(marker in title_lower or marker in body_lower for marker in cf_markers)


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
    """Synchronous browser service backed by Lightpanda + async CDP.
    
    Lightpanda is a lightweight browser engine optimized for automation.
    This service launches `lightpanda serve` and connects via CDPClient
    (async) running in a background event loop thread.
    
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
        self._cdp_client = None  # CDPClient (async)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
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
        if not self._opened or self._cdp_client is None:
            raise LightpandaServiceError(
                f"No browser open for session '{self.session}'. Call browser_open() first."
            )

    def _run_async(self, coro):
        """Run async coroutine in background event loop, return result synchronously."""
        if not self._loop:
            raise LightpandaServiceError("Event loop not running")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=self.default_timeout)
        except Exception as exc:
            if isinstance(exc, asyncio.TimeoutError):
                raise LightpandaServiceError(
                    f"CDP operation timed out after {self.default_timeout}s"
                ) from exc
            raise

    async def _cdp_send(self, method: str, params: Optional[Dict] = None) -> Any:
        """Send CDP command on current session."""
        if not self._cdp_client or not self._session_id:
            raise LightpandaServiceError("CDP session not established")
        result = await self._cdp_client.send_raw(
            method,
            params or {},
            session_id=self._session_id
        )
        return result

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

    def _start_event_loop(self):
        """Start background asyncio event loop in a daemon thread."""
        def run_loop(loop):
            asyncio.set_event_loop(loop)
            loop.run_forever()
        
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=run_loop, args=(self._loop,), daemon=True)
        self._loop_thread.start()

    def _stop_event_loop(self):
        """Stop background event loop."""
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._loop_thread:
                self._loop_thread.join(timeout=2.0)
            self._loop = None
            self._loop_thread = None

    def browser_open(
        self,
        url: Optional[str] = None,
        headed: bool = False,
        persistent_profile_dir: Optional[Path] = None,
        user_agent: Optional[str] = None,
        window_size: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Open Lightpanda browser and connect via async CDP.
        
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
        
        # Load cookies if file exists (both --cookie for read and --cookie-jar for write)
        if self._cookie_file.exists():
            args.extend(["--cookie", str(self._cookie_file)])
        args.extend(["--cookie-jar", str(self._cookie_file)])
        
        # Load resources (iframes and stylesheets for better rendering)
        args.extend([
            "--load-resources", "iframe",
            "--load-resources", "stylesheet",
        ])
        
        # Optional user agent (Lightpanda forbids Mozilla strings)
        # Use CLI_TOOLS_LIGHTPANDA_USER_AGENT for custom identity (e.g. bot name)
        # or CLI_TOOLS_LIGHTPANDA_UA_SUFFIX to append to default Lightpanda/1.0
        custom_ua = os.environ.get("CLI_TOOLS_LIGHTPANDA_USER_AGENT")
        ua_suffix = os.environ.get("CLI_TOOLS_LIGHTPANDA_UA_SUFFIX")
        
        if custom_ua:
            # Validate: Lightpanda rejects any UA containing "Mozilla"
            if "mozilla" in custom_ua.lower():
                raise LightpandaServiceError(
                    "CLI_TOOLS_LIGHTPANDA_USER_AGENT cannot contain 'Mozilla' - "
                    "Lightpanda intentionally forbids Chrome impersonation. "
                    "Use a non-browser identity or Web Bot Auth instead."
                )
            args.extend(["--user-agent", custom_ua])
        elif ua_suffix:
            args.extend(["--user-agent", f"Lightpanda/1.0 {ua_suffix}"])
        
        # Optional Web Bot Auth for Cloudflare Verified Bots
        # See: https://developers.cloudflare.com/bots/concepts/bot-management/
        web_bot_key = os.environ.get("CLI_TOOLS_LIGHTPANDA_WEB_BOT_AUTH_KEY_FILE")
        web_bot_keyid = os.environ.get("CLI_TOOLS_LIGHTPANDA_WEB_BOT_AUTH_KEYID")
        web_bot_domain = os.environ.get("CLI_TOOLS_LIGHTPANDA_WEB_BOT_AUTH_DOMAIN")
        
        if web_bot_key and web_bot_keyid and web_bot_domain:
            args.extend([
                "--web-bot-auth-key-file", web_bot_key,
                "--web-bot-auth-keyid", web_bot_keyid,
                "--web-bot-auth-domain", web_bot_domain,
            ])

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

        # Start background event loop
        self._start_event_loop()

        # Connect via CDPClient
        try:
            from cdp_use.client import CDPClient
            
            async def connect_and_setup():
                # Create and start CDP client
                client = CDPClient(self._cdp_ws_url)
                await client.start()
                self._cdp_client = client
                
                # Create a target (page)
                result = await client.send_raw("Target.createTarget", {"url": "about:blank"})
                target_id = result.get("targetId")
                
                # Attach to target to get session
                attach_result = await client.send_raw("Target.attachToTarget", {
                    "targetId": target_id,
                    "flatten": True,
                })
                session_id = attach_result.get("sessionId")
                
                if not session_id:
                    raise LightpandaServiceError("Failed to establish CDP session")
                
                return target_id, session_id
            
            self._target_id, self._session_id = self._run_async(connect_and_setup())
            
            # Enable necessary domains
            async def enable_domains():
                await self._cdp_send("Page.enable")
                await self._cdp_send("Runtime.enable")
                await self._cdp_send("Network.enable")
                await self._cdp_send("DOM.enable")
            
            self._run_async(enable_domains())
            
            self._opened = True
            
            # Navigate if URL provided
            if url:
                self.page_goto(url)
            else:
                self._current_url = "about:blank"

            return self._page_info()
            
        except Exception as exc:
            self._terminate_lightpanda()
            self._stop_event_loop()
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
        
        cdp_client = self._cdp_client
        self._cdp_client = None
        self._session_id = None
        self._target_id = None
        self._opened = False
        self._current_url = ""
        
        try:
            if cdp_client and self._loop:
                async def close_client():
                    try:
                        await cdp_client.close()
                    except Exception:
                        pass
                
                try:
                    self._run_async(close_client())
                except Exception:
                    pass
        finally:
            self._stop_event_loop()
            self._terminate_lightpanda()
        
        return {"success": True, "message": "Browser closed"}

    def page_goto(self, url: str, wait_until: str | None = None) -> Dict[str, Any]:
        """Navigate to URL using raw CDP (no lifecycle wait).
        
        Note: wait_until is ignored; Lightpanda doesn't emit lifecycle events.
        We use Page.navigate then poll document.readyState.
        """
        self._require_open()
        
        try:
            async def navigate():
                # Navigate via CDP
                result = await self._cdp_send("Page.navigate", {"url": url})
                
                # Check for immediate error
                if "errorText" in result:
                    raise LightpandaServiceError(
                        f"Navigation failed: {result['errorText']}"
                    )
                
                # Wait for page to settle (no lifecycle events in Lightpanda)
                await asyncio.sleep(0.5)
                
                # Verify page is accessible by checking readyState
                try:
                    eval_result = await self._cdp_send(
                        "Runtime.evaluate",
                        {
                            "expression": "document.readyState",
                            "returnByValue": True,
                        }
                    )
                    if "exceptionDetails" not in eval_result:
                        # Page is ready
                        return
                except Exception:
                    pass
                
                # If not ready, wait a bit more
                await asyncio.sleep(1.0)
            
            self._run_async(navigate())
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
        """Evaluate JavaScript in page context using async CDP.
        
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
        
        async def eval_js():
            result = await self._cdp_send(
                "Runtime.evaluate",
                {
                    "expression": expression,
                    "returnByValue": True,
                    "awaitPromise": True,
                }
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
        
        try:
            return self._run_async(eval_js())
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
        
        async def press_key():
            await self._cdp_send("Input.dispatchKeyEvent", {"type": "keyDown", "text": key_to_send})
            await self._cdp_send("Input.dispatchKeyEvent", {"type": "keyUp", "text": key_to_send})
        
        try:
            self._run_async(press_key())
        except Exception as exc:
            raise LightpandaServiceError(f"Failed to press key {key}: {exc}") from exc
        
        return self._page_info()

    def type_text(self, text: str) -> Dict[str, Any]:
        """Type text into focused element."""
        self._require_open()
        
        async def type_chars():
            for char in text:
                await self._cdp_send("Input.dispatchKeyEvent", {"type": "char", "text": char})
        
        try:
            self._run_async(type_chars())
        except Exception as exc:
            raise LightpandaServiceError(f"Failed to type text: {exc}") from exc
        
        return self._page_info()

    def cookie_list(self) -> List[Dict[str, Any]]:
        """Return all cookies via CDP."""
        self._require_open()
        
        async def get_cookies():
            result = await self._cdp_send("Network.getAllCookies")
            cookies = result.get("cookies", [])
            if not isinstance(cookies, list):
                raise LightpandaServiceError(
                    f"Network.getAllCookies returned unexpected payload: {result!r}"
                )
            return cookies
        
        try:
            return self._run_async(get_cookies())
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
    
    def is_cloudflare_blocked(self) -> bool:
        """Check if current page shows Cloudflare challenge/block.
        
        Returns True if the page appears to be Cloudflare-blocked,
        indicating a fallback to Chrome is needed.
        """
        if not self._opened:
            return False
        
        try:
            # Get page title and body text
            title = self.evaluate("() => document.title || ''") or ""
            body = self.evaluate("() => document.body?.innerText?.slice(0, 2000) || ''") or ""
            
            # Check for CF markers
            return _is_cloudflare_blocked(title, body, self._current_url)
        except Exception:
            # If we can't check, assume not blocked
            return False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        try:
            self.browser_close()
        except LightpandaServiceError:
            pass
        return False
