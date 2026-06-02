"""BrowserHarnessService - browser automation backed by browser-harness.

Public API matches the previous browser-automation implementation so callers
(BrowserAutomation, brickfreedom client.py, _ServiceElement/_ServiceLocator)
need no changes.  Internally this drives Chrome via the browser-harness CDP
daemon (https://github.com/browser-use/browser-harness) instead of an external automation framework.

Session model: each session owns a Chrome process launched with its own
``--remote-debugging-port`` and ``--user-data-dir``, paired with a dedicated
browser-harness daemon (``BU_NAME``).  This mirrors the previous
``launch_persistent_context(user_data_dir)`` model.
"""

import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import fcntl
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from .._debug_logging import get_debug_logger
from . import BrowserHarnessError
from ._elements import _ServiceLocator

logger = get_debug_logger("cli_tools.browser_service")

# macOS AF_UNIX paths are limited to 104 bytes.  Browser-harness writes its
# socket under BH_RUNTIME_DIR; keep this short to stay within budget.
_BH_RUNTIME_ROOT = Path("/tmp/cli-tools-bh")


def _ensure_runtime_dir(session: str) -> Path:
    """Per-session short runtime dir for AF_UNIX socket / pid / port files."""
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session)[:32]
    d = _BH_RUNTIME_ROOT / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def _find_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _chrome_binary() -> str:
    """Locate Chrome (or compatible) on macOS / Linux / Windows."""
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
    raise BrowserHarnessError(
        "Could not locate a Chrome/Chromium binary. Install Google Chrome "
        "or set CLI_TOOLS_CHROME_BINARY."
    )


def _chrome_launch_command(chrome: str, args: list[str]) -> list[str]:
    """Return the command that starts an isolated Chrome instance."""
    if sys.platform == "darwin" and ".app/Contents/MacOS/" in chrome:
        app_path = chrome.split("/Contents/MacOS/", 1)[0]
        return ["/usr/bin/open", "-na", app_path, "--args", *args[1:]]
    return args


def _wait_for_cdp(port: int, timeout: float = 30.0) -> None:
    """Block until Chrome's /json/version endpoint is alive."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/version", timeout=1.0
            ) as r:
                if r.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            time.sleep(0.25)
    raise BrowserHarnessError(
        f"Chrome did not expose CDP on port {port} within {timeout}s"
    )


class _BrowserHarness:
    """Per-session adapter that binds helper calls to this session's daemon.

    browser_harness.helpers caches NAME at import time, but every helper
    call reads the module-level NAME at call time via _send().  Patch it
    (and the cached _ipc paths) before every call so that multiple
    BrowserHarnessService instances in one process can target different
    daemons.
    """

    def __init__(self, session: str, runtime_dir: Path):
        self.session = session
        self.runtime_dir = runtime_dir

    @property
    def h(self):
        os.environ["BH_RUNTIME_DIR"] = str(self.runtime_dir)
        os.environ["BH_TMP_DIR"] = str(self.runtime_dir)
        from browser_harness import _ipc, helpers
        _ipc._TMP = Path(os.environ["BH_TMP_DIR"])
        _ipc._RUNTIME = Path(os.environ["BH_RUNTIME_DIR"])
        _ipc.BH_TMP_DIR = os.environ["BH_TMP_DIR"]
        _ipc.BH_RUNTIME_DIR = os.environ["BH_RUNTIME_DIR"]
        helpers.NAME = self.session
        helpers.SOCK = _ipc.sock_addr(self.session)
        return helpers

class BrowserHarnessService:
    """Browser automation service backed by browser-harness.

    The class and its public methods deliberately keep their original names
    so callers (notably BrowserAutomation and brickfreedom client.py) do not
    need to change.
    """

    def __init__(self, session: str, timeout: int = 60):
        self.session = session
        self.default_timeout = timeout
        self._chrome_proc: Optional[subprocess.Popen] = None
        self._cdp_port: Optional[int] = None
        self._opened = False
        # Persistent Chromium user-data-dir. Set by ``browser_open`` from the
        # caller-supplied ``persistent_profile_dir``. Attribute (not method)
        # because the daemon-key scope and the Chrome user-data-dir scope are
        # decoupled — the caller resolves the path through config.
        self._user_data_dir: Optional[Path] = None
        self._runtime_dir = _ensure_runtime_dir(session)
        self._lifecycle_lock_path = self._runtime_dir / "lifecycle.lock"
        self._lifecycle_lock_file = None
        # browser_harness._ipc reads BH_RUNTIME_DIR / BH_TMP_DIR at import
        # time and caches the resolved paths in module globals.  Set the env
        # vars BEFORE any browser_harness import (including the helper bind
        # and ensure_daemon call) so the parent process and the daemon agree
        # on where the socket / pid / log files live.
        os.environ["BH_RUNTIME_DIR"] = str(self._runtime_dir)
        os.environ["BH_TMP_DIR"] = str(self._runtime_dir)
        self._bh = _BrowserHarness(session, self._runtime_dir)

    # --- Context Manager ---

    def __enter__(self):
        return self

    def __exit__(self, *args):
        try:
            self.browser_close()
        except BrowserHarnessError:
            pass
        return False

    # ---------------- Internal helpers ----------------

    @staticmethod
    def _safe_url_for_log(url: str) -> str:
        if not url:
            return ""
        try:
            parts = urlsplit(url)
            query = "&".join(
                f"{name}=<redacted>"
                for name, _v in parse_qsl(parts.query, keep_blank_values=True)
            )
            fragment = "<redacted>" if parts.fragment else ""
            return urlunsplit((parts.scheme, parts.netloc, parts.path, query, fragment))
        except Exception:
            return "<unparseable url>"

    def _require_open(self):
        if not self._opened:
            raise BrowserHarnessError(
                f"No browser open for session '{self.session}'. Call browser_open() first."
            )

    def _start_daemon(self):
        """Start (or reuse) the browser-harness daemon for this session."""
        from browser_harness.admin import ensure_daemon
        env = {
            "BU_NAME": self.session,
            "BU_CDP_URL": f"http://127.0.0.1:{self._cdp_port}",
            "BH_RUNTIME_DIR": str(self._runtime_dir),
            "BH_TMP_DIR": str(self._runtime_dir),
        }
        # ensure_daemon spawns a fresh daemon process with the supplied env merged
        # over os.environ, then verifies it's reachable.  Restarts stale daemons.
        ensure_daemon(name=self.session, env=env)
        logger.debug(
            "_start_daemon: daemon up session=%s cdp_port=%s",
            self.session, self._cdp_port,
        )

    def _stop_daemon(self):
        """Fast daemon shutdown.

        browser_harness.admin.restart_daemon() does a polite shutdown + waits
        up to 15s for the daemon to exit on its own.  Since we're tearing
        Chrome down in the same call anyway, the daemon's WebSocket would
        die regardless — there's nothing to gracefully save.  SIGKILL the
        daemon process directly via its pid file and move on.
        """
        import signal
        from browser_harness import _ipc as ipc
        try:
            pid_path = ipc.pid_path(self.session)
            if pid_path.exists():
                try:
                    pid = int(pid_path.read_text().strip())
                    os.kill(pid, signal.SIGKILL)
                except (ValueError, ProcessLookupError, OSError):
                    pass
                try:
                    pid_path.unlink()
                except FileNotFoundError:
                    pass
            ipc.cleanup_endpoint(self.session)
        except Exception as e:
            logger.debug("_stop_daemon: %s", e)

    def _terminate_chrome(self):
        if self._chrome_proc is None:
            return
        try:
            self._chrome_proc.terminate()
            try:
                self._chrome_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._chrome_proc.kill()
                self._chrome_proc.wait(timeout=5)
        except Exception as e:
            logger.debug("_terminate_chrome: %s", e)
        finally:
            self._chrome_proc = None

    def _request_browser_close(self) -> None:
        """Ask Chrome to exit cleanly before hard-stop teardown.

        Some services only flush updated cookies or local/session storage to
        the persistent profile during a graceful browser shutdown. We request
        that first, then let ``_terminate_chrome`` handle the fallback path.
        """
        if not self._opened:
            return
        try:
            self._bh.h.cdp("Browser.close")
        except Exception as e:
            logger.debug("_request_browser_close: %s", e)
            return

        if self._chrome_proc is None or not hasattr(self._chrome_proc, "wait"):
            return
        try:
            self._chrome_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.debug("_request_browser_close: timed out waiting for Chrome to exit")

    def _list_process_commands(self) -> List[tuple[int, str, str]]:
        """Return `(pid, stat, command)` rows for the local process table."""
        try:
            result = subprocess.run(
                ["ps", "ax", "-o", "pid=,stat=,command="],
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError) as e:
            raise BrowserHarnessError(f"Failed to inspect process table: {e}") from e

        rows: List[tuple[int, str, str]] = []
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split(None, 2)
            try:
                pid = int(parts[0])
            except (IndexError, ValueError) as e:
                raise BrowserHarnessError(
                    f"Failed to parse process-table row: {raw_line!r}"
                ) from e
            stat = parts[1] if len(parts) >= 2 else ""
            command = parts[2] if len(parts) == 3 else ""
            rows.append((pid, stat, command))
        return rows

    def _session_process_pids(self) -> List[int]:
        """Return PIDs for Chrome/browser-harness children using this session's profile."""
        if self._user_data_dir is None:
            return []
        user_data_dir = str(self._user_data_dir)
        pids: List[int] = []
        for pid, stat, command in self._list_process_commands():
            if pid == os.getpid():
                continue
            if stat.startswith("Z"):
                continue
            command_user_data_dir = self._command_user_data_dir(command)
            if command_user_data_dir != user_data_dir:
                continue
            pids.append(pid)
        return pids

    @staticmethod
    def _command_user_data_dir(command: str) -> Optional[str]:
        for pattern in (
            r"(?:^|\s)--user-data-dir=(?P<value>\"[^\"]+\"|'[^']+'|\S+)(?:\s|$)",
            r"(?:^|\s)--user-data-dir\s+(?P<value>\"[^\"]+\"|'[^']+'|\S+)(?:\s|$)",
        ):
            match = re.search(pattern, command)
            if not match:
                continue
            value = match.group("value")
            if value.startswith(("'", '"')) and value.endswith(("'", '"')):
                return value[1:-1]
            return value
        return None

    def _pid_running(self, pid: int) -> bool:
        for current_pid, stat, _command in self._list_process_commands():
            if current_pid == pid:
                return not stat.startswith("Z")
        return False

    def _terminate_session_pid(self, pid: int) -> None:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except OSError as e:
            raise BrowserHarnessError(
                f"Failed to stop stale browser process {pid}: {e}"
            ) from e

        deadline = time.time() + 5
        while time.time() < deadline:
            if not self._pid_running(pid):
                return
            time.sleep(0.1)

        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        except OSError as e:
            raise BrowserHarnessError(
                f"Failed to force-stop stale browser process {pid}: {e}"
            ) from e

        deadline = time.time() + 5
        while time.time() < deadline:
            if not self._pid_running(pid):
                return
            time.sleep(0.1)

        raise BrowserHarnessError(
            f"Stale browser process {pid} for session '{self.session}' did not exit"
        )

    def _cleanup_session_lock_files(self) -> None:
        """Delete stale lock files, but refuse to clobber a live SingletonLock.

        Chrome stores its single-instance guard as a symlink at
        ``SingletonLock`` whose target is ``<hostname>-<pid>``. When that
        PID is still alive, another Chrome process owns the persistent
        profile and starting a second one would corrupt the user data dir.
        Fail fast with the PID and an actionable hint — never delete the
        live lock.

        Unparseable targets are treated as stale (Chrome leaves these
        behind after a crash) and deleted.
        """
        # Resolve user-data-dir for this session. Tests monkeypatch
        # ``service._user_data_dir`` directly with a Path; the attribute
        # may also still be set via ``browser_open`` in real flows.
        ud = self._user_data_dir
        if ud is None:
            return
        if callable(ud):  # legacy test paths
            ud = ud()
        lock_path = ud / "SingletonLock"
        if lock_path.is_symlink():
            target = os.readlink(str(lock_path))
            # Target format: ``<hostname>-<pid>``. Parse PID from the right.
            pid: Optional[int] = None
            if "-" in target:
                _, _, tail = target.rpartition("-")
                try:
                    pid = int(tail)
                except ValueError:
                    pid = None
            if pid is not None and self._pid_running(pid):
                raise BrowserHarnessError(
                    f"Browser session '{self.session}' is held by PID {pid}. "
                    "Finish or kill it before retrying."
                )
            # Stale or unparseable — fall through to delete below.

        for name in (
            "SingletonCookie",
            "SingletonLock",
            "SingletonSocket",
            "DevToolsActivePort",
        ):
            path = ud / name
            if not path.exists() and not path.is_symlink():
                continue
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            except OSError as e:
                raise BrowserHarnessError(
                    f"Failed to remove stale browser lock file {path}: {e}"
                ) from e

    def _cleanup_stale_session(self) -> None:
        """Kill only stale browser-harness/Chrome state for this named session."""
        from browser_harness.admin import restart_daemon

        logger.debug("_cleanup_stale_session: session=%s", self.session)
        restart_daemon(name=self.session)
        for pid in self._session_process_pids():
            logger.debug("_cleanup_stale_session: stopping stale pid=%s", pid)
            self._terminate_session_pid(pid)
        self._cleanup_session_lock_files()

    def _acquire_lifecycle_lock(self) -> None:
        """Acquire the per-session lifecycle lock until close/delete."""
        if self._lifecycle_lock_file is not None:
            return
        self._lifecycle_lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = open(self._lifecycle_lock_path, "a+")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        except Exception:
            lock_file.close()
            raise
        self._lifecycle_lock_file = lock_file

    def _release_lifecycle_lock(self) -> None:
        """Release the per-session lifecycle lock if held by this instance."""
        if self._lifecycle_lock_file is None:
            return
        try:
            fcntl.flock(self._lifecycle_lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            self._lifecycle_lock_file.close()
            self._lifecycle_lock_file = None

    def _close_browser_locked(self) -> None:
        """Close browser and daemon while assuming the lifecycle lock is held."""
        if not self._opened:
            return
        self._request_browser_close()
        self._stop_daemon()
        self._terminate_chrome()
        for pid in self._session_process_pids():
            self._terminate_session_pid(pid)
        self._opened = False
        self._cdp_port = None

    # ---------------- Browser lifecycle ----------------

    def browser_open(
        self,
        url: Optional[str] = None,
        headed: bool = False,
        persistent_profile_dir: Optional[Path] = None,
        user_agent: Optional[str] = None,
        window_size: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Spawn Chrome with the supplied persistent user-data-dir.

        ``persistent_profile_dir`` is required — the caller (config) is the
        sole source of truth for that path; this driver no longer derives
        a path from the daemon-session name.
        """
        logger.debug(
            "browser_open: session=%s url=%s headed=%s",
            self.session, self._safe_url_for_log(url or ""), headed,
        )
        if persistent_profile_dir is None:
            raise BrowserHarnessError(
                "browser_open: persistent_profile_dir is required. "
                "Pass config.get_persistent_profile_dir() from the caller."
            )
        if headed and os.getenv("CLI_TOOL_TEST_NO_HEADED_BROWSER") == "1":
            headed = False
        try:
            self._acquire_lifecycle_lock()

            # Resolve and persist the user-data-dir for this open() so that
            # ``_session_process_pids``, ``_cleanup_session_lock_files``, and
            # ``data_delete`` all agree on a single path.
            self._user_data_dir = Path(persistent_profile_dir)
            self._user_data_dir.mkdir(parents=True, exist_ok=True)

            if self._opened:
                self._close_browser_locked()

            self._cleanup_stale_session()

            # Allocate port + spawn Chrome with the persistent user-data-dir.
            self._cdp_port = _find_free_port()
            user_data_dir = str(self._user_data_dir)
            chrome = os.environ.get("CLI_TOOLS_CHROME_BINARY") or _chrome_binary()

            args = [
                chrome,
                f"--remote-debugging-port={self._cdp_port}",
                f"--user-data-dir={user_data_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=AutomationControlled,Translate",
                "--remote-allow-origins=*",
            ]
            if user_agent:
                args.append(f"--user-agent={user_agent}")
            if window_size:
                args.append(f"--window-size={window_size}")
            if not headed:
                args.append("--headless=new")
            logger.debug("browser_open: spawning chrome args=%s", args)
            launch_args = _chrome_launch_command(chrome, args)
            try:
                self._chrome_proc = subprocess.Popen(
                    launch_args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except OSError as e:
                raise BrowserHarnessError(f"Failed to spawn Chrome: {e}")

            try:
                _wait_for_cdp(self._cdp_port, timeout=self.default_timeout)
            except BrowserHarnessError:
                self._terminate_chrome()
                raise

            # Start the harness daemon bound to this Chrome's CDP endpoint.
            try:
                self._start_daemon()
            except Exception as e:
                self._terminate_chrome()
                raise BrowserHarnessError(f"Failed to start browser-harness daemon: {e}")

            self._opened = True

            # Mask navigator.webdriver everywhere on this page.
            try:
                self._bh.h.cdp(
                    "Page.addScriptToEvaluateOnNewDocument",
                    source="Object.defineProperty(navigator,'webdriver',{get:()=>undefined});",
                )
            except Exception as e:
                logger.debug("browser_open: addScriptToEvaluateOnNewDocument failed: %s", e)

            if url:
                self.page_goto(url)

            return self._page_info()
        except Exception:
            if not self._opened:
                self._release_lifecycle_lock()
            raise

    def browser_close(self) -> Dict[str, Any]:
        try:
            self._close_browser_locked()
            return {"success": True, "message": "Browser closed"}
        finally:
            self._release_lifecycle_lock()

    # ---------------- Page info ----------------

    def _page_info(self) -> Dict[str, Any]:
        if not self._opened:
            return {"url": "", "title": "", "console_errors": 0, "console_warnings": 0}
        try:
            info = self._bh.h.page_info()
        except Exception:
            return {"url": "", "title": "", "console_errors": 0, "console_warnings": 0}
        if isinstance(info, dict) and "dialog" in info:
            return {"url": "", "title": "", "console_errors": 0, "console_warnings": 0}
        return {
            "url": info.get("url", "") if isinstance(info, dict) else "",
            "title": info.get("title", "") if isinstance(info, dict) else "",
            "console_errors": 0,
            "console_warnings": 0,
        }

    @property
    def url(self) -> str:
        try:
            return self._page_info().get("url", "")
        except Exception:
            return ""

    # ---------------- Navigation ----------------

    def page_goto(self, url: str) -> Dict[str, Any]:
        self._require_open()
        try:
            self._bh.h.goto_url(url)
            self._bh.h.wait_for_load(timeout=self.default_timeout)
        except Exception as e:
            raise BrowserHarnessError(f"Failed to navigate to {url}: {e}")
        return self._page_info()

    def goto(self, url: str, wait_until: str = None) -> None:
        self.page_goto(url)

    # ---------------- JavaScript evaluation ----------------

    @staticmethod
    def _wrap_callable_expression(js_code: str, arg: Any) -> str:
        """Callers pass `() => {...}` or `async (x) => {...}` and
        expect the caller to invoke it.  Runtime.evaluate just evaluates the
        expression, which would yield the function reference.  We wrap it in
        a call so the function actually runs and (optionally) receives arg.
        """
        code = js_code.strip()
        looks_like_function = (
            code.startswith("(")
            or code.startswith("async (")
            or code.startswith("async(")
            or code.startswith("function")
            or code.startswith("async function")
        )
        if not looks_like_function:
            return code
        if arg is not None:
            return f"({code})({json.dumps(arg)})"
        return f"({code})()"

    @staticmethod
    def _decode_cdp_runtime_value(payload: Dict[str, Any], expression: str) -> Any:
        if payload.get("exceptionDetails"):
            details = payload["exceptionDetails"]
            text = details.get("text") or "JavaScript evaluation failed"
            raise BrowserHarnessError(f"{text}; expression: {expression[:200]}")

        result = payload.get("result")
        if not isinstance(result, dict):
            return None
        if "value" in result:
            return result["value"]
        if "unserializableValue" in result:
            value = result["unserializableValue"]
            if value == "NaN":
                return float("nan")
            if value == "Infinity":
                return float("inf")
            if value == "-Infinity":
                return float("-inf")
            if value == "-0":
                return -0.0
            return value
        return None

    @staticmethod
    def _find_frame_id_in_tree(frame_tree: Dict[str, Any], url_substr: str) -> Optional[str]:
        frame = frame_tree.get("frame")
        if isinstance(frame, dict) and url_substr in str(frame.get("url", "")):
            frame_id = frame.get("id")
            if isinstance(frame_id, str) and frame_id:
                return frame_id
        for child in frame_tree.get("childFrames", []) or []:
            if not isinstance(child, dict):
                continue
            frame_id = BrowserHarnessService._find_frame_id_in_tree(child, url_substr)
            if frame_id:
                return frame_id
        return None

    def evaluate(self, js: str, arg: Any = None) -> Any:
        self._require_open()
        try:
            wrapped = self._wrap_callable_expression(js, arg)
            return self._bh.h.js(wrapped)
        except Exception as e:
            error_msg = str(e)
            if "undefined" in error_msg.lower() or "null" in error_msg.lower():
                return None
            raise BrowserHarnessError(f"Eval error: {e}")

    def iframe_target(self, url_substr: str) -> Optional[str]:
        """Return the first iframe target or frame id containing ``url_substr``."""
        self._require_open()
        if not url_substr:
            raise BrowserHarnessError("iframe_target: url_substr must be non-empty")
        try:
            target_id = self._bh.h.iframe_target(url_substr)
            if target_id:
                return target_id
            frame_tree = self._bh.h.cdp("Page.getFrameTree")
            if not isinstance(frame_tree, dict) or "frameTree" not in frame_tree:
                return None
            return self._find_frame_id_in_tree(frame_tree["frameTree"], url_substr)
        except Exception as e:
            raise BrowserHarnessError(f"iframe_target error: {e}") from e

    def evaluate_in_iframe(self, url_substr: str, js: str, arg: Any = None) -> Any:
        """Run JS inside the first iframe whose URL contains ``url_substr``."""
        self._require_open()
        helper_target_id = None
        try:
            helper_target_id = self._bh.h.iframe_target(url_substr)
        except Exception:
            helper_target_id = None
        wrapped = self._wrap_callable_expression(js, arg)
        if helper_target_id:
            try:
                return self._bh.h.js(wrapped, target_id=helper_target_id)
            except Exception as e:
                error_msg = str(e)
                if "undefined" in error_msg.lower() or "null" in error_msg.lower():
                    return None
                raise BrowserHarnessError(f"Eval error: {e}") from e

        frame_id = self.iframe_target(url_substr)
        if not frame_id:
            return None
        try:
            world = self._bh.h.cdp(
                "Page.createIsolatedWorld",
                frameId=frame_id,
                worldName="cli-tools-iframe-eval",
            )
            context_id = world.get("executionContextId")
            if not context_id:
                return None
            payload = self._bh.h.cdp(
                "Runtime.evaluate",
                contextId=context_id,
                expression=wrapped,
                returnByValue=True,
                awaitPromise=True,
            )
            return self._decode_cdp_runtime_value(payload, wrapped)
        except Exception as e:
            error_msg = str(e)
            if "undefined" in error_msg.lower() or "null" in error_msg.lower():
                return None
            raise BrowserHarnessError(f"Eval error: {e}") from e

    def page_eval(self, js: str, arg: Any = None) -> Dict[str, Any]:
        """Backward-compatible wrapper for legacy page-eval callers."""
        return {"result": self.evaluate(js, arg)}

    # ---------------- Keyboard ----------------

    def keyboard_press(self, key: str) -> Dict[str, Any]:
        self._require_open()
        # Browser callers may use compound keys like "Control+A" / "Shift+Tab".
        # browser-harness press_key takes a single key + modifiers bitfield.
        mods = 0
        parts = key.split("+")
        last = parts[-1]
        for mod in parts[:-1]:
            m = mod.lower()
            if m in ("alt",):
                mods |= 1
            elif m in ("control", "ctrl"):
                mods |= 2
            elif m in ("meta", "cmd", "command"):
                mods |= 4
            elif m in ("shift",):
                mods |= 8
        self._bh.h.press_key(last, modifiers=mods)
        return self._page_info()

    def type_text(self, text: str) -> Dict[str, Any]:
        self._require_open()
        self._bh.h.type_text(text)
        return self._page_info()

    # ---------------- Cookies ----------------

    def cookie_list(self) -> List[Dict[str, Any]]:
        """Return all cookies from the open browser via CDP.

        Uses ``Network.getAllCookies`` (returns every cookie in the
        browser's network stack, across all origins) rather than the
        URL-scoped ``Network.getCookies`` — the persistent profile holds
        cookies for many hosts (the auth domain, the API domain, the
        CDN, etc.), and the current page URL is irrelevant to whether
        the consumer needs them. Failures propagate (no silent recovery
        — fail loudly per project policy).
        """
        if not self._opened:
            raise BrowserHarnessError(
                f"No browser open for session '{self.session}'. "
                f"Call browser_open() first."
            )
        r = self._bh.h.cdp("Network.getAllCookies")
        if not isinstance(r, dict):
            raise BrowserHarnessError(
                f"CDP Network.getAllCookies returned unexpected payload: {r!r}"
            )
        return r.get("cookies", [])

    # ---------------- Storage ----------------

    def localstorage_list(self) -> List[Dict[str, str]]:
        self._require_open()
        try:
            result = self.evaluate(
                "() => Object.entries(localStorage).map(([key, value]) => ({key, value}))"
            )
            return result or []
        except Exception:
            return []

    # ---------------- Data ----------------

    def data_delete(self) -> Dict[str, Any]:
        """Wipe the persistent user-data-dir for this session.

        Closes the browser (if open) and rmtree's the user-data-dir. Both
        operations propagate failures — no silent recovery. The caller
        owns turning those failures into actionable error messages.
        """
        import shutil
        try:
            self._acquire_lifecycle_lock()
            self._close_browser_locked()
            ud = self._user_data_dir
            if ud is not None and ud.exists():
                shutil.rmtree(ud)
            return {"success": True, "message": "Session data deleted"}
        finally:
            self._release_lifecycle_lock()

    # ---------------- Selectors ----------------

    def locator(self, selector: str) -> _ServiceLocator:
        return _ServiceLocator(self, selector)

    def get_by_role(self, role: str, *, name=None) -> _ServiceLocator:
        return _ServiceLocator.from_role(self, role, name)

    def get_by_placeholder(self, text: str) -> _ServiceLocator:
        return _ServiceLocator(self, f'[placeholder="{text}"]')

    # ---------------- Waiting ----------------

    def wait_for_timeout(self, ms: int) -> None:
        time.sleep(ms / 1000)

    def drain_events(self) -> List[Dict[str, Any]]:
        """Return and clear buffered CDP events for this browser session."""
        self._require_open()
        events = self._bh.h.drain_events()
        if not isinstance(events, list):
            raise BrowserHarnessError(
                f"drain_events returned unexpected payload: {events!r}"
            )
        return events

    def wait_for_network_idle(self, timeout: float = 10.0, idle_ms: int = 500) -> bool:
        """Wait until the active tab has no in-flight network activity."""
        self._require_open()
        return bool(self._bh.h.wait_for_network_idle(timeout=timeout, idle_ms=idle_ms))

    def wait_for_selector(
        self,
        selector: str,
        *,
        state: str = "visible",
        timeout: int = 30000,
    ) -> "_ServiceElement":
        """Wait for an element matching ``selector`` to reach ``state``.

        Playwright-compatible polling primitive. Returns the resolved first
        matching element (a ``_ServiceElement``) when the state is reached.
        Raises :class:`BrowserHarnessError` on timeout.

        Args:
            selector: CSS selector to poll for.
            state: One of ``"attached"``, ``"visible"``, ``"hidden"``, or
                ``"detached"``. Default ``"visible"``.
            timeout: Maximum time to wait, in milliseconds. Default 30000.

        Returns:
            ``_ServiceElement`` for the first matching element, or ``None`` when
            the awaited state is ``"hidden"`` or ``"detached"``.

        Raises:
            BrowserHarnessError: If the awaited state is not reached within
                ``timeout`` ms, or if ``state`` is not one of the supported
                values.
        """
        valid_states = ("attached", "visible", "hidden", "detached")
        if state not in valid_states:
            raise BrowserHarnessError(
                f"wait_for_selector: state must be one of {valid_states}, got {state!r}"
            )
        self._require_open()

        # Import lazily to avoid the circular import driver <-> _elements.
        from ._elements import _ServiceElement
        from ._js_fragments import _VISIBILITY_JS

        # Poll via evaluate() so we re-use the existing transport. Each iteration
        # asks the page directly — no JS-side setTimeout loop that the harness
        # would have to keep alive across calls.
        attached_js = (
            f"() => !!document.querySelector({json.dumps(selector)})"
        )
        visible_js = (
            "() => { const el = document.querySelector("
            f"{json.dumps(selector)}); if (!el) return false; "
            f"{_VISIBILITY_JS} }}"
        )

        deadline = time.monotonic() + (timeout / 1000.0)
        # Poll roughly every 100ms; Playwright uses similar fast polling.
        poll_interval = 0.1

        while True:
            if state == "attached":
                ok = bool(self.evaluate(attached_js))
                if ok:
                    return _ServiceElement(self, css=selector)
            elif state == "visible":
                ok = bool(self.evaluate(visible_js))
                if ok:
                    return _ServiceElement(self, css=selector)
            elif state == "detached":
                ok = not bool(self.evaluate(attached_js))
                if ok:
                    return None
            else:  # "hidden"
                ok = not bool(self.evaluate(visible_js))
                if ok:
                    return None

            if time.monotonic() >= deadline:
                raise BrowserHarnessError(
                    f"wait_for_selector: timed out after {timeout}ms waiting "
                    f"for selector {selector!r} to be {state}"
                )
            time.sleep(poll_interval)

    def query_selector(self, selector: str) -> Optional["_ServiceElement"]:
        """Return the first element matching ``selector``, or ``None``.

        Playwright-compatible synchronous query. Does not wait. Returns a
        ``_ServiceElement`` when the selector matches at least one element,
        and ``None`` when the page has no match. Methods on the returned
        element (``click``, ``fill``, etc.) evaluate against the live DOM.
        """
        self._require_open()
        from ._elements import _ServiceElement
        present = self.evaluate(
            f"() => !!document.querySelector({json.dumps(selector)})"
        )
        if not present:
            return None
        return _ServiceElement(self, css=selector)

    def aria_snapshot(self, selector: str = "body", *, timeout: int = 5000) -> str:
        """Capture a Playwright-style accessibility snapshot from the live page.

        browser-harness owns the running Chrome instance. To preserve the
        exact loaded page state, attach to that same browser over CDP and
        call Playwright's ``aria_snapshot()`` against the matching live page.
        """
        self._require_open()
        if self._cdp_port is None:
            raise BrowserHarnessError(
                f"No CDP port available for session '{self.session}'."
            )

        current_url = self.url
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{self._cdp_port}"
                )
                try:
                    if not browser.contexts:
                        raise BrowserHarnessError(
                            "CDP browser connection returned no contexts."
                        )
                    live_pages = browser.contexts[0].pages
                    if not live_pages:
                        raise BrowserHarnessError(
                            "CDP browser connection returned no pages."
                        )
                    raw_page = next(
                        (
                            candidate
                            for candidate in live_pages
                            if candidate.url == current_url
                        ),
                        live_pages[0],
                    )
                    return raw_page.locator(selector).aria_snapshot(timeout=timeout)
                finally:
                    browser.close()
        except BrowserHarnessError:
            raise
        except Exception as e:
            raise BrowserHarnessError(
                f"Failed to capture aria snapshot: {e}"
            ) from e
