"""Browser automation CLI validation tests.

These tests verify that browser automation CLIs use the BrowserAutomation
service from cli_tools_shared for browser session management.

Tests validate:
1. config.py extends BaseConfig with get_browser() accessor
2. browser.py defines a BrowserAutomation subclass with session hooks
3. client.py uses the BrowserAutomation subclass (not raw subprocess)
4. No direct Playwright auth logic outside browser.py (must delegate to BrowserAutomation)
5. No custom is_logged_in/is_authenticated — must use base class is_authenticated() via hooks
6. No direct browser-binary subprocess calls (must go through cli_tools_shared BrowserHarnessService)
7. browser_harness module is importable in the CLI's uv tool venv
"""
import re
import subprocess
from pathlib import Path

import pytest

from cli_test_utils import get_uv_tool_venv_dir


def _get_pkg_dir(cli_dir: Path, cli_name: str) -> Path:
    """Get the CLI package directory."""
    pkg_name = cli_name.replace("-", "_") + "_cli"
    return cli_dir / pkg_name


# ==================== Config Pattern ====================


def test_browser_cli_config_uses_base_config(cli_name, cli_dir, test_config, command_filter, is_browser_cli):
    """config.py must extend BaseConfig for profile-aware env loading."""
    if command_filter:
        pytest.skip("Skipping browser automation tests (command filter active)")
    if not is_browser_cli:
        pytest.skip(f"{cli_name} is not a browser automation CLI")

    pkg_dir = _get_pkg_dir(cli_dir, cli_name)
    config_file = pkg_dir / "config.py"

    if not config_file.exists():
        pytest.fail(f"config.py not found at {config_file}")

    content = config_file.read_text()

    assert "BaseConfig" in content, (
        f"'{cli_name}' config.py must extend BaseConfig from cli_tools_shared. "
        f"Fix: Import BaseConfig and make Config(BaseConfig) with CREDENTIAL_TYPES and tool_dir."
    )


def test_browser_cli_config_has_get_browser(cli_name, cli_dir, test_config, command_filter, is_browser_cli):
    """config.py must have get_browser() to provide access to the BrowserAutomation subclass."""
    if command_filter:
        pytest.skip("Skipping browser automation tests (command filter active)")
    if not is_browser_cli:
        pytest.skip(f"{cli_name} is not a browser automation CLI")

    pkg_dir = _get_pkg_dir(cli_dir, cli_name)
    config_file = pkg_dir / "config.py"

    if not config_file.exists():
        pytest.fail(f"config.py not found at {config_file}")

    content = config_file.read_text()

    assert "get_browser" in content, (
        f"'{cli_name}' config.py must implement get_browser() returning the BrowserAutomation subclass. "
        f"Fix: Add 'def get_browser(self): return MyBrowser(self)' to Config."
    )


# ==================== Browser Automation Subclass ====================


def test_browser_cli_has_browser_automation_subclass(cli_name, cli_dir, test_config, command_filter, is_browser_cli):
    """browser.py (preferred) or config.py must define a BrowserAutomation subclass."""
    if command_filter:
        pytest.skip("Skipping browser automation tests (command filter active)")
    if not is_browser_cli:
        pytest.skip(f"{cli_name} is not a browser automation CLI")

    pkg_dir = _get_pkg_dir(cli_dir, cli_name)
    browser_file = pkg_dir / "browser.py"
    config_file = pkg_dir / "config.py"

    # Prefer browser.py, fall back to config.py
    if browser_file.exists():
        content = browser_file.read_text()
        location = "browser.py"
    elif config_file.exists():
        content = config_file.read_text()
        location = "config.py"
    else:
        pytest.fail(
            f"'{cli_name}' has neither browser.py nor config.py. "
            f"Fix: Create browser.py with a BrowserAutomation subclass defining "
            f"LOGIN_URL, AUTH_CHECK_URL, AUTH_URL_PATTERN, SESSION_NAME."
        )

    assert "BrowserAutomation" in content, (
        f"'{cli_name}' {location} must define a BrowserAutomation subclass. "
        f"Fix: Import BrowserAutomation from cli_tools_shared.auth and "
        f"create a subclass with LOGIN_URL, AUTH_CHECK_URL, AUTH_URL_PATTERN, SESSION_NAME."
    )


# ==================== Client Pattern ====================


def test_browser_cli_client_uses_browser_automation(cli_name, cli_dir, test_config, command_filter, is_browser_cli):
    """client.py must use BrowserAutomation for browser management (not raw subprocess)."""
    if command_filter:
        pytest.skip("Skipping browser automation tests (command filter active)")
    if not is_browser_cli:
        pytest.skip(f"{cli_name} is not a browser automation CLI")

    pkg_dir = _get_pkg_dir(cli_dir, cli_name)
    client_file = pkg_dir / "client.py"

    if not client_file.exists():
        pytest.fail(f"client.py not found at {client_file}")

    content = client_file.read_text()

    # Client should import the BrowserAutomation subclass from config or browser
    has_browser_import = (
        "BrowserAutomation" in content
        or "Browser(" in content  # e.g., BrickfreedomBrowser(
        or "get_browser" in content
    )
    assert has_browser_import, (
        f"'{cli_name}' client.py must use a BrowserAutomation subclass for browser management. "
        f"Fix: Import the BrowserAutomation subclass from browser.py and use its get_page()/close() methods."
    )
    assert "BrowserService" not in content, (
        f"'{cli_name}' client.py must NOT reference BrowserService (old pattern). "
        f"Fix: Replace BrowserService with BrowserAutomation subclass from browser.py."
    )


# ==================== Auth Delegation ====================


_FORBIDDEN_PATTERNS = [
    (r"from playwright\.(sync|async)_api import", "Raw Playwright SDK import (use BrowserAutomation instead)"),
    (r"(sync|async)_playwright\(\)", "Direct Playwright context manager (use BrowserAutomation instead)"),
    (r"from browser_harness import", "Raw browser-harness import outside browser.py (use BrowserAutomation instead)"),
    (r"launch_persistent_context", "Direct browser context creation"),
    (r"def (login|authenticate|create_session)\b", "Custom auth function"),
]


def test_browser_cli_no_direct_browser_auth(cli_name, cli_dir, test_config, command_filter, is_browser_cli):
    """Browser CLIs must delegate auth to BrowserAutomation, not handle it directly."""
    if command_filter:
        pytest.skip("Skipping browser automation tests (command filter active)")
    if not is_browser_cli:
        pytest.skip(f"{cli_name} is not a browser automation CLI")

    pkg_dir = _get_pkg_dir(cli_dir, cli_name)
    excluded_files = {"browser.py", "config.py"}
    violations = []

    for py_file in pkg_dir.rglob("*.py"):
        if py_file.name in excluded_files or "__pycache__" in py_file.parts:
            continue

        lines = py_file.read_text().splitlines()
        rel_path = py_file.relative_to(cli_dir)

        for line_num, line in enumerate(lines, start=1):
            for pattern, description in _FORBIDDEN_PATTERNS:
                if re.search(pattern, line):
                    violations.append((str(rel_path), line_num, description))

    assert not violations, (
        f"'{cli_name}' has direct browser auth logic that should be delegated to "
        f"BrowserAutomation in browser.py.\n"
        f"Violations:\n"
        + "\n".join(f"  {f}:{ln} — {desc}" for f, ln, desc in violations)
        + "\n\nFix: Move all browser auth logic into the BrowserAutomation subclass in browser.py. "
        "Other files should only call get_browser().get_page() / .close()."
    )


# ==================== Auth State Detection ====================

# Patterns that indicate a CLI defines its own auth-checking methods
# instead of relying on the base class is_authenticated().
_CUSTOM_AUTH_CHECK_PATTERNS = [
    (r"def\s+is_logged_in\b", "Custom is_logged_in() method"),
    (r"def\s+is_authenticated\b", "Custom is_authenticated() override"),
    (r"def\s+check_auth\b", "Custom check_auth() method"),
    (r"def\s+_ensure_logged_in\b", "Custom _ensure_logged_in() method"),
    (r"def\s+verify_session\b", "Custom verify_session() method"),
    (r"def\s+check_session\b", "Custom check_session() method"),
]


def test_browser_cli_no_custom_auth_check(cli_name, cli_dir, test_config, command_filter, is_browser_cli):
    """Browser CLIs must use BrowserAutomation.is_authenticated(), not custom auth-checking methods.

    Auth state detection must be handled by the base class is_authenticated() method.
    CLIs should only provide configuration hooks (AUTH_SUCCESS_SELECTOR, AUTH_COOKIE_PATTERNS,
    AUTH_CHECK_URL, AUTH_URL_PATTERN) to tell the base class HOW to check — not implement
    the check themselves.
    """
    if command_filter:
        pytest.skip("Skipping browser automation tests (command filter active)")
    if not is_browser_cli:
        pytest.skip(f"{cli_name} is not a browser automation CLI")

    pkg_dir = _get_pkg_dir(cli_dir, cli_name)
    browser_file = pkg_dir / "browser.py"
    config_file = pkg_dir / "config.py"

    violations = []

    for check_file in [browser_file, config_file]:
        if not check_file.exists():
            continue

        lines = check_file.read_text().splitlines()
        rel_path = check_file.relative_to(cli_dir)

        for line_num, line in enumerate(lines, start=1):
            for pattern, description in _CUSTOM_AUTH_CHECK_PATTERNS:
                if re.search(pattern, line):
                    violations.append((str(rel_path), line_num, description))

    assert not violations, (
        f"'{cli_name}' defines custom auth-checking methods instead of using "
        f"BrowserAutomation.is_authenticated() from cli_tools_shared.\n"
        f"Violations:\n"
        + "\n".join(f"  {f}:{ln} — {desc}" for f, ln, desc in violations)
        + "\n\nFix: Remove custom auth-check methods. Configure auth detection via "
        "class-level hooks on the BrowserAutomation subclass:\n"
        "  - AUTH_SUCCESS_SELECTOR = 'text=Hello username'  (DOM element visible when logged in)\n"
        "  - AUTH_COOKIE_PATTERNS = ['session_id', 'auth_token']  (cookie names indicating auth)\n"
        "  - AUTH_CHECK_URL = 'https://example.com/dashboard'  (protected page to test against)\n"
        "  - AUTH_URL_PATTERN = r'/login'  (URL pattern indicating login page redirect)\n"
        "The base class is_authenticated() uses these hooks to determine auth state."
    )


# ==================== BrowserHarnessService Usage ====================


# Patterns indicating direct browser-binary subprocess calls bypassing BrowserHarnessService,
# or direct imports of the internal service from cli_tools_shared.browser.
_DIRECT_BROWSER_PATTERNS = [
    (r"""subprocess\.\w+\(.*["']playwright-cli["']""", "Direct subprocess call to playwright-cli"),
    (r"""Popen\(.*["']playwright-cli["']""", "Direct Popen call to playwright-cli"),
    (r"""from cli_tools_shared\.browser\.driver import""", "Direct BrowserHarnessService import (use BrowserAutomation instead)"),
    (r"""from cli_tools_shared\.browser import.*BrowserHarnessService""", "Direct BrowserHarnessService import (use BrowserAutomation instead)"),
]


def test_browser_cli_uses_browser_harness_via_browser_automation(
    cli_name, cli_dir, test_config, command_filter, is_browser_cli
):
    """Browser CLIs must use browser-harness through cli_tools_shared's BrowserAutomation,
    never by importing BrowserHarnessService directly or calling browser binaries via subprocess.

    The correct layering is:
        CLI code -> BrowserAutomation (cli_tools_shared.auth) -> BrowserHarnessService -> browser-harness daemon

    CLIs should never:
    - Call playwright-cli or other browser binaries via subprocess/Popen
    - Import BrowserHarnessService directly (it's an internal detail of BrowserAutomation)
    """
    if command_filter:
        pytest.skip("Skipping browser automation tests (command filter active)")
    if not is_browser_cli:
        pytest.skip(f"{cli_name} is not a browser automation CLI")

    pkg_dir = _get_pkg_dir(cli_dir, cli_name)
    violations = []

    for py_file in pkg_dir.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue

        lines = py_file.read_text().splitlines()
        rel_path = py_file.relative_to(cli_dir)

        for line_num, line in enumerate(lines, start=1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            for pattern, description in _DIRECT_BROWSER_PATTERNS:
                if re.search(pattern, line):
                    violations.append((str(rel_path), line_num, description))

    assert not violations, (
        f"'{cli_name}' bypasses BrowserAutomation by importing BrowserHarnessService directly "
        f"or calling a browser binary via subprocess.\n"
        f"Violations:\n"
        + "\n".join(f"  {f}:{ln} — {desc}" for f, ln, desc in violations)
        + "\n\nFix: All browser operations must go through the BrowserAutomation subclass "
        "in browser.py, which internally uses BrowserHarnessService. Never import "
        "BrowserHarnessService directly or call browser binaries via subprocess.\n"
        "Correct: self._browser.get_page(url), self._browser.close()\n"
        "Wrong: subprocess.run(['playwright-cli', 'page', 'goto', url])"
    )


# ==================== browser_harness Module Importable ====================


def test_browser_cli_browser_harness_module_installed(cli_name, cli_dir, test_config, command_filter, is_browser_cli):
    """Browser CLIs must be able to import browser_harness.

    BrowserAutomation in cli_tools_shared.auth drives the browser through
    cli_tools_shared.browser.BrowserHarnessService, which imports
    'browser_harness'. If the module is not available in the CLI's uv tool
    venv, browser operations will fail at runtime with ModuleNotFoundError.
    cli-tools-shared vendors browser_harness, so deployed CLI dependencies do
    not need a separate Git-based browser-harness package.
    """
    if command_filter:
        pytest.skip("Skipping browser automation tests (command filter active)")
    if not is_browser_cli:
        pytest.skip(f"{cli_name} is not a browser automation CLI")

    uv_venv = get_uv_tool_venv_dir(cli_dir, cli_name)
    if uv_venv is None:
        pytest.skip(f"{cli_name} uv tool venv not found")

    env = {**subprocess.os.environ, "VIRTUAL_ENV": str(uv_venv)}
    result = subprocess.run(
        ["uv", "run", "--no-sync", "python", "-c", "import browser_harness"],
        capture_output=True, text=True, env=env
    )
    assert result.returncode == 0, (
        f"'{cli_name}' is a browser automation CLI but cannot import the "
        f"'browser_harness' module in its uv tool venv. BrowserAutomation "
        f"requires the browser_harness module vendored by cli-tools-shared.\n"
        f"stderr: {result.stderr.strip()}\n"
        f"Fix: Ensure {cli_name}/pyproject.toml depends on cli-tools-shared, "
        f"then run: uv tool install -e {cli_dir} --force --refresh"
    )
