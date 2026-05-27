# Authentication Standards

## Auth Requirement by Credential/CLI Type

Authentication commands (`auth login`, `auth status`) are **not required for all CLIs**. Whether auth is required depends on the credential type and CLI type.

| Credential / CLI Type | Auth Required? | Reason |
|-----------------------|----------------|--------|
| `api_key` | **REQUIRED** | Must store and validate API key |
| `personal_access_token` | **REQUIRED** | Must store and validate PAT |
| `oauth` | **REQUIRED** | Must handle OAuth token flow |
| `oauth_authorization_code` | **REQUIRED** | Must handle auth code exchange |
| `username_password` | **REQUIRED** | Must store and validate credentials |
| `browser_session` | **AUTO** | Auth auto-generated via `create_auth_app()` + `PlaywrightCLIBrowser` adapter |
| `wrapper` CLI type | **OPTIONAL** | Underlying CLI may handle its own auth |
| `browser` CLI type | **AUTO** | Uses `create_auth_app()` (default auth type: `browser_session`) |
| `none` (no auth) | **NOT APPLICABLE** | No auth commands scaffolded |

**When auth IS present**, the CLI MUST have:

1. **auth login** - Authenticate with the service
2. **auth status** - Check authentication status

```bash
<name> auth status   # Should work without error if authenticated
<name> auth login    # Should initiate authentication flow
<name> auth login --force  # Clear existing session and re-authenticate
```

## CLI-Tools Secret Manager

Before asking Adam for CLI credentials, or storing any new reusable CLI credential, follow `references/secrets.md`.

## `auth status` JSON Shape (Canonical)

`create_auth_app` (in `cli_tools_shared.auth_commands`) emits a single canonical shape. Every CLI — including wrappers — returns this shape:

```json
{
  "profiles": [
    {
      "name": "default",
      "auth_type": "default",
      "active": true,
      "authenticated": true,
      "credential_types": {
        "custom": {
          "credentials_saved": true,
          "api_test": "passed",
          "authenticated": true
        }
      }
    }
  ]
}
```

**Field rules:**

- `profiles` is always a list. Single-profile CLIs still emit a one-element list.
- stdout MUST be a single valid JSON document. No prose, info messages, or progress text may be mixed in — `print_info` / `print_success` / `print_error` must route to stderr. Mixing prose with JSON on stdout breaks every downstream JSON consumer (this is the "monarch stream-separation bug").
- Per-profile required keys: `name` (string), `auth_type` (string), `active` (bool), `authenticated` (bool), `credential_types` (object). `auth status` returns active profiles only, with exactly one active profile per auth type.
- Per-profile `authenticated` is OR-over-configured types: true when at least one credential pathway works.
- `credential_types.<type>` is keyed by the `CredentialType.value` string. **The complete whitelist** is `custom`, `api_key`, `oauth`, `oauth_authorization_code`, `personal_access_token`, `username_password`, `browser_session`. Any other key is a schema violation. Per-type **required** keys:
  - `credentials_saved` (bool) — whether required fields for this type are present in the profile.
  - `authenticated` (bool) — whether this type's API test succeeded.
- Per-type **conditional** keys:
  - `api_test` — when present, MUST be the literal string `"passed"` or a string starting with `"failed:"` (e.g., `"failed: unauthorized"`). Sourced from `Config.test_connection()`.
  - Extra keys from `Config.test_connection()` land here (e.g., `email`, `bot_id`, `user_id`). For OAuth, `oauth_status` lands under `credential_types.oauth`. For browser, `browser_session` / `browser_available` land under `credential_types.browser_session`.
- Per-type **optional** keys (reserved; emit when meaningful, no validator enforces them yet):
  - `expires_at` — ISO-8601 timestamp string indicating when the saved token/session expires.
  - `scopes` — list of scope strings granted by the upstream OAuth provider.
  - `last_authenticated_at` — ISO-8601 timestamp string indicating when the credential last successfully authenticated.
- Old flat shape (`{"authenticated": true, "credentials_saved": true, "api_test": "passed"}`) is obsolete. Anything consuming `auth status` JSON must read `profiles[].credential_types.<type>.api_test` and `profiles[].authenticated`.

**Validation gates (enforced):**

- **Fleet-level gate** — `<cli-tools-root>/_repo/skills/cli-tool/scripts/test-cli-tool.sh` runs an `auth status` schema and readiness preflight before the broader pytest suite. It executes `<cli> auth status`, parses stdout as JSON via the shared `tests/auth_status_schema.py` helper, requires every reported profile to be authenticated and requires each authenticated profile to have at least one authenticated credential type. Unused secondary credential types may report `authenticated: false` when the profile is still usable through another credential pathway. The gate prints a clear `[FAIL] auth status schema: ...` line on stderr for violations and injects a structured `test_auth_status_schema_preflight` failure into the harness JSON summary. The phase auto-skips when the CLI has no `auth` or `auth status` subcommand.
- **Pytest CLI gate** — `_repo/skills/cli-tool/tests/test_auth_status_schema.py` reuses the same helper for direct pytest runs and other callers that invoke the compliance tests outside the shell wrapper.
- **Unit-level gate** — `_repo/cli-tools-shared/tests/test_auth_commands.py` invokes `create_auth_app`'s `status` subcommand via Typer's `CliRunner` and asserts the same canonical shape end-to-end across single-profile, multi-profile, passing, failing, and dual-credential setups. The shared schema helper is the source of truth — keep all three gates in sync.

**Who computes what:**

- `Config.test_connection()` powers `auth status` API validation. It returns the per-type dict (merged into `credential_types.<type>`).
- The `test_handler` kwarg to `create_auth_app` only powers the separate `auth test` subcommand, not `auth status`.
- Existing env var names (e.g., `NOTION_API_TOKEN`) are preserved via `CUSTOM_REQUIRED_FIELDS` on `Config(BaseConfig)` — don't rename to `API_KEY`.

**When auth is OPTIONAL and not present:**
- The CLI simply has no `auth` subcommand group
- Test suite will auto-detect this and skip auth tests
- The CLI should work without any authentication setup
- Use `--auth-type none` when scaffolding to skip auth commands entirely

## Supported Credential Types

Set via `--auth-type` flag (repeatable) when creating a CLI with `new-cli-tool`, or by setting `CREDENTIAL_TYPES` in `config.py`.

| Type | Enum Value | Required Env Var | Use Case |
|------|-----------|------------------|----------|
| None | N/A (no auth scaffolded) | None | Local tools, wrappers with no auth |
| API Key | `CredentialType.API_KEY` | `API_KEY` | Services using API keys |
| Personal Access Token | `CredentialType.PERSONAL_ACCESS_TOKEN` | `PERSONAL_ACCESS_TOKEN` | Services using PATs (GitHub, GitLab, etc.) |
| OAuth | `CredentialType.OAUTH` | `CLIENT_ID`, `CLIENT_SECRET`, `ACCESS_TOKEN` | OAuth 2.0 flows |
| OAuth Auth Code | `CredentialType.OAUTH_AUTHORIZATION_CODE` | `CLIENT_ID`, `CLIENT_SECRET`, `ACCESS_TOKEN`, `REDIRECT_URI` | OAuth 2.0 authorization code flow |
| Username/Password | `CredentialType.USERNAME_PASSWORD` | `USERNAME`, `PASSWORD` | Basic auth |
| Browser Session | `CredentialType.BROWSER_SESSION` | None (uses browser session profile) | Browser automation CLIs |

**Example config.py for PAT auth:**
```python
from cli_tools_shared.config import BaseConfig
from cli_tools_shared.credentials import CredentialType

class Config(BaseConfig):
    CREDENTIAL_TYPES = [CredentialType.PERSONAL_ACCESS_TOKEN]
    DEFAULT_BASE_URL = "https://api.example.com"
```

## Multiple Credential Types

Some services need both API credentials and browser automation (e.g., API for data + browser for actions without API coverage). Use multiple types — each configured pathway is tested independently, and the top-level `authenticated` flag is true when ANY configured type succeeds.

**Scaffolding with multiple types:**
```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/new-cli-tool \
  --name myservice --type api --base-url https://api.example.com \
  --auth-type api_key --auth-type browser_session
```

**Example config.py for dual auth:**
```python
class Config(BaseConfig):
    CREDENTIAL_TYPES = [CredentialType.API_KEY, CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://api.example.com"
```

**How it works:**
- `auth login` prompts for all required fields across all types (deduplicated)
- `auth status` reports per-type results under `credential_types.<type>` and sets top-level `authenticated: true` when ANY configured (`credentials_saved: true`) type authenticates. An unconfigured listed type does not drag the top-level to false.
- `auth logout` clears credentials for ALL types
- Fields shared across types (e.g., `USERNAME`) are prompted once

**When to use multiple types:**
- Service has an API but some actions require browser automation
- OAuth API + browser session for scraping (e.g., Descript, PayPal)
- API key + username/password for different service tiers

## API Client Credential Gate in Dual-Auth CLIs

**CRITICAL:** When a CLI has multiple credential types (e.g., `API_KEY` + `BROWSER_SESSION`), the API client constructor must NOT use `has_credentials()`. That method uses AND semantics — it requires ALL credential types to be satisfied, which blocks API-only commands when no browser session exists.

**Solution:** Add `has_api_credentials()` to your Config and use it in the API client:

**config.py (API_KEY variant):**
```python
def has_api_credentials(self) -> bool:
    """Check if API key is configured (ignores browser session)."""
    return bool(self.api_key)
```

**config.py (OAuth variant):**
```python
def has_api_credentials(self) -> bool:
    """Check if OAuth credentials are configured (ignores browser session)."""
    return bool(self.consumer_key and self.consumer_secret
                and self.token_value and self.token_secret)
```

**client.py:**
```python
# CORRECT: Only check API credentials
if not self.config.has_api_credentials():
    raise ClientError("Missing API credentials. Run '<name> auth login -c api_key' to configure.")

# WRONG: Blocks API commands when browser session is missing
if not self.config.has_credentials():
    ...
```

**Reference implementation:** `bricklink_cli/config.py:58-68` and `bricklink_cli/client.py:50-56`.

## COMMAND_CREDENTIALS Mapping (Required for n8n Node Generation)

**Every command file in a multi-credential CLI MUST declare a `COMMAND_CREDENTIALS` dict** at the top of the file (before imports). This maps each command name to the credential types it uses. The n8n node generator reads this to split commands into separate nodes per credential type.

```python
"""Order commands for MyService CLI."""
COMMAND_CREDENTIALS = {
    "list": ["api_key"],
    "get": ["api_key"],
    "status": ["api_key"],
}

import typer
# ... rest of file
```

```python
"""Messages commands for MyService CLI."""
COMMAND_CREDENTIALS = {
    "list": ["browser_session"],
    "reply": ["browser_session"],
    "send": ["browser_session"],
}

import typer
# ... rest of file
```

**How it's used by n8n:**
- `n8n nodes create <cli>` parses `COMMAND_CREDENTIALS` from each command file via AST
- If the CLI has multiple credential types, separate n8n nodes are generated (e.g., `MyService (API)` and `MyService (Browser)`)
- Each node contains only the operations mapped to its credential type
- Single-credential CLIs generate one node (no suffix, unchanged behavior)

**Rules:**
- Dict must be at module level, before any imports (AST parser reads it statically)
- Keys are command names (must match `@app.command("name")` values)
- Values are lists of credential type strings (e.g., `["api_key"]`, `["browser_session"]`)
- Every command in the file should have an entry
- Single-credential CLIs can omit this dict (all commands use the single type)

## auth login --force Flag (MANDATORY)

**CRITICAL: The `auth login` command MUST support `--force/-F` flag.**

| Behavior | Description |
|----------|-------------|
| Without `--force` | Idempotent - may skip if already authenticated |
| With `--force` | Clears existing session/credentials FIRST, then initiates fresh authentication |

Implementation by template type:

| Template | --force Behavior |
|----------|------------------|
| API | Call `config.clear_credentials()` before prompting for API key |
| Browser | Call `config.clear_session()` before opening browser login |
| Wrapper | Call underlying CLI's logout command before running login |
| OAuth (built-in) | Clears OAuth app credentials and tokens, prompts for CLIENT_ID/CLIENT_SECRET/REDIRECT_URI, then re-runs the auth flow |

**OAuth --force note:** For CLIs using the built-in `oauth_login` handler (via `OAUTH_*` class vars), `--force` clears OAuth app credentials and tokens first, then prompts again for CLIENT_ID, CLIENT_SECRET, and REDIRECT_URI before opening the browser authorization flow.

## auth login --credential-type Flag (Multi-Credential CLIs)

For CLIs with multiple credential types (2+ types in `CREDENTIAL_TYPES`), the `--credential-type` / `-c` flag scopes login to a single credential type. This allows re-authenticating just one type without affecting others.

| Behavior | Description |
|----------|-------------|
| Without `--credential-type` | Prompts for ALL credential types (default behavior) |
| With `--credential-type <type>` | Prompts only for the specified type's fields |
| Combined with `--force` | Clears ephemeral state only for the specified type |
| On single-credential CLIs | Errors with "only valid for CLIs with multiple credential types" |

**Valid values:** The `.value` strings from `CredentialType` enum — `api_key`, `personal_access_token`, `oauth`, `oauth_authorization_code`, `username_password`, `browser_session`.

**Example usage:**
```bash
# Re-do only the browser login without re-entering API keys
bricklink auth login --credential-type browser_session --force

# Re-authenticate only OAuth (get fresh tokens)
myservice auth login -c oauth -F

# Error: single-credential CLI
notion auth login --credential-type api_key  # Error: only valid for multi-credential CLIs
```

**Note:** This flag is automatically provided by `create_auth_app()` in `cli-tools-shared`. No per-CLI implementation needed.

Example implementation:
```python
@app.command("login")
def auth_login(
    force: bool = typer.Option(False, "--force", "-F", help="Clear existing session and re-authenticate"),
):
    """Login to service."""
    config = get_config()

    # Clear existing session if --force is specified
    if force:
        config.clear_session()  # or clear_credentials() for API type
        print_info("Existing session cleared")

    # Continue with normal login flow...
```

## Wrapper CLI Authentication (CONDITIONAL)

**Wrapper CLIs that wrap authenticated services MUST mount `create_auth_app` like every other CLI.** Hand-rolling a `subprocess`-driven `auth` command group is disallowed — the only approved pattern is a `Config.test_connection()` method that subprocesses the upstream CLI and parses its `{profiles: [...]}` JSON, paired with a `login_handler` that subprocesses the upstream `auth login`.

Wrapper CLIs that wrap local tools with no auth (e.g., `cliclick`, `ffmpeg`, `imagemagick`) should use `--auth-type none` and skip auth entirely.

**When to skip auth entirely:**
- Use `--auth-type none` when scaffolding
- The underlying CLI has no authentication concept
- The wrapper is purely a convenience/formatting layer

**Hard rule (applies to every CLI, not just wrappers):** every `commands/auth.py` must be a thin `create_auth_app(...)` mount. Hand-rolled `@app.command("status")` / `@app.command("login")` / `@app.command("logout")` functions are disallowed unless the CLI is genuinely exceptional (document the exception when introducing it).

**Wrapper pattern (recommended):**

1. `config.py` — `Config(BaseConfig)` with a `test_connection()` that shells out to the upstream CLI, parses its new-shape `{profiles: [...]}` JSON, and returns a dict whose fields will land inside `credential_types.custom` (or the matching type) in the wrapper's own `auth status` output.
2. `commands/auth.py` — 4-line `create_auth_app(get_config, tool_name="<name>", login_handler=_subprocess_upstream_login)` mount. The `login_handler` subprocesses the upstream `auth login`; the rest (status, logout, profiles, refresh) is free.

**Reference:** see `n8n-cli-tool-node-converter` once its migration to `create_auth_app` lands for the canonical wrapper-subprocess pattern. Until then, `notion_cli/commands/auth.py` shows the minimal `create_auth_app` mount, and `google_cli/commands/auth.py` shows a custom `login_handler` mounted via the same `create_auth_app` factory.

---

## OAuth Login Flow Standard

**PREFERRED:** Use the **built-in OAuth handler** from `cli-tools-shared` by setting `OAUTH_*` class variables on your Config subclass. This provides the complete auth code flow (browser, code capture, token exchange, refresh) with zero custom auth code.

### Built-in OAuth Handler (Recommended)

Set `OAUTH_*` class variables on your Config subclass. The `create_auth_app()` auto-detects these and uses the built-in `oauth_login` handler:

```python
from cli_tools_shared.config import BaseConfig
from cli_tools_shared.credentials import CredentialType

class Config(BaseConfig):
    CREDENTIAL_TYPE = CredentialType.OAUTH_AUTHORIZATION_CODE
    DEFAULT_BASE_URL = "https://api.example.com"

    # OAuth 2.0 configuration
    OAUTH_AUTH_URL = "https://auth.example.com/oauth2/authorize"
    OAUTH_TOKEN_URL = "https://auth.example.com/oauth2/token"
    OAUTH_SCOPES = ["read", "write"]
    OAUTH_TOKEN_AUTH = "basic"  # "basic" | "body" | "none"
    # Optional:
    # OAUTH_PKCE = True                    # Enable PKCE (S256)
    # OAUTH_STATE = True                   # Generate + verify state param
    # OAUTH_REDIRECT_URI = "https://..."   # Default (overridable via .env REDIRECT_URI)
    # OAUTH_EXTRA_AUTH_PARAMS = {}         # Extra auth URL params
```

For environment-dependent URLs (e.g., sandbox vs production), use `@property` overrides:
```python
@property
def OAUTH_AUTH_URL(self):
    return f"{self.auth_base_url}/oauth2/authorize"

@property
def OAUTH_TOKEN_URL(self):
    return f"{self.api_base_url}/identity/v1/oauth2/token"
```

**Auth commands provided automatically:**
- `auth login [--force] [--profile]` — full browser OAuth flow
- `auth logout [--profile]` — clear credentials
- `auth status [--table] [--profile]` — show auth status
- `auth refresh [--profile]` — refresh access token using refresh token

**Token management in client.py** — use `TokenManager`:
```python
from cli_tools_shared.token_manager import TokenManager

class MyClient:
    def __init__(self):
        self.config = get_config()
        self.tokens = TokenManager(self.config, on_refresh=self._update_headers)

    def _request(self, method, url, **kwargs):
        self.tokens.ensure_valid()  # auto-refresh if expired
        headers = {"Authorization": f"Bearer {self.config.access_token}"}
        resp = requests.request(method, url, headers=headers, **kwargs)
        if resp.status_code == 401:
            self.tokens.force_refresh()
            headers["Authorization"] = f"Bearer {self.config.access_token}"
            resp = requests.request(method, url, headers=headers, **kwargs)
        return resp
```

**Token auth modes (`OAUTH_TOKEN_AUTH`):**
| Mode | Behavior | Use When |
|------|----------|----------|
| `"basic"` | `Authorization: Basic base64(client_id:client_secret)` | eBay, most OAuth providers |
| `"body"` | `client_id` + `client_secret` in POST form data | FreshBooks, some providers |
| `"none"` | `client_id` only in POST data (public client) | PKCE flows, Kick |

**Handler priority (3-way resolution in `create_auth_app`):**
1. Explicit `login_handler` param — always wins (Bricklink OAuth 1.0a, dual-auth CLIs)
2. Config has `OAUTH_AUTH_URL` + `OAUTH_TOKEN_URL` — built-in `oauth_login`
3. Neither — default prompt-based login (API_KEY, PAT, USERNAME_PASSWORD)

### Extending the Built-in Handler

For CLIs that need OAuth + custom logic (e.g., OAuth + browser session):

```python
from cli_tools_shared.oauth import oauth_login

def my_login_handler(config, force):
    oauth_login(config, force)          # Standard OAuth flow
    browser = get_browser()
    browser.login(force=force)          # Custom post-login logic

app = create_auth_app(get_config, tool_name="myservice", login_handler=my_login_handler)
```

### Manual OAuth (Legacy / Fallback)

If the built-in handler doesn't fit, implement the flow manually. The `auth login` command **must** handle both direct codes and redirect URLs:

1. **Open browser** for authorization URL
2. **Interactively prompt** user for input
3. **Accept either** the authorization code directly or the full redirect URL
4. **Auto-detect input type** and URL-decode if needed
5. **Exchange code** for tokens

Use `extract_code_from_input()` from `cli_tools_shared.oauth` for code extraction:
```python
from cli_tools_shared.oauth import extract_code_from_input

code = extract_code_from_input(user_input)  # Handles both code and URL
```

**User Experience:**

```
$ mytool auth login
Opening browser for authorization...

If browser doesn't open, visit:
https://auth.example.com/oauth2/authorize?client_id=xxx&...

After authorizing, you'll be redirected.
Paste the authorization code OR the full redirect URL below:

Code or URL: https://mysite.com/?code=v%5E1.1%23i%5E1%23...&expires_in=299
Authentication successful! Tokens saved.
```
