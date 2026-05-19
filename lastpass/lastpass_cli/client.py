"""Lastpass wrapper client using subprocess to call underlying CLI."""
import logging
import os
import random
import signal
import subprocess
import sys
import time
from typing import Dict, List, Optional, Any, Union

from cli_tools_shared.activity_log import get_activity_logger

# Debug logger — enabled with DEBUG=1 env var
debug = logging.getLogger("lastpass.debug")
if os.environ.get("DEBUG") == "1":
    logging.basicConfig(level=logging.DEBUG, format="[DEBUG] %(message)s", stream=sys.stderr)
else:
    debug.addHandler(logging.NullHandler())

from .config import get_config
from .parsers import parse_cli_output, OutputFormat

activity = get_activity_logger("lastpass")

# Known crash patterns in lpass (OpenSSL/agent bugs)
MALLOC_ERROR_PATTERNS = [
    "malloc:",
    "pointer being freed was not allocated",
    "Heap corruption detected",
]
# Signal-based exit codes: SIGABRT=-6/134, SIGSEGV=-11/139, SIGBUS=-10/138
CRASH_EXIT_CODES = {-6, -10, -11, 134, 138, 139}
LPASS_DIR = os.path.expanduser("~/.lpass")
AGENT_SOCK_PATH = os.path.join(LPASS_DIR, "agent.sock")
PLAINTEXT_KEY_PATH = os.path.join(LPASS_DIR, "plaintext_key")


class ClientError(Exception):
    """Custom exception for Lastpass wrapper errors."""
    pass


class LastpassClient:
    """Wrapper client for lpass CLI.

    Calls the underlying CLI via subprocess and parses/transforms output
    to standard JSON format for the wrapper CLI.
    """

    def __init__(self, config=None):
        """Initialize Lastpass wrapper client."""
        self.config = config or get_config()

        if not self.config.is_cli_available():
            raise ClientError(
                f"Underlying CLI '{self.config.cli_command}' not found. "
                f"Please install it first."
            )

    def _is_crash(self, result: subprocess.CompletedProcess) -> bool:
        """Check if the result indicates a crash (malloc error, segfault, etc.)."""
        if result.returncode in CRASH_EXIT_CODES:
            return True
        stderr = result.stderr or ""
        return any(pattern in stderr for pattern in MALLOC_ERROR_PATTERNS)

    @staticmethod
    def _kill_agent():
        """Kill the lpass agent process and remove its socket.

        Stale agents (e.g. linked against an old OpenSSL) are a common
        cause of malloc crashes. Killing the agent lets lpass spawn a
        fresh one from the current binary.
        """
        try:
            subprocess.run(["pkill", "-f", "lpass"], capture_output=True, timeout=5)
        except Exception:
            pass
        try:
            if os.path.exists(AGENT_SOCK_PATH):
                os.remove(AGENT_SOCK_PATH)
        except OSError:
            pass

    @staticmethod
    def _agent_disabled_env() -> Dict[str, str]:
        """Return environment with LPASS_AGENT_DISABLE=1.

        The lpass agent has a known crash bug with OpenSSL 3.6.x on macOS.
        Disabling it forces lpass to read the decryption key from the
        plaintext_key file on disk (created by login --plaintext-key).
        """
        return {**os.environ, "LPASS_AGENT_DISABLE": "1"}

    def _run_command(
        self,
        args: List[str],
        input_text: Optional[str] = None,
        timeout: int = 60,
        check: bool = True,
        max_retries: int = 3,
    ) -> subprocess.CompletedProcess:
        """
        Run a command on the underlying CLI.

        On crash, retries with escalating recovery:
          1. Simple retry (transient crash)
          2. Kill stale agent processes and retry

        Args:
            args: Command arguments (without the CLI command itself)
            input_text: Optional text to pass to stdin
            timeout: Command timeout in seconds
            check: If True, raise ClientError on non-zero exit
            max_retries: Maximum retries on crash

        Returns:
            CompletedProcess with stdout, stderr, and returncode

        Raises:
            ClientError: If command fails and check=True
        """
        cmd = [self.config.get_cli_executable()] + args
        last_result = None
        env = self._agent_disabled_env()
        activity.info("Running command: %s", " ".join(args))
        debug.debug("_run_command: %s", " ".join(cmd))
        debug.debug("_run_command env: LPASS_AGENT_DISABLE=%s", env.get("LPASS_AGENT_DISABLE"))
        debug.debug("_run_command plaintext_key exists=%s", os.path.exists(PLAINTEXT_KEY_PATH))

        for attempt in range(max_retries):
            try:
                result = subprocess.run(
                    cmd,
                    input=input_text,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env=env,
                )
                last_result = result

                debug.debug("_run_command attempt %d: rc=%d stdout=%r stderr=%r",
                           attempt, result.returncode, result.stdout[:200], result.stderr[:200])
                crashed = self._is_crash(result)

                if crashed:
                    if attempt < max_retries - 1:
                        self._kill_agent()
                        # Exponential backoff with jitter
                        base_delay = 0.5 * (2 ** attempt)
                        jitter = random.uniform(0, base_delay * 0.5)
                        time.sleep(base_delay + jitter)
                        continue
                    # All retries exhausted
                    raise ClientError(
                        f"{self.config.cli_command} crashed (exit {result.returncode}). "
                        f"Tried {max_retries} times. This is a known lpass bug with "
                        f"OpenSSL. Try: brew reinstall --build-from-source lastpass-cli"
                    )

                # Check for missing decryption key (plaintext_key file not found)
                if result.returncode != 0:
                    stderr = result.stderr.strip()
                    if "Could not find decryption key" in stderr:
                        raise ClientError(
                            "No decryption key found. Re-login required: "
                            "lastpass auth login --force"
                        )

                if check and result.returncode != 0:
                    error_msg = result.stderr.strip() or result.stdout.strip() or "Command failed"
                    raise ClientError(f"{self.config.cli_command} error: {error_msg}")

                return result

            except subprocess.TimeoutExpired:
                raise ClientError(f"Command timed out after {timeout} seconds")
            except FileNotFoundError:
                raise ClientError(f"CLI '{self.config.cli_command}' not found in PATH")
            except Exception as e:
                if isinstance(e, ClientError):
                    raise
                raise ClientError(f"Failed to run command: {e}")

        # Should not reach here, but just in case
        if last_result:
            return last_result
        raise ClientError("Command failed after all retries")

    def _parse_output(
        self,
        output: str,
        format: OutputFormat = OutputFormat.AUTO,
    ) -> Union[Dict, List, str]:
        """
        Parse CLI output into structured data.

        Args:
            output: Raw CLI output string
            format: Expected output format (auto-detect by default)

        Returns:
            Parsed data (dict, list, or string)
        """
        return parse_cli_output(output, format)

    # ==================== Auth Methods ====================
    # Customized for lpass CLI

    def auth_login(self, email: Optional[str] = None, password: Optional[str] = None,
                   force: bool = False, **kwargs) -> Dict[str, Any]:
        """
        Login to LastPass via lpass CLI.

        Uses LPASS_DISABLE_PINENTRY=1 to pipe the password via stdin,
        bypassing lpass's buggy pinentry code that causes malloc crashes
        on macOS. Also uses --plaintext-key to persist the decryption key
        to disk so LPASS_AGENT_DISABLE=1 works for subsequent commands.

        Args:
            email: LastPass account email (required for lpass login)
            password: Master password (piped via stdin)
            force: If True, force re-authentication even if already logged in
        """
        activity.info("Login attempt for email=%s force=%s", email, force)
        debug.debug("auth_login called: email=%s, force=%s, password_len=%s",
                     email, force, len(password) if password else 0)
        if not email:
            return {
                "success": False,
                "message": "Email is required for lpass login.",
            }

        # Force re-auth by logging out first
        if force:
            env_logout = self._agent_disabled_env()
            debug.debug("Logging out first: lpass logout --force")
            logout_result = subprocess.run(
                [self.config.get_cli_executable(), "logout", "--force"],
                capture_output=True, text=True, timeout=30, env=env_logout,
            )
            debug.debug("Logout result: rc=%d stdout=%r stderr=%r",
                        logout_result.returncode, logout_result.stdout.strip(), logout_result.stderr.strip())
            self._kill_agent()
            debug.debug("Agent killed")

        args = ["login", "--plaintext-key", "--force", email]
        cmd = [self.config.get_cli_executable()] + args
        # Disable pinentry (pipe password via stdin) AND disable agent
        env = self._agent_disabled_env()
        env["LPASS_DISABLE_PINENTRY"] = "1"

        debug.debug("Login command: %s", " ".join(cmd))
        debug.debug("Env overrides: LPASS_AGENT_DISABLE=%s LPASS_DISABLE_PINENTRY=%s",
                     env.get("LPASS_AGENT_DISABLE"), env.get("LPASS_DISABLE_PINENTRY"))
        debug.debug("LPASS_HOME=%s", env.get("LPASS_HOME", "(not set)"))
        debug.debug("plaintext_key path: %s (exists=%s)", PLAINTEXT_KEY_PATH, os.path.exists(PLAINTEXT_KEY_PATH))
        debug.debug("agent.sock path: %s (exists=%s)", AGENT_SOCK_PATH, os.path.exists(AGENT_SOCK_PATH))
        debug.debug("~/.lpass contents: %s", os.listdir(LPASS_DIR) if os.path.exists(LPASS_DIR) else "(missing)")

        for attempt in range(3):
            debug.debug("--- Attempt %d/3 ---", attempt + 1)
            try:
                result = subprocess.run(
                    cmd, input=password, capture_output=True,
                    text=True, timeout=120, env=env,
                )
            except subprocess.TimeoutExpired:
                debug.debug("Attempt %d: TIMEOUT", attempt + 1)
                raise ClientError("Login timed out after 120 seconds")
            except FileNotFoundError:
                debug.debug("Attempt %d: lpass binary not found", attempt + 1)
                raise ClientError(f"CLI '{self.config.cli_command}' not found in PATH")

            debug.debug("Attempt %d: rc=%d", attempt + 1, result.returncode)
            debug.debug("Attempt %d: stdout=%r", attempt + 1, result.stdout.strip())
            debug.debug("Attempt %d: stderr=%r", attempt + 1, result.stderr.strip())
            debug.debug("Attempt %d: plaintext_key exists=%s", attempt + 1, os.path.exists(PLAINTEXT_KEY_PATH))
            debug.debug("Attempt %d: agent.sock exists=%s", attempt + 1, os.path.exists(AGENT_SOCK_PATH))

            if result.returncode == 0:
                if os.path.exists(PLAINTEXT_KEY_PATH):
                    activity.info("Login successful for %s", email)
                    debug.debug("SUCCESS: plaintext_key written")
                    return {"success": True, "message": "Login successful"}
                # Key not written — retry
                debug.debug("rc=0 but NO plaintext_key — retrying")
                activity.warning("Login OK but plaintext_key missing, retry %d", attempt)
                self._kill_agent()
                time.sleep(0.5)
                continue

            # Crash — retry
            if result.returncode in CRASH_EXIT_CODES and attempt < 2:
                debug.debug("CRASH (exit %d in CRASH_EXIT_CODES) — killing agent and retrying",
                           result.returncode)
                activity.warning("Login crashed (exit %d), retry %d", result.returncode, attempt)
                self._kill_agent()
                time.sleep(0.5)
                continue

            # Real failure (wrong password, etc.)
            debug.debug("REAL FAILURE (exit %d, not in CRASH_EXIT_CODES or final attempt)",
                       result.returncode)
            stderr = result.stderr.strip()
            break

        activity.warning("Login failed for %s (exit code %s)", email, result.returncode)
        msg = stderr if stderr else f"exit code {result.returncode}"
        debug.debug("Final failure message: %s", msg)
        return {"success": False, "message": f"Login failed: {msg}"}

    def auth_logout(self, force: bool = False) -> Dict[str, Any]:
        """
        Logout from LastPass via lpass CLI.

        Args:
            force: If True, force logout without confirmation
        """
        args = ["logout"]
        if force:
            args.append("--force")

        result = self._run_command(args, check=False)

        return {
            "success": result.returncode == 0,
            "message": result.stdout.strip() if result.returncode == 0 else result.stderr.strip(),
        }

    def auth_status(self) -> Dict[str, Any]:
        """
        Check LastPass authentication status.

        First checks lpass status, then verifies with an actual API call
        (lpass ls) to confirm the session is valid.
        """
        import re
        activity.info("Checking auth status")

        result = self._run_command(["status"], check=False)
        output = result.stdout.strip()
        status_says_logged_in = result.returncode == 0 and "Logged in as" in output

        # Extract email from status output
        email = None
        if status_says_logged_in:
            match = re.search(r"Logged in as (.+)\.", output)
            if match:
                email = match.group(1)

        # Verify with actual API call - lpass status can report "Logged in"
        # even when the session is stale and can't fetch data
        authenticated = False
        if status_says_logged_in:
            verify_result = self._run_command(["ls"], check=False, max_retries=2)
            authenticated = verify_result.returncode == 0

        error_msg = None
        if status_says_logged_in and not authenticated:
            error_msg = "Session appears stale - lpass reports logged in but cannot fetch vault data. Re-login required."
        elif not status_says_logged_in:
            error_msg = result.stderr.strip() or output

        return {
            "authenticated": authenticated,
            "email": email,
            "cli_command": self.config.cli_command,
            "cli_available": True,
            "cli_version": self.config.get_cli_version(),
            "output": output if authenticated else None,
            "error": error_msg,
        }

    # ==================== Vault Methods ====================
    # LastPass vault operations

    def list_items(
        self,
        group: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[Dict]:
        """
        List vault entries from LastPass.

        Args:
            group: Optional folder/group to list (e.g., "Work" or "Work/Servers")
            category: Optional LastPass item category/note type (e.g., "Credit Card")

        Returns:
            List of vault entries with id, name, and group
        """
        activity.info("Listing items group=%s category=%s", group, category)
        args = ["ls"]
        if group:
            args.append(group)

        result = self._run_command(args)
        items = self._parse_lpass_ls(result.stdout)
        if category is not None:
            items = self._filter_items_by_category(items, category)
        return items

    @staticmethod
    def _normalize_category(category: str) -> str:
        """Normalize category names to the lpass secure-note NoteType value."""
        value = category.strip().casefold()
        aliases = {
            "payment card": "credit card",
            "payment cards": "credit card",
            "credit cards": "credit card",
        }
        return aliases.get(value, value)

    def _get_item_category(self, item_id: str) -> str:
        """Fetch a vault item's LastPass category without reading its password."""
        result = self._run_command(["show", "--field=NoteType", item_id], check=False)
        if result.returncode == 0:
            return result.stdout.strip()
        if "Could not find specified field 'NoteType'" in result.stderr:
            return ""
        error_msg = result.stderr.strip() or result.stdout.strip() or "Command failed"
        raise ClientError(f"{self.config.cli_command} error: {error_msg}")

    def _filter_items_by_category(self, items: List[Dict], category: str) -> List[Dict]:
        """Filter entries by LastPass category/note type."""
        expected = self._normalize_category(category)
        matches = []
        for item in items:
            if item.get("is_folder"):
                continue
            actual = self._get_item_category(item["id"])
            if self._normalize_category(actual) == expected:
                item["category"] = actual
                matches.append(item)
        return matches

    def get_item(self, item_id: str, show_password: bool = False) -> Dict:
        """
        Get a vault entry's details.

        Args:
            item_id: Entry ID or unique name
            show_password: If True, include password in output

        Returns:
            Entry details as dictionary
        """
        activity.info("Getting item %s", item_id)
        args = ["show", item_id]

        result = self._run_command(args)
        parsed = self._parse_lpass_show(result.stdout)

        # Optionally mask password
        if not show_password and "Password" in parsed:
            parsed["Password"] = "********"

        return parsed

    def get_password(self, item_id: str) -> str:
        """
        Get just the password for an entry.

        Args:
            item_id: Entry ID or unique name

        Returns:
            The password string
        """
        args = ["show", "--password", item_id]
        result = self._run_command(args)
        return result.stdout.strip()

    def get_username(self, item_id: str) -> str:
        """
        Get just the username for an entry.

        Args:
            item_id: Entry ID or unique name

        Returns:
            The username string
        """
        args = ["show", "--username", item_id]
        result = self._run_command(args)
        return result.stdout.strip()

    def create_item(
        self,
        name: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        url: Optional[str] = None,
        notes: Optional[str] = None,
        group: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new vault entry.

        Args:
            name: Entry name
            username: Username/email
            password: Password
            url: URL
            notes: Notes
            group: Folder/group (prepended to name as Group/Name)

        Returns:
            Result with success status
        """
        full_name = f"{group}/{name}" if group else name
        activity.info("Creating item: %s", full_name)

        # Build stdin payload for --non-interactive
        lines = []
        if username:
            lines.append(f"Username: {username}")
        if password:
            lines.append(f"Password: {password}")
        if url:
            lines.append(f"URL: {url}")
        if notes:
            lines.append(f"Notes: {notes}")
        stdin_data = "\n".join(lines) + "\n" if lines else "\n"

        args = ["add", "--non-interactive", "--sync=now", full_name]
        result = self._run_command(args, input_text=stdin_data)
        return {"success": True, "message": f"Created entry '{full_name}'"}

    def update_item(
        self,
        item_id: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        url: Optional[str] = None,
        notes: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update an existing vault entry.

        Args:
            item_id: Entry ID or unique name
            username: New username
            password: New password
            url: New URL
            notes: New notes
            name: New name

        Returns:
            Result with success status
        """
        activity.info("Updating item: %s", item_id)
        updated_fields = []

        field_map = {
            "username": username,
            "password": password,
            "url": url,
            "notes": notes,
            "name": name,
        }

        for field, value in field_map.items():
            if value is not None:
                args = ["edit", "--non-interactive", f"--{field}", item_id]
                self._run_command(args, input_text=value + "\n")
                updated_fields.append(field)

        if not updated_fields:
            return {"success": False, "message": "No fields to update"}

        return {"success": True, "message": f"Updated {', '.join(updated_fields)} for '{item_id}'"}

    def delete_item(self, item_id: str) -> Dict[str, Any]:
        """
        Delete a vault entry.

        Args:
            item_id: Entry ID or unique name

        Returns:
            Result with success status
        """
        activity.info("Deleting item: %s", item_id)
        args = ["rm", "--sync=now", item_id]
        self._run_command(args)
        return {"success": True, "message": f"Deleted entry '{item_id}'"}

    def generate_password(
        self,
        name: str,
        length: int = 20,
        username: Optional[str] = None,
        url: Optional[str] = None,
        no_symbols: bool = False,
    ) -> Dict[str, Any]:
        """
        Generate a random password for a new or existing entry.

        Args:
            name: Entry name or ID
            length: Password length
            username: Optional username
            url: Optional URL
            no_symbols: If True, omit symbols

        Returns:
            Result with generated password
        """
        activity.info("Generating password for: %s (length=%d)", name, length)
        args = ["generate", "--sync=now"]
        if username:
            args.extend([f"--username={username}"])
        if url:
            args.extend([f"--url={url}"])
        if no_symbols:
            args.append("--no-symbols")
        args.extend([name, str(length)])

        result = self._run_command(args)
        return {
            "success": True,
            "password": result.stdout.strip(),
            "message": f"Generated {length}-char password for '{name}'",
        }

    def sync(self) -> Dict[str, Any]:
        """
        Sync vault with LastPass servers.

        Returns:
            Sync result
        """
        result = self._run_command(["sync"], check=False)
        return {
            "success": result.returncode == 0,
            "message": result.stdout.strip() or result.stderr.strip(),
        }

    # ==================== Output Parsers ====================

    def _parse_lpass_ls(self, output: str) -> List[Dict]:
        """
        Parse lpass ls output.

        Format: "Group/Name [id: 1234567890123456789]"
        """
        import re
        items = []
        pattern = r'^(.+?)\s+\[id:\s*(\d+)\]$'

        for line in output.strip().split('\n'):
            line = line.strip()
            if not line:
                continue

            match = re.match(pattern, line)
            if match:
                full_path = match.group(1).strip()
                item_id = match.group(2)

                if full_path.endswith("/"):
                    items.append({
                        "id": item_id,
                        "name": full_path.rstrip("/"),
                        "group": "",
                        "full_path": full_path,
                        "is_folder": True,
                    })
                    continue

                # Split path into group and name
                if '/' in full_path:
                    parts = full_path.rsplit('/', 1)
                    group = parts[0]
                    name = parts[1]
                else:
                    group = ""
                    name = full_path

                items.append({
                    "id": item_id,
                    "name": name,
                    "group": group,
                    "full_path": full_path,
                })
            elif line and not line.startswith('(none)'):
                # Folder line (no ID)
                items.append({
                    "id": "",
                    "name": line,
                    "group": "",
                    "full_path": line,
                    "is_folder": True,
                })

        return items

    def _parse_lpass_show(self, output: str) -> Dict:
        """
        Parse lpass show output.

        Format:
            Name: EntryName
            URL: https://example.com
            Username: myuser
            Password: secret
            Notes: Some notes here
        """
        result = {}
        current_key = None
        current_value = []

        for line in output.strip().split('\n'):
            if ': ' in line and not line.startswith(' '):
                # Save previous key-value if exists
                if current_key:
                    result[current_key] = '\n'.join(current_value).strip()

                # Parse new key-value
                key, _, value = line.partition(': ')
                current_key = key.strip()
                current_value = [value]
            elif current_key:
                # Continuation of multiline value (like Notes)
                current_value.append(line)

        # Save last key-value
        if current_key:
            result[current_key] = '\n'.join(current_value).strip()

        return result


# Module-level client instance - singleton pattern
_client: Optional[LastpassClient] = None


def get_client() -> LastpassClient:
    """Get or create the global Lastpass client instance."""
    global _client
    if _client is None:
        _client = LastpassClient()
    return _client
