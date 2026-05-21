# Implementation Plan: Slack CLI Refactor for cli_tools_shared Compliance

## Summary

The Slack CLI uses a bespoke multi-workspace model (workspaces.json, WorkspaceCredentials, custom auth) that is incompatible with the cli_tools_shared compliance test suite (45 of 114 tests fail). The solution is a complete one-pass refactor that replaces the custom model with BaseConfig profiles, create_auth_app(), SlackBrowser(BrowserAutomation), and standard command patterns.

## Why This Approach

- **Profiles replace workspaces**: Each Slack workspace becomes a separate .env profile, eliminating the custom workspaces.json model entirely. No migration needed — clean cutover.
- **create_auth_app() with login_handler**: The Slack browser-based auth is too custom for the default prompts but fits the `login_handler` callback pattern. Slack-specific flags (--token-type, --team-id, --all) are eliminated.
- **SlackBrowser(BrowserAutomation)**: The shared base class already supports session save/restore via CDP + session.json. The custom BrowserAutomationService is replaced by a thin subclass that adds Slack-specific token extraction via JavaScript.
- **CUSTOM credential type**: ACCESS_TOKEN is the single required field. The profile's .env file stores it directly after browser extraction.
- **Simplest data flow**: Auth login opens browser, extracts xoxc token, writes ACCESS_TOKEN to the profile's .env. All downstream commands read ACCESS_TOKEN from config.

## Prerequisites

- Compliance test runner: `<cli-tools-root>/_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name slack`

## Implementation Steps

### Step 1: Update pyproject.toml — add cli-tools-shared dependency

**File:** `<cli-tools-root>/slack/pyproject.toml`

**Action:** Add `cli-tools-shared` to the dependencies list. The package is already installed via install.sh but must be declared so pip installs it transitively when bundled for n8n.

```toml
dependencies = [
    "typer>=0.9.0",
    "python-dotenv>=1.0.0",
    "requests>=2.31.0",
    "playwright>=1.40.0",
    "cli-tools-shared @ git+https://github.com/adbertram/cli-tools.git#subdirectory=cli-tools-shared",
]
```

**Verify:** `grep "cli-tools-shared" <cli-tools-root>/slack/pyproject.toml`

---

### Step 2: Rewrite config.py — replace custom Config with BaseConfig subclass

**File:** `<cli-tools-root>/slack/slack_cli/config.py`

**Action:** Delete the entire file content and replace with a thin BaseConfig subclass. All workspace multi-credential complexity is removed. The Config class exposes:
- `CREDENTIAL_TYPES = [CredentialType.CUSTOM]`
- `CUSTOM_REQUIRED_FIELDS = ['ACCESS_TOKEN']`
- `CUSTOM_ALL_FIELDS = ['ACCESS_TOKEN', 'REFRESH_TOKEN', 'BASE_URL']`
- `CUSTOM_SENSITIVE_FIELDS = ['ACCESS_TOKEN']`
- `CUSTOM_EPHEMERAL_FIELDS = ['ACCESS_TOKEN', 'REFRESH_TOKEN']`
- `DEFAULT_BASE_URL = "https://slack.com/api"`
- `get_browser()` — returns `SlackBrowser(self)`

Also keep `BOT_SCOPES`, `USER_SCOPES` as class constants (used in the login_handler for OAuth scope reference). Remove `WorkspaceCredentials`, `TokenType`, `get_all_workspaces()`, `active_workspace`, etc.

New `get_config(profile=None)` signature must accept `profile` kwarg to match `create_auth_app()` expectations.

```python
"""Configuration management for Slack CLI."""
from pathlib import Path
from cli_tools_shared.config import BaseConfig
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS = ['ACCESS_TOKEN']
    CUSTOM_ALL_FIELDS = ['ACCESS_TOKEN', 'REFRESH_TOKEN', 'TOKEN_EXPIRES_AT', 'BASE_URL',
                         'CLIENT_ID', 'CLIENT_SECRET']
    CUSTOM_SENSITIVE_FIELDS = ['ACCESS_TOKEN', 'CLIENT_SECRET']
    CUSTOM_EPHEMERAL_FIELDS = ['ACCESS_TOKEN', 'REFRESH_TOKEN', 'TOKEN_EXPIRES_AT']
    CUSTOM_LOGIN_PROMPTS = []   # login_handler handles all credential acquisition

    DEFAULT_BASE_URL = "https://slack.com/api"

    # OAuth scopes (used by login_handler)
    BOT_SCOPES = [ ... ]  # keep existing list verbatim
    USER_SCOPES = [ ... ]  # keep existing list verbatim

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=Path(__file__).resolve().parent.parent,
            profile=profile,
        )

    def get_browser(self):
        from .browser import SlackBrowser
        return SlackBrowser(self)

    def test_connection(self):
        """Test Slack API connectivity using stored ACCESS_TOKEN."""
        token = self._get("ACCESS_TOKEN")
        if not token:
            return {"api_test": "failed: no ACCESS_TOKEN"}
        import requests
        resp = requests.get(
            f"{self.base_url}/auth.test",
            headers={"Authorization": f"Bearer {token}"},
        )
        data = resp.json()
        if data.get("ok"):
            return {"api_test": "passed", "team": data.get("team"), "user": data.get("user")}
        return {"api_test": f"failed: {data.get('error', 'unknown')}"}


_configs = {}

def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]


def reset_config():
    global _configs
    _configs = {}
```

**Verify:** `~/.local/share/uv/tools/slack-cli/bin/python -c "from slack_cli.config import get_config; c = get_config(); print(c.CREDENTIAL_TYPES)"`

---

### Step 3: Rewrite browser.py — SlackBrowser(BrowserAutomation) subclass

**File:** `<cli-tools-root>/slack/slack_cli/browser.py`

**Action:** Replace the entire file with a `SlackBrowser` class that extends `BrowserAutomation`. The class handles:
1. Interactive browser auth (CDP approach from base class)
2. Token extraction from Slack's localStorage after login
3. Saving the extracted token to the profile's `.env` via `config._set()`

Key class variables:
- `LOGIN_URL = "https://slack.com/signin"`
- `AUTH_CHECK_URL = "https://app.slack.com/client"`
- `AUTH_URL_PATTERN = r"/signin"` (Slack's login detection)
- `AUTH_SUCCESS_URL = r"/client"` (logged-in detection)
- `AUTH_COOKIE_PATTERNS = ["d"]` (Slack's session cookie)

Override `_on_authenticated(page)` to extract the xoxc token from localStorage and call `config._set("ACCESS_TOKEN", token)` and `config._set("REFRESH_TOKEN", d_cookie)`.

The `is_authenticated()` check uses the cookie pattern (fast, no browser launch) plus also checks for ACCESS_TOKEN in config.

```python
"""Slack browser automation — extracts session tokens via CDP."""
from cli_tools_shared.auth import BrowserAutomation


class SlackBrowser(BrowserAutomation):
    LOGIN_URL = "https://slack.com/signin"
    AUTH_CHECK_URL = "https://app.slack.com/client"
    AUTH_URL_PATTERN = r"/signin|/sign-in|workspace-signin"
    AUTH_SUCCESS_URL = r"/client"
    AUTH_COOKIE_PATTERNS = ["^d$"]   # Slack 'd' session cookie

    def _on_authenticated(self, page):
        """After login: extract xoxc token and save to profile .env."""
        js_code = """() => {
            try {
                const config = JSON.parse(localStorage.localConfig_v2 || '{}');
                const teams = config.teams || {};
                const results = [];
                for (const [teamId, teamData] of Object.entries(teams)) {
                    if (teamData.token) {
                        results.push({ team_id: teamId, team_name: teamData.name || '', token: teamData.token });
                    }
                }
                return results;
            } catch(e) { return []; }
        }"""
        token_data = page.evaluate(js_code)
        if token_data:
            # Save first (primary) workspace token to profile
            primary = token_data[0]
            self.config._set("ACCESS_TOKEN", primary["token"])
            # Get 'd' cookie and store as REFRESH_TOKEN
            cookies = self._context.cookies(["https://slack.com", "https://app.slack.com"])
            d_cookie = next((c["value"] for c in cookies if c["name"] == "d"), None)
            if d_cookie:
                self.config._set("REFRESH_TOKEN", d_cookie)

    def is_authenticated(self) -> bool:
        """Check auth: token in .env OR valid session file with 'd' cookie."""
        token = self.config._get("ACCESS_TOKEN")
        if token:
            return True
        return super().is_authenticated()
```

**Verify:** `python -c "from slack_cli.browser import SlackBrowser; print('OK')"`

---

### Step 4: Rewrite commands/auth.py — use create_auth_app()

**File:** `<cli-tools-root>/slack/slack_cli/commands/auth.py`

**Action:** Replace the entire file. The new auth module:
1. Defines a `slack_login_handler(config, force)` function that handles the Slack-specific browser session flow (the existing `_capture_session_tokens` logic, adapted for single-profile model)
2. Calls `create_auth_app(get_config, tool_name="slack", login_handler=slack_login_handler)` from cli_tools_shared
3. The `app` variable returned by `create_auth_app()` becomes the module-level `app`

The `slack_login_handler(config, force)` function:
- Instantiates `SlackBrowser(config)`
- Calls `browser.authenticate(force=force)` (which opens Chrome, waits for login, then calls `_on_authenticated` to save the token)
- Prints success/error messages

This eliminates all custom login/logout/status/refresh implementations. The common package handles all of those.

```python
"""Authentication commands for Slack CLI."""
from ..config import get_config
from ..browser import SlackBrowser
from cli_tools_shared import create_auth_app
from cli_tools_shared.output import print_success, print_error


def slack_login_handler(config, force: bool):
    """Custom login handler: opens Chrome, user logs into Slack, token is captured."""
    browser = SlackBrowser(config)
    try:
        result = browser.login(force=force)
        if result.get("success"):
            print_success("Slack session authenticated. Token saved to profile.")
        else:
            print_error(f"Browser auth failed: {result.get('message', 'Unknown error')}")
    finally:
        browser.close()


app = create_auth_app(get_config, tool_name="slack", login_handler=slack_login_handler)
```

**Important:** The `create_auth_app()` generates login, logout, status, refresh, and test (because `test_connection()` is implemented on Config). All previously failing auth tests should pass after this step.

**Verify:** `slack auth --help` (should show login, logout, status, refresh, test commands with --profile/-p flags on all of them)

---

### CHECKPOINT: Verify steps 1-4

**Run:** `<cli-tools-root>/_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name slack --pytest-args "-k 'auth or basic_setup or config' -v"`

**Expected:** auth tests passing: login (with --force, --profile), status (with --table, --profile, exit 0), logout (with --profile), test, profiles subcommands present. Config test passing (BaseConfig import found).

---

### Step 5: Update main.py — use auth profiles, remove workspace group

**File:** `<cli-tools-root>/slack/slack_cli/main.py`

**Action:** Three changes:
1. Import auth app from `commands.auth` module (which now exports the `create_auth_app()` result)
2. Use `auth profiles` from `create_auth_app()` instead of a top-level `profiles` command group
3. Remove the `workspace` command group import and `app.add_typer(workspace.app, ...)` line

```python
# ... existing imports ...
from .commands import auth, channels, dm, messages, reminders, users, files
from .commands import canvas, bookmarks, pins, notifications

app.add_typer(auth.app, name="auth", help="Manage Slack API authentication")
# ... rest of existing add_typer calls (minus workspace) ...
```

**Verify:** `slack auth --help` shows the `profiles` group and `slack --help` shows no top-level `profiles` or `workspace` group.

---

### Step 6: Update .env.example — remove SLACK_ prefix, add IS_DEFAULT_PROFILE

**File:** `<cli-tools-root>/slack/.env.example`

**Action:** Rewrite the file with generic variable names (no SLACK_ prefix) and add IS_DEFAULT_PROFILE. The test `test_env_no_service_prefix` checks for `SLACK_` prefixed vars in `.env.example`.

```bash
# Slack CLI profile configuration
IS_DEFAULT_PROFILE=1

# Required: Slack session token (xoxc-*). Obtained via 'slack auth login'.
ACCESS_TOKEN=

# Optional: OAuth app credentials for user/bot token flows
CLIENT_ID=
CLIENT_SECRET=

# Session cookie ('d' value). Saved automatically by 'slack auth login'.
REFRESH_TOKEN=

# Slack API base URL (do not change unless using a custom Slack instance)
BASE_URL=https://slack.com/api
```

**Verify:** `grep "SLACK_" <cli-tools-root>/slack/.env.example` → no output (no SLACK_ prefixed vars remain)

---

### Step 7: Update .env file — remove SLACK_ prefix, add IS_DEFAULT_PROFILE

**File:** `<cli-tools-root>/slack/.env`

**Action:** Rename all SLACK_-prefixed vars and add IS_DEFAULT_PROFILE. Read the existing `.env` file first to preserve any set values, then rewrite with generic names.

The mappings are:
- `SLACK_ACCESS_TOKEN` → `ACCESS_TOKEN`
- `SLACK_REFRESH_TOKEN` → `REFRESH_TOKEN`
- `SLACK_TOKEN_EXPIRES_AT` → `TOKEN_EXPIRES_AT`
- `SLACK_CLIENT_ID` → `CLIENT_ID`
- `SLACK_CLIENT_SECRET` → `CLIENT_SECRET`
- `SLACK_BASE_URL` → `BASE_URL`
- Add `IS_DEFAULT_PROFILE=1` if not present

**Verify:** `grep "SLACK_" <cli-tools-root>/slack/.env` → no output; `grep "IS_DEFAULT_PROFILE" <cli-tools-root>/slack/.env` → `IS_DEFAULT_PROFILE=1`

---

### Step 8: Update .gitignore — add profiles/ and .env* patterns

**File:** `<cli-tools-root>/slack/.gitignore`

**Action:** Add the following lines if not present:
```
profiles/
.env
.env.*
!.env.example
```

**Verify:** `grep "profiles/" <cli-tools-root>/slack/.gitignore`

---

### Step 9: Replace filters.py with canonical template

**File:** `<cli-tools-root>/slack/slack_cli/filters.py`

**Action:** The compliance test `test_filters_identical_to_template` requires `filters.py` to be byte-for-byte identical to the template used by other passing CLIs. The canonical template is at `<cli-tools-root>/cloudflare/cloudflare_cli/filters.py`. Copy it verbatim.

The current `filters.py` is missing `contains`, `startswith`, `endswith` operators, `get_nested_value()`, `apply_properties_filter()`, and `apply_limit()` functions.

**Exact content to write:** Copy the full content of `<cli-tools-root>/cloudflare/cloudflare_cli/filters.py` (293 lines) to `<cli-tools-root>/slack/slack_cli/filters.py`.

**Verify:** `diff <cli-tools-root>/cloudflare/cloudflare_cli/filters.py <cli-tools-root>/slack/slack_cli/filters.py` → no output (files are identical)

---

### CHECKPOINT: Verify steps 5-9

**Run:** `cd <cli-tools-root>/_repo/skills/cli-tool/tests && pytest --cli-name slack -k "filters or profiles or env" -v 2>&1 | tail -20`

**Expected:** filters tests passing (all operators present, identical to template), profiles command tests passing, env prefix tests passing.

---

### PARALLEL GROUP: Update 12 command files — add COMMAND_CREDENTIALS and fix 'info'→'get', add --properties flag (Steps 10-21)

**Steps 10-21 can run concurrently — each file is independent.**

**Execution:** Spawn 12 subagents simultaneously, one per command file, using the Task tool.

The changes required for ALL command files:
1. Add `COMMAND_CREDENTIALS` dict at module level mapping each `@app.command("name")` to `["custom"]`
2. Rename any `@app.command("info")` to `@app.command("get")` and rename the function too
3. Add `--properties/-p` flag to any `list` command that lacks it (applies `apply_properties_filter()`)
4. Update filter help text on `--filter` options to use "field:op:value" syntax description (e.g., `"Filter: field:op:value (e.g., name:eq:value)"`)

**Command files and their commands** (from `ls slack_cli/commands/`):

#### Step 10: channels.py
**File:** `<cli-tools-root>/slack/slack_cli/commands/channels.py`

Commands registered: `list`, `info` (→ rename to `get`)

```python
COMMAND_CREDENTIALS = {
    "list": ["custom"],
    "get": ["custom"],
}
```

Changes:
- Add `COMMAND_CREDENTIALS` after imports
- Rename `@app.command("info")` → `@app.command("get")`, rename function `channel_info` → `channel_get`
- Add `--properties/-p` to `list_channels()`
- Import `apply_properties_filter` from `..filters`
- Apply properties filter before `print_json()`/`print_table()`
- Update `--filter` help text: `"Filter: field:op:value (e.g., name:eq:general, is_private:eq:true)"`

**Subagent prompt:** "Edit `<cli-tools-root>/slack/slack_cli/commands/channels.py`. Read the file first. Make these changes: (1) Add `COMMAND_CREDENTIALS = {'list': ['custom'], 'get': ['custom']}` after the imports. (2) Rename the `@app.command('info')` decorator to `@app.command('get')` and rename the `channel_info` function to `channel_get`. Update the docstring examples. (3) Add `properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated fields to include')` to `list_channels()`. (4) Add `from ..filters import apply_filters, validate_filters, FilterValidationError, apply_properties_filter` (replace existing import). (5) In `list_channels()`, after `if filter_: channels = apply_filters(channels, filter_)`, add `if properties: channels = apply_properties_filter(channels, properties)`. (6) Update `--filter` help text to: `'Filter: field:op:value (e.g., name:eq:general, is_private:eq:true)'`."

#### Step 11: users.py
**File:** `<cli-tools-root>/slack/slack_cli/commands/users.py`

Commands: `list`, `info` (→ `get`)

```python
COMMAND_CREDENTIALS = {
    "list": ["custom"],
    "get": ["custom"],
}
```

Same pattern as channels.py: rename info→get, add --properties, update filter help.

**Subagent prompt:** "Edit `<cli-tools-root>/slack/slack_cli/commands/users.py`. Read the file first. (1) Add `COMMAND_CREDENTIALS = {'list': ['custom'], 'get': ['custom']}` after imports. (2) Rename `@app.command('info')` to `@app.command('get')`, rename function `user_info` to `user_get`. (3) Add `properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated fields to include')` to `list_users()`. (4) Update import to include `apply_properties_filter`. (5) After `if filter_: users = apply_filters(users, filter_)`, add `if properties: users = apply_properties_filter(users, properties)`. (6) Update `--filter` help text to `'Filter: field:op:value (e.g., name:eq:john, is_admin:eq:true)'`."

#### Step 12: files.py
**File:** `<cli-tools-root>/slack/slack_cli/commands/files.py`

Commands: `list`, `info` (→ `get`, if present) — read file to confirm exact commands.

```python
COMMAND_CREDENTIALS = {
    "list": ["custom"],
    "get": ["custom"],
}
```

**Subagent prompt:** "Read `<cli-tools-root>/slack/slack_cli/commands/files.py` and identify all `@app.command(...)` decorators. Then: (1) Add `COMMAND_CREDENTIALS` dict after imports mapping each command name to `['custom']`, using 'get' instead of 'info' for any info command. (2) Rename any `@app.command('info')` to `@app.command('get')` and the corresponding function. (3) Add `properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated fields to include')` to any `list` command. (4) Update import to include `apply_properties_filter` from `..filters`. (5) Apply `apply_properties_filter` in list commands before output. (6) Update `--filter` help text to `'Filter: field:op:value (e.g., name:eq:report.pdf)'`."

#### Step 13: messages.py
**File:** `<cli-tools-root>/slack/slack_cli/commands/messages.py`

**Subagent prompt:** "Read `<cli-tools-root>/slack/slack_cli/commands/messages.py` and identify all `@app.command(...)` decorators. Then: (1) Add `COMMAND_CREDENTIALS` dict mapping each command name to `['custom']`, using 'get' for any 'info' commands. (2) Rename any `@app.command('info')` to `@app.command('get')`. (3) Add `properties` flag to any list command. (4) Update filter imports to include `apply_properties_filter`. (5) Apply properties filter in list commands. (6) Update --filter help text to use field:op:value syntax."

#### Step 14: dm.py
**File:** `<cli-tools-root>/slack/slack_cli/commands/dm.py`

**Subagent prompt:** "Read `<cli-tools-root>/slack/slack_cli/commands/dm.py` and identify all `@app.command(...)` decorators. Then: (1) Add `COMMAND_CREDENTIALS` dict mapping each command name to `['custom']`, using 'get' for any 'info' commands. (2) Rename any `@app.command('info')` to `@app.command('get')`. (3) Add `properties` flag to any list command: `properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated fields to include')`. (4) Update filter imports to include `apply_properties_filter` from `..filters`. (5) Apply properties filter before output in list commands. (6) Update --filter help to field:op:value syntax."

#### Step 15: reminders.py
**File:** `<cli-tools-root>/slack/slack_cli/commands/reminders.py`

**Subagent prompt:** "Read `<cli-tools-root>/slack/slack_cli/commands/reminders.py` and identify all `@app.command(...)` decorators. Then: (1) Add `COMMAND_CREDENTIALS` dict mapping each command name to `['custom']`, using 'get' for any 'info' commands. (2) Rename any `@app.command('info')` to `@app.command('get')`. (3) Add `properties` flag to any list command. (4) Update filter imports if needed. (5) Apply properties filter in list commands. (6) Update --filter help to field:op:value syntax. Note: if the file has no `--filter` option on list commands, add it along with `--limit` if missing."

#### Step 16: canvas.py
**File:** `<cli-tools-root>/slack/slack_cli/commands/canvas.py`

**Subagent prompt:** "Read `<cli-tools-root>/slack/slack_cli/commands/canvas.py` and identify all `@app.command(...)` decorators. Then: (1) Add `COMMAND_CREDENTIALS` dict mapping each command name to `['custom']`, using 'get' for any 'info' commands. (2) Rename any `@app.command('info')` to `@app.command('get')`. (3) Add `properties` flag to any list command. (4) Update filter imports if needed. (5) Apply properties filter in list commands. (6) Update --filter help to field:op:value syntax."

#### Step 17: bookmarks.py
**File:** `<cli-tools-root>/slack/slack_cli/commands/bookmarks.py`

**Subagent prompt:** "Read `<cli-tools-root>/slack/slack_cli/commands/bookmarks.py` and identify all `@app.command(...)` decorators. Then: (1) Add `COMMAND_CREDENTIALS` dict mapping each command name to `['custom']`, using 'get' for any 'info' commands. (2) Rename any `@app.command('info')` to `@app.command('get')`. (3) Add `properties` flag to any list command. (4) Update filter imports if needed. (5) Apply properties filter in list commands. (6) Update --filter help to field:op:value syntax."

#### Step 18: pins.py
**File:** `<cli-tools-root>/slack/slack_cli/commands/pins.py`

**Subagent prompt:** "Read `<cli-tools-root>/slack/slack_cli/commands/pins.py` and identify all `@app.command(...)` decorators. Then: (1) Add `COMMAND_CREDENTIALS` dict mapping each command name to `['custom']`, using 'get' for any 'info' commands. (2) Rename any `@app.command('info')` to `@app.command('get')`. (3) Add `properties` flag to any list command. (4) Update filter imports if needed. (5) Apply properties filter in list commands. (6) Update --filter help to field:op:value syntax."

#### Step 19: notifications.py
**File:** `<cli-tools-root>/slack/slack_cli/commands/notifications.py`

**Subagent prompt:** "Read `<cli-tools-root>/slack/slack_cli/commands/notifications.py` and identify all `@app.command(...)` decorators. Then: (1) Add `COMMAND_CREDENTIALS` dict mapping each command name to `['custom']`, using 'get' for any 'info' commands. (2) Rename any `@app.command('info')` to `@app.command('get')`. (3) Add `properties` flag to any list command. (4) Update filter imports if needed. (5) Apply properties filter in list commands. (6) Update --filter help to field:op:value syntax."

#### Step 20: Delete workspace.py (command group removed)

**File:** `<cli-tools-root>/slack/slack_cli/commands/workspace.py`

**Action:** Delete this file. The workspace group is replaced by `profiles`. The import of `workspace` in `main.py` was already removed in Step 5.

**Subagent prompt:** "Delete the file `<cli-tools-root>/slack/slack_cli/commands/workspace.py` using Bash: `rm <cli-tools-root>/slack/slack_cli/commands/workspace.py`"

#### Step 21: Update client.py — remove workspace-based client factory

**File:** `<cli-tools-root>/slack/slack_cli/client.py`

**Action:** Read the file first. The client likely uses `get_config().active_workspace` or `get_all_workspaces()` to build clients. After the refactor, there is a single active profile's `ACCESS_TOKEN`. Update client factory to use `config.access_token` (which reads from `ACCESS_TOKEN` env var via BaseConfig). Remove `get_all_workspace_clients()` and `get_client_for_workspace_id()` if they reference the old workspace model. Replace with a single `get_client(profile=None)` that instantiates with `config.access_token`.

**Subagent prompt:** "Read `<cli-tools-root>/slack/slack_cli/client.py`. Identify how it creates clients (likely via `get_config().active_workspace` or `get_all_workspaces()`). Update it to use the new single-profile model: replace workspace-based client creation with `config = get_config(profile)` and `token = config.access_token`. Keep the SlackClient class itself intact — only change the factory functions at the bottom. The ACCESS_TOKEN is read from `config._get('ACCESS_TOKEN')` or `config.access_token`. If `get_all_workspace_clients()` or `get_client_for_workspace_id()` are used by command files, update them to return a single client from the active profile instead of iterating workspaces."

---

### CHECKPOINT: Verify steps 10-21

**Run:** `~/.local/share/uv/tools/slack-cli/bin/python -c "from slack_cli.main import app; print('Import OK')" && slack --help`

**Expected:** CLI imports without errors. All command groups appear. `workspace` is gone. `profiles` is present. No `auth workspace` commands visible.

**Run:** `cd <cli-tools-root>/_repo/skills/cli-tool/tests && pytest --cli-name slack -k "credentials or get_commands" -v 2>&1 | tail -30`

**Expected:** COMMAND_CREDENTIALS tests passing for all 12 modules. `info`→`get` rename validated.

---

### Step 22: Reinstall package

**Action:** After all code changes, reinstall the package so the `slack` executable reflects the latest code.

```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/install-cli-tool.sh slack
```

**Verify:** `slack --help` works. `slack auth --help` shows login/logout/status/test/refresh with --profile/-p flags.

---

### Step 24: Run full compliance test suite

**Action:** Run all 114 compliance tests to verify the refactor is complete.

```bash
cd <cli-tools-root>/_repo/skills/cli-tool/tests
pytest --cli-name slack -v 2>&1 | tail -50
```

**Expected:** 0 failures (or only skipped tests from integration-level tests that require live Slack auth).

**Specific assertions to verify manually if any remain:**
- `test_auth_status_outputs_json_with_authenticated` — requires `auth status` to exit 0 (the `create_auth_app()` status command does not `raise typer.Exit(2)` when unauthenticated, it exits 0)
- `test_filters_identical_to_template` — diff should be empty
- `test_all_commands_have_credential_mapping` — all 12 modules must have COMMAND_CREDENTIALS

---

## Testing Strategy

**Unit smoke test (no auth needed):**
```bash
slack --help
slack auth --help
slack auth login --help    # must have --force/-F and --profile/-p
slack auth status          # must exit 0, output JSON with 'authenticated' field
slack auth status --table
slack auth profiles --help
slack channels --help      # must have list and get (not info)
slack users --help         # must have list and get (not info)
```

**Compliance test suite:**
```bash
cd <cli-tools-root>/_repo/skills/cli-tool/tests
pytest --cli-name slack -v
```

**If auth is available (live test):**
```bash
slack auth status          # {"authenticated": true, ...}
slack auth test            # {"api_test": "passed", ...}
slack channels list --limit 5
slack users list --limit 5
```

## What's NOT Included

- Multi-workspace support within a single profile (one profile = one workspace, use `slack auth login --profile ws2` to add a second)
- Migration of existing workspaces.json data (clean cutover, users must re-authenticate)
- OAuth user/bot token flows (removed; session token via browser is the sole auth method post-refactor)
- The `--token-type`, `--team-id`, `--all` flags on auth login (eliminated per design decision)

## Success Criteria

- [ ] 0 compliance test failures (up from 45)
- [ ] `slack auth status` exits 0 in all cases, outputs JSON with `authenticated` field
- [ ] `slack auth login --help` shows `--force/-F` and `--profile/-p` flags (no `--token-type`, `--team-id`, `--all`)
- [ ] `slack auth profiles list` works
- [ ] `slack channels list --properties id,name` works
- [ ] `slack channels get <id>` works (renamed from `info`)
- [ ] `slack users get <id>` works (renamed from `info`)
- [ ] No `SLACK_`-prefixed vars in `.env.example`
- [ ] `IS_DEFAULT_PROFILE=1` in `.env`
- [ ] `filters.py` is byte-for-byte identical to cloudflare's template
- [ ] All 12 command modules have `COMMAND_CREDENTIALS` dict
- [ ] `workspace` command group is gone
