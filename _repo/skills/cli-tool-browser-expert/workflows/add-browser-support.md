# Add Browser Support to an Existing CLI

<required_reading>
Before starting, read these references:
- references/architecture.md — Full system design
- references/hooks-reference.md — Available class constants
- templates/scaffold/ — All required files
</required_reading>

<process>

## Step 1: Assess Current CLI

Read the CLI's `config.py` and `main.py` to understand:
- Current `CREDENTIAL_TYPES` (what auth exists today)
- Whether `get_browser()` already exists
- Whether `create_auth_app()` is already used

If the CLI already has `get_browser()`, this is an update — check if it follows best practices instead.

## Step 2: Identify Auth Hooks

Before writing any code, determine the 5 required class constants for the target site:

1. **SESSION_NAME** — Unique name for the browser-harness session (typically the CLI name)
2. **LOGIN_URL** — The URL where users log in interactively
3. **AUTH_CHECK_URL** — A page that requires authentication (dashboard, account page)
4. **AUTH_URL_PATTERN** — Regex matching login/register URLs
5. **AUTH_SUCCESS_SELECTOR** — CSS selector visible ONLY when logged in

To find `AUTH_SUCCESS_SELECTOR`:
```bash
playwright-cli page goto "https://site.com/dashboard"
playwright-cli page snapshot
```
Look for elements unique to the authenticated state (headings, nav items, user menus).

**CRITICAL:** The selector must target a VISIBLE element. Avoid elements in collapsed sidebars, hidden menus, or lazy-loaded images.

## Step 3: Create browser.py

Create `<cli_name>_cli/browser.py` following the scaffold template:

```python
"""Browser automation for <ServiceName>."""

from cli_tools_shared.auth import BrowserAutomation

from .config import get_config


class <ServiceName>Browser(BrowserAutomation):
    """Browser automation for <ServiceName>."""

    SESSION_NAME = "<cli_name>"
    LOGIN_URL = "<login_url>"
    AUTH_CHECK_URL = "<dashboard_url>"
    AUTH_URL_PATTERN = r"<login_regex>"
    AUTH_SUCCESS_SELECTOR = '<selector>'

    def __init__(self, config=None):
        config = config or get_config()
        super().__init__(config)
```

**This file must have NO custom methods beyond `__init__`.**

## Step 4: Update config.py

Add `CredentialType.BROWSER_SESSION` and implement `get_browser()`:

```python
from cli_tools_shared.credentials import CredentialType

class Config(BaseConfig):
    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]  # or add to existing list
    DEFAULT_BASE_URL = "https://site.com"

    def get_browser(self):
        from .browser import <ServiceName>Browser
        return <ServiceName>Browser(self)
```

**Use lazy import** in `get_browser()` to avoid circular imports.

If adding browser to an existing API CLI (dual auth), append to the list:
```python
CREDENTIAL_TYPES = [CredentialType.OAUTH, CredentialType.BROWSER_SESSION]
```

## Step 5: Update main.py

Ensure `create_auth_app()` is used with a `test_handler`:

```python
from cli_tools_shared.auth_commands import create_auth_app

def _test_handler(config):
    """Test browser session by navigating to authenticated page.

    Return shape: dict is MERGED into the per-credential-type block in
    `auth status`/`auth test` output. Must contain `api_test` set to
    `"passed"` or `"failed: <reason>"`. Extra fields (e.g., `email`,
    `user_id`) are embedded alongside. NEVER return a top-level
    `authenticated` key — AuthVerifier owns that field.
    """
    browser = config.get_browser()
    try:
        browser.get_page(browser.AUTH_CHECK_URL)
        return {"api_test": "passed"}
    except Exception as e:
        return {"api_test": f"failed: {e}"}
    finally:
        browser.close()

app.add_typer(
    create_auth_app(get_config, tool_name="<cli_name>", test_handler=_test_handler),
    name="auth",
)
```

**Do NOT create custom auth commands.** `create_auth_app()` provides: login, logout, status, test, refresh.

**Return shape contract** — the test_handler's return dict is merged INTO the per-credential-type block inside `credential_types.<type>`. AuthVerifier sets `authenticated`; the handler only contributes `api_test` (required) plus any probe-derived fields (`email`, `bot_id`, etc.). Reference implementation: `google/google_cli/commands/auth.py::_google_test_handler` — returns `{"api_test": "passed", "email": "..."}`.

## Step 6: Update client.py

The client uses the browser for page automation:

```python
class Client:
    def __init__(self, config=None):
        self._config = config or get_config()
        self._browser = self._config.get_browser()

    def _get_page(self, url):
        """Get an authenticated page."""
        return self._browser.get_page(url)

    def close(self):
        """Close browser."""
        self._browser.close()
```

**NEVER call** `is_authenticated()`, `login()`, or session management from the client.
The client assumes the session exists — auth is handled by the auth commands.

## Step 7: Verify

Run the CLI tool test suite:
```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name "<cli_name>" --command auth
```

Manual verification:
```bash
<cli_name> auth login          # Should open browser for interactive login
<cli_name> auth status         # Should show credential_types.browser_session.browser_session: true/false
<cli_name> auth test           # Should verify session works
<cli_name> auth logout         # Should clear session + credentials
<cli_name> auth status         # Should show profiles[].authenticated: false
```

</process>

<success_criteria>
- browser.py is ~15 lines, 5 class constants, no custom methods
- config.py has `get_browser()` returning BrowserAutomation subclass
- config.py includes `CredentialType.BROWSER_SESSION` in CREDENTIAL_TYPES
- main.py uses `create_auth_app()` with test_handler
- client.py uses `get_page()`, no auth logic
- `auth status` returns `credential_types.browser_session.browser_session`
- `auth logout` clears browser session
- All shared browser auth tests pass
</success_criteria>
