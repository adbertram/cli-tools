# OAuth Migration Guide: Custom Auth → Built-in Handler

How to convert a CLI tool from custom OAuth auth code to the built-in `oauth_login` handler and `TokenManager` from `cli-tools-shared`.

## What You're Replacing

The built-in handler eliminates three categories of custom code:

| Category | Custom Code | Built-in Replacement |
|----------|-------------|---------------------|
| **Login flow** | `_extract_code_from_input()`, `_exchange_code_for_tokens()`, `login_handler()` | `OAUTH_*` class vars on Config → auto-detected by `create_auth_app()` |
| **Token refresh** | `_is_token_expired()`, `_refresh_token()` in client.py | `TokenManager(config)` with `is_expired()`, `ensure_valid()`, `force_refresh()` |
| **Auth commands** | Custom `typer.Typer` app with manual login/status/logout/refresh | `create_auth_app(get_config, tool_name="x")` — all 4 commands provided |

## Pre-Migration Checklist

Before starting, identify which pattern your CLI uses:

| Pattern | How to Identify | Migration Path |
|---------|----------------|----------------|
| **Standard OAuth** (eBay) | `Authorization: Basic` header on token exchange, manual code paste | Set `OAUTH_TOKEN_AUTH = "basic"`, remove handler |
| **Body auth** (FreshBooks) | `client_id`/`client_secret` in POST body | Set `OAUTH_TOKEN_AUTH = "body"` |
| **PKCE public client** (Kick) | `code_verifier`/`code_challenge`, no client_secret in token exchange | Set `OAUTH_PKCE = True`, `OAUTH_TOKEN_AUTH = "none"` |
| **SDK-managed** (Google, Dropbox) | Uses google-auth, dropbox SDK for token lifecycle | **Do not migrate** — keep SDK handling |
| **OAuth 1.0a** (Bricklink) | Signature-based auth, nonce, timestamp | **Do not migrate** — keep custom handler |

**Do NOT migrate if:**
- Auth is managed by a third-party SDK (Google, Dropbox, Podio, Slack)
- The CLI uses OAuth 1.0a (Bricklink)
- The CLI uses client credentials flow without user interaction (USPS, FedEx)
- The CLI has a completely custom token source (Descript JWT extraction)

---

## Migration Steps

### Step 1: Update Config — Add OAUTH_* Class Variables

Open your CLI's `config.py` and add `OAUTH_*` class variables to the Config class.

**Mapping your existing code to class vars:**

Find in your current auth.py or client.py | Set on Config
---|---
Auth URL (e.g., `https://auth.example.com/authorize`) | `OAUTH_AUTH_URL`
Token URL (e.g., `https://api.example.com/oauth/token`) | `OAUTH_TOKEN_URL`
Scopes list | `OAUTH_SCOPES`
Default redirect URI | `OAUTH_REDIRECT_URI`
Uses PKCE (`code_verifier`, `code_challenge`) | `OAUTH_PKCE = True`
Generates state parameter | `OAUTH_STATE = True`
Uses `Authorization: Basic` header for token exchange | `OAUTH_TOKEN_AUTH = "basic"`
Sends `client_id`/`client_secret` in POST body | `OAUTH_TOKEN_AUTH = "body"`
No client_secret (public client) | `OAUTH_TOKEN_AUTH = "none"`
Extra auth URL params (e.g., `audience`) | `OAUTH_EXTRA_AUTH_PARAMS = {"audience": "..."}`
**Static values** — set as class variables:
```python
class Config(BaseConfig):
    OAUTH_AUTH_URL = "https://auth.example.com/authorize"
    OAUTH_TOKEN_URL = "https://api.example.com/oauth/token"
    OAUTH_SCOPES = ["read", "write"]
    OAUTH_TOKEN_AUTH = "body"
```

**Dynamic values** (e.g., environment-dependent URLs) — use `@property` overrides:
```python
class Config(BaseConfig):
    @property
    def OAUTH_AUTH_URL(self):
        return f"{self.auth_base_url}/oauth2/authorize"

    @property
    def OAUTH_TOKEN_URL(self):
        return f"{self.api_base_url}/identity/v1/oauth2/token"
```

**If your Config doesn't extend BaseConfig** (e.g., Kick), you must also migrate the Config class itself. See [Step 1b: Migrate Config to BaseConfig](#step-1b-migrate-config-to-baseconfig).

#### Step 1b: Migrate Config to BaseConfig

If your CLI has a standalone Config class (not extending `BaseConfig`), rewrite it:

**Before (Kick — standalone Config, 116 lines):**
```python
class Config:
    def __init__(self):
        config_dir = Path(__file__).resolve().parent.parent
        cli_env_path = config_dir / ".env"
        self.env_file_path = cli_env_path
        if cli_env_path.exists():
            load_dotenv(cli_env_path, override=True)

    @property
    def access_token(self):
        return os.getenv("KICK_ACCESS_TOKEN")  # ❌ Service-prefixed

    def save_tokens(self, access_token, refresh_token, expires_at):
        set_key(str(self.env_file_path), "KICK_ACCESS_TOKEN", access_token)  # ❌ Manual
        ...

    def clear_credentials(self):
        set_key(str(self.env_file_path), "KICK_ACCESS_TOKEN", "")  # ❌ Manual
        ...
```

**After (BaseConfig subclass, ~25 lines):**
```python
from cli_tools_shared.config import BaseConfig
from cli_tools_shared.credentials import CredentialType

class Config(BaseConfig):
    CREDENTIAL_TYPE = CredentialType.OAUTH_AUTHORIZATION_CODE
    DEFAULT_BASE_URL = "https://use.kick.co"

    OAUTH_AUTH_URL = "https://auth.kick.co/authorize"
    OAUTH_TOKEN_URL = "https://auth.kick.co/oauth/token"
    OAUTH_SCOPES = ["openid", "profile", "email", "offline_access"]
    OAUTH_PKCE = True
    OAUTH_STATE = True
    OAUTH_TOKEN_AUTH = "none"
    OAUTH_REDIRECT_URI = "https://use.kick.co"
    OAUTH_EXTRA_AUTH_PARAMS = {"audience": "https://use.kick.co"}

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=Path(__file__).resolve().parent.parent,
            profile=profile,
        )
```

**What BaseConfig provides for free:**
- `access_token`, `refresh_token`, `token_expires_at`, `client_id`, `client_secret`, `redirect_uri` properties
- `save_tokens()`, `clear_credentials()`, `has_credentials()`, `get_missing_credentials()`
- Profile support (`.env.staging`, `--profile` flag)
- `_get()`, `_set()`, `_clear()` for custom env vars

**Env var rename:** If your `.env` uses service-prefixed vars (e.g., `KICK_ACCESS_TOKEN`), rename them to generic names (`ACCESS_TOKEN`). BaseConfig reads generic names.

**Custom properties** you still need (e.g., `account_id`, `auth0_domain`) stay as `@property` methods using `self._get("ACCOUNT_ID")`.

---

### Step 2: Replace Auth Commands

**Before (FreshBooks — 196 lines of custom auth):**
```python
app = typer.Typer(help="Manage FreshBooks API authentication")

def _get_auth_code_from_browser(auth_url, redirect_uri, timeout=120):
    # 26 lines of Playwright code...

@app.command("login")
def auth_login(profile, force):
    # 63 lines building auth URL, calling Playwright, exchanging tokens...

@app.command("logout")
def auth_logout(profile):
    # 12 lines...

@app.command("status")
def auth_status(profile, table):
    # 47 lines...
```

**After (4 lines):**
```python
from cli_tools_shared.auth_commands import create_auth_app
from ..config import get_config

app = create_auth_app(get_config, tool_name="freshbooks")
```

That's it. The `create_auth_app` factory:
1. Detects `OAUTH_AUTH_URL` + `OAUTH_TOKEN_URL` on your Config
2. Auto-uses the built-in `oauth_login` handler
3. Provides `login`, `logout`, `status`, and `refresh` commands

**Delete from auth.py:**
- All `import` statements for requests, base64, webbrowser, Playwright, etc.
- `_extract_code_from_input()`
- `_exchange_code_for_tokens()`
- `_get_auth_code_from_browser()` (Playwright)
- `login_handler()` / `ebay_login_handler()` / etc.
- All `@app.command` definitions (login, logout, status, refresh)
- Module-level constants like `FRESHBOOKS_AUTH_URL`, `FRESHBOOKS_TOKEN_URL`

**Keep in auth.py:** Nothing besides the `create_auth_app` call. All OAuth config lives on the Config class now.

---

### Step 3: Replace Token Management in Client

**Before (eBay client.py — 60 lines of token management):**
```python
import base64
from datetime import datetime

class EbayClient:
    SCOPES = [...]  # ❌ Scopes on client (should be on Config)

    def __init__(self):
        self.config = get_config()
        self._update_headers()

    def _is_token_expired(self) -> bool:
        expires_at = self.config.token_expires_at
        if not expires_at:
            return True
        try:
            expires_timestamp = float(expires_at)
            return datetime.now().timestamp() > (expires_timestamp - 300)
        except (ValueError, TypeError):
            return True

    def _refresh_token(self):
        refresh_token = self.config.refresh_token
        if not refresh_token:
            raise ClientError("No refresh token available...")
        credentials = f"{self.config.client_id}:{self.config.client_secret}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        # ... 20+ more lines of HTTP request, error handling, saving tokens
```

**After (2 lines in `__init__`, 0 custom methods):**
```python
from cli_tools_shared.token_manager import TokenManager

class EbayClient:
    def __init__(self):
        self.config = get_config()
        self.tokens = TokenManager(self.config, on_refresh=self._update_headers)
        self._update_headers()
```

**Replace all call sites:**

| Before | After |
|--------|-------|
| `self._is_token_expired()` | `self.tokens.is_expired()` |
| `self._refresh_token()` | `self.tokens.force_refresh()` |
| `if self._is_token_expired(): self._refresh_token()` | `self.tokens.ensure_valid()` |

**The `on_refresh` callback** is called after `force_refresh()` saves new tokens. Use it if your client caches auth headers:

```python
# Client caches headers → needs callback to update them
self.tokens = TokenManager(self.config, on_refresh=self._update_headers)

# Client reads config.access_token per-request → no callback needed
self.tokens = TokenManager(self.config)
```

**Delete from client.py:**
- `_is_token_expired()` method
- `_refresh_token()` method
- `import base64` (if only used for token refresh)
- `from datetime import datetime` (if only used for token expiry check)
- `SCOPES` class variable (move to `Config.OAUTH_SCOPES`)

**Keep in client.py:**
- `_update_headers()` — still needed for per-request header construction
- `_make_request()` — still needed, just replace the token method calls
- All API methods — unchanged

---

### Step 4: Move Scopes to Config

If scopes are defined on the client class, move them to Config:

**Before (client.py):**
```python
class EbayClient:
    SCOPES = ["https://api.ebay.com/oauth/api_scope/sell.fulfillment", ...]
```

**After (config.py):**
```python
class Config(BaseConfig):
    OAUTH_SCOPES = ["https://api.ebay.com/oauth/api_scope/sell.fulfillment", ...]
```

**Update references:** Search for `ClientClass.SCOPES` and replace with `Config.OAUTH_SCOPES` (or `self.config.OAUTH_SCOPES` inside the client).

---

### Step 5: Update main.py (if needed)

Usually no changes needed in main.py — it already imports and registers `auth.app`. But check for:

- References to `ClientClass.SCOPES` (update to `Config.OAUTH_SCOPES`)
- References to deleted auth functions

---

### Step 6: Reinstall and Verify

```bash
# 1. Reinstall the CLI through the standard installer.
#    This refreshes the uv tool venv and overlays the live cli-tools-shared repo.
<cli-tools-root>/_repo/skills/cli-tool/scripts/install-cli-tool.sh cli-name

# 2. Verify CLI loads
cli-name --help

# 3. Verify auth commands
cli-name auth --help          # Should show: login, logout, status, refresh
cli-name auth status          # Should show authenticated status
cli-name auth refresh         # Should refresh token
cli-name auth login --help    # Should show --force/-F and --profile/-p

# 4. Verify API calls work (proves token + refresh path)
cli-name <some-list-command> --limit 1
```

---

## Complete Examples

### Example A: eBay (Standard OAuth, Basic auth)

**Before:** 142 lines custom auth + 60 lines token management = 202 lines
**After:** 15 lines auth.py + 2 lines in client `__init__` = 17 lines

**config.py changes:**
```python
class Config(BaseConfig):
    CREDENTIAL_TYPE = CredentialType.OAUTH_AUTHORIZATION_CODE
    DEFAULT_BASE_URL = "https://api.ebay.com"

    # ADD these:
    OAUTH_SCOPES = [
        "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
        "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
        # ...
    ]
    OAUTH_TOKEN_AUTH = "basic"

    @property
    def OAUTH_AUTH_URL(self):
        return f"{self.auth_base_url}/oauth2/authorize"

    @property
    def OAUTH_TOKEN_URL(self):
        return f"{self.api_base_url}/identity/v1/oauth2/token"
```

**auth.py (complete replacement):**
```python
from cli_tools_shared.auth_commands import create_auth_app
from ..config import get_config

app = create_auth_app(get_config, tool_name="ebay")
```

**client.py changes:**
```python
# ADD:
from cli_tools_shared.token_manager import TokenManager

class EbayClient:
    # DELETE: SCOPES = [...]

    def __init__(self, ...):
        self.config = get_config()
        # ADD:
        self.tokens = TokenManager(self.config, on_refresh=self._update_headers)
        self._update_headers()

    # DELETE: _is_token_expired()
    # DELETE: _refresh_token()

    def _make_request(self, ...):
        # REPLACE: if self._is_token_expired():
        if self.tokens.is_expired():
            try:
                # REPLACE: self._refresh_token()
                self.tokens.force_refresh()
            except Exception:
                pass

        # ... in 401 handler:
        if response.status_code == 401:
            try:
                # REPLACE: self._refresh_token()
                self.tokens.force_refresh()
```

### Example B: FreshBooks (body auth)

**Before:** 196 lines custom auth + 48 lines token management = 244 lines
**After:** 4 lines auth.py + 2 lines in client `__init__` = 6 lines

**config.py changes:**
```python
class Config(BaseConfig):
    CREDENTIAL_TYPE = CredentialType.OAUTH

    # ADD these:
    OAUTH_AUTH_URL = "https://my.freshbooks.com/service/auth/oauth/authorize"
    OAUTH_TOKEN_URL = "https://api.freshbooks.com/auth/oauth/token"
    OAUTH_TOKEN_AUTH = "body"
    OAUTH_REDIRECT_URI = "https://localhost/callback"
```

**auth.py (complete replacement):**
```python
from cli_tools_shared.auth_commands import create_auth_app
from ..config import get_config

app = create_auth_app(get_config, tool_name="freshbooks")
```

**client.py changes:** Same pattern as eBay — add `TokenManager`, delete `_is_token_expired()` and `_refresh_token()`.

### Example C: Kick (PKCE + state, public client, needs BaseConfig migration)

**Before:** 337 lines custom auth + standalone Config (doesn't extend BaseConfig) + custom token methods
**After:** 4 lines auth.py + ~25 lines Config + 2 lines in client `__init__`

This is the most involved migration because Kick's Config doesn't extend BaseConfig and uses service-prefixed env vars.

**config.py (full rewrite):**
```python
from pathlib import Path
from cli_tools_shared.config import BaseConfig
from cli_tools_shared.credentials import CredentialType

class Config(BaseConfig):
    CREDENTIAL_TYPE = CredentialType.OAUTH_AUTHORIZATION_CODE
    DEFAULT_BASE_URL = "https://use.kick.co"

    OAUTH_AUTH_URL = "https://auth.kick.co/authorize"
    OAUTH_TOKEN_URL = "https://auth.kick.co/oauth/token"
    OAUTH_SCOPES = ["openid", "profile", "email", "offline_access"]
    OAUTH_PKCE = True
    OAUTH_STATE = True
    OAUTH_TOKEN_AUTH = "none"     # Public client, no client_secret
    OAUTH_REDIRECT_URI = "https://use.kick.co"
    OAUTH_EXTRA_AUTH_PARAMS = {"audience": "https://use.kick.co"}

    def __init__(self, profile=None):
        super().__init__(
            tool_dir=Path(__file__).resolve().parent.parent,
            profile=profile,
        )

_configs = {}

def get_config(profile=None):
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
```

**Env var rename (.env file):**
```
# Before:
KICK_ACCESS_TOKEN=...
KICK_REFRESH_TOKEN=...
KICK_TOKEN_EXPIRES_AT=...

# After:
ACCESS_TOKEN=...
REFRESH_TOKEN=...
TOKEN_EXPIRES_AT=...
ACTIVE=true
```

**auth.py (complete replacement):**
```python
from cli_tools_shared.auth_commands import create_auth_app
from ..config import get_config

app = create_auth_app(get_config, tool_name="kick")
```

**main.py update:** Register the auth app. `create_auth_app()` mounts profiles under `auth`:
```python
from .commands import auth

app.add_typer(auth.app, name="auth")
```

---

## Auth Modes Reference

### OAUTH_TOKEN_AUTH = "basic"

Token exchange sends `Authorization: Basic base64(client_id:client_secret)` header.

**Used by:** eBay, most standard OAuth providers.

```
POST /oauth/token
Authorization: Basic cGxBckVm...NjM5NTY=
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code&code=xxx&redirect_uri=https://...
```

### OAUTH_TOKEN_AUTH = "body"

Token exchange sends `client_id` and `client_secret` as POST form fields.

**Used by:** FreshBooks, some OAuth providers that don't accept Basic auth.

```
POST /oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code&code=xxx&redirect_uri=https://...&client_id=xxx&client_secret=xxx
```

### OAUTH_TOKEN_AUTH = "none"

Token exchange sends only `client_id` in POST body (no secret). For public clients using PKCE.

**Used by:** Kick (Auth0 public client with PKCE).

```
POST /oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code&code=xxx&redirect_uri=https://...&client_id=xxx&code_verifier=xxx
```

---

## PKCE Flow Details

When `OAUTH_PKCE = True`, the built-in handler:

1. Generates a random `code_verifier` (128-char URL-safe string)
2. Creates `code_challenge` = base64url(SHA256(code_verifier))
3. Adds `code_challenge` and `code_challenge_method=S256` to the auth URL
4. Includes `code_verifier` in the token exchange POST

No custom code needed — just set the class var.

---

## Browser-Driven OAuth Capture

For OAuth providers whose redirect lands on a localhost or otherwise
unroutable URL, the OAuth handler can drive the browser through
`BrowserAutomation` (backed by `browser-harness`) to auto-capture the code,
rather than asking the user to paste it.

When this path is enabled, the handler:
1. Opens the OAuth authorization URL in a managed browser session.
2. Watches navigation for a request whose URL contains `code=` and matches
   the configured redirect host.
3. Extracts the `code` query parameter and closes the browser.
4. Continues with the token exchange.

If no such mechanism is exposed on `oauth.OAuthConfig` in your installed
`cli-tools-shared`, fall through to the default `webbrowser.open()` +
manual paste flow.

**Timeout:** Controlled by the handler's standard browser timeout (default
120 seconds).

**Dependency:** `browser-harness` (pulled in transitively via
`cli-tools-shared`). No separate install step.

---

## Composing the Built-in Handler

For CLIs that need OAuth + additional custom logic, provide a custom `login_handler` that calls the built-in `oauth_login` first:

```python
from cli_tools_shared.oauth import oauth_login

def my_login_handler(config, force):
    # Step 1: Standard OAuth flow (built-in)
    oauth_login(config, force)

    # Step 2: Custom post-login logic
    # e.g., fetch account ID, set up browser session, etc.
    response = requests.get(f"{config.base_url}/me",
        headers={"Authorization": f"Bearer {config.access_token}"})
    config._set("ACCOUNT_ID", response.json()["id"])

app = create_auth_app(get_config, tool_name="myservice", login_handler=my_login_handler)
```

This pattern lets you:
- Use the built-in OAuth flow (no re-implementing code capture, token exchange)
- Add service-specific post-login steps
- Still set `OAUTH_*` class vars for `TokenManager` and `auth refresh` to work

---

## Troubleshooting

### "No module named 'cli_tools_shared.token_manager'"

The uv tool venv has an old copy of cli-tools-shared. Reinstall:
```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/install-cli-tool.sh cli-name
```

### "Token refresh not supported (no OAUTH_TOKEN_URL configured)"

`auth refresh` requires `OAUTH_TOKEN_URL` on Config. If using `@property` overrides, ensure the property is accessible without requiring a loaded .env (i.e., it doesn't depend on env vars that may not be set yet).

### "No 'code' parameter found in URL"

The user pasted something that isn't a code or redirect URL. The built-in handler accepts both:
- Direct code: `v^1.1#i^1#...`
- Full redirect URL: `https://example.com/?code=v%5E1.1%23...`

### Token refresh works but client still gets 401

The client is caching old headers. Add `on_refresh` callback:
```python
self.tokens = TokenManager(self.config, on_refresh=self._update_headers)
```

### Playwright browser doesn't capture the redirect

Check that `OAUTH_REDIRECT_URI` matches what the OAuth provider redirects to. The Playwright handler watches for requests to the redirect URI's host containing `code=`.

---

## Custom Auth Handlers

For CLIs that don't fit the standard OAuth 2.0 pattern, `create_auth_app` provides extensibility points: `login_handler`, `AUTH_EXTRA_PROMPTS`, `get_browser()`, and `test_handler`.

### The `login_handler(config, force)` Contract

A custom login handler replaces the default prompt-based or OAuth login flow.

```python
def my_login_handler(config, force):
    """Custom login handler.

    Args:
        config: BaseConfig instance (credentials already prompted via login_prompts).
        force: True if --force flag was passed (re-authenticate even if valid).

    The handler is responsible for:
    - Obtaining and saving any additional tokens/credentials
    - Any custom authentication flow (browser, API calls, etc.)

    What create_auth_app does BEFORE calling the handler:
    - Prompts for standard credential fields (from CredentialType.login_prompts)
    - Prompts for AUTH_EXTRA_PROMPTS fields (if configured)

    What the handler does NOT need to do:
    - Prompt for CLIENT_ID, CLIENT_SECRET, etc. (already done)
    - Prompt for AUTH_EXTRA_PROMPTS fields (already done)
    """
    # Your custom auth logic here
    pass
```

**Handler priority (3-way resolution):**
1. Explicit `login_handler` param → always wins
2. Config has `OAUTH_AUTH_URL` + `OAUTH_TOKEN_URL` → built-in `oauth_login`
3. Neither → default prompt-based login

When a custom `login_handler` is provided, the shared package does NOT automatically handle browser login — the handler is responsible for its own browser flow if needed.

### `AUTH_EXTRA_PROMPTS` — Declarative Extra Fields

Add extra fields to the login prompt without writing a custom handler. Set on the Config class:

```python
class Config(BaseConfig):
    CREDENTIAL_TYPE = CredentialType.OAUTH  # Prompts CLIENT_ID, CLIENT_SECRET
    AUTH_EXTRA_PROMPTS = [
        ("ACCESS_TOKEN", "Token Value", False),    # (field_name, label, hide_input)
        ("REFRESH_TOKEN", "Token Secret", True),
    ]
```

**Behavior:**
- Prompted AFTER standard `login_prompts` (from CredentialType)
- Prompted BEFORE `login_handler` (if provided) or browser login
- Skipped if field already has a value (unless `--force`)
- Values saved to the `.env` file via `config._set()`

**Use case:** OAuth 1.0a CLIs where token value/secret are manually entered (not obtained via browser flow).

### `get_browser()` — Built-in Browser Session Login

Override `get_browser()` on your Config to automatically add browser session login to the auth flow.

```python
class Config(BaseConfig):
    def get_browser(self):
        """Return browser service for browser-based auth."""
        from .browser import get_browser
        return get_browser()
```

**Required protocol for the returned object:**

| Method | Signature | Purpose |
|--------|-----------|---------|
| `is_authenticated()` | `() -> bool` | Check if browser session is valid |
| `login(force)` | `(force: bool) -> dict` | Open browser for login, return `{"success": bool}` |
| `close()` | `() -> None` | Clean up browser resources |

**What the shared package handles automatically:**
- `auth login`: After credentials are saved, opens browser if `get_browser()` returns non-None. Skips if already authenticated (unless `--force`).
- `auth status`: Adds `browser_session: true/false` to status output.
- `auth test`: Adds `browser_session: true/false` to test results and factors it into the `authenticated` verdict.

**When a custom `login_handler` is provided:** The shared package does NOT automatically handle browser login — the handler manages its own browser flow. Use `get_browser()` only when you want the shared package to handle browser login for you.

### `test_handler` — Custom Auth Test Command

Provide a `test_handler` to `create_auth_app` to add an `auth test` command.

```python
def _test_handler(config):
    """Test API credentials by making a lightweight call.

    Args:
        config: BaseConfig instance.

    Returns:
        dict with at minimum {"api_test": "passed"|"failed: reason"}.
        Can include extra keys (e.g., "method") that appear in output.
    """
    from .client import MyClient
    client = MyClient()
    client.some_lightweight_call()
    return {"api_test": "passed", "method": "oauth2"}

app = create_auth_app(get_config, tool_name="myservice", test_handler=_test_handler)
```

**The shared package automatically adds to the test result:**
- `credentials_configured`: Whether required credentials exist
- `browser_session`: Browser auth status (if `get_browser()` configured)
- `authenticated`: Overall verdict (`api_test == "passed"` AND `browser_session` is True or not configured)

The CLI only provides the API-specific test. Everything else is free.

**`auth test` flags:**
- `--verbose` / `-v`: Adds `profile` and `base_url` to output
- `--table` / `-t`: Renders as table instead of JSON
- `--profile` / `-p`: Test a specific profile

### Patterns Summary

| Need | Solution | Custom Code |
|------|----------|-------------|
| Standard OAuth 2.0 | `OAUTH_*` class vars | None |
| OAuth 2.0 + post-login step | `OAUTH_*` vars + compose handler | ~5 lines |
| Extra credential fields | `AUTH_EXTRA_PROMPTS` | None |
| Browser session login | Override `get_browser()` | ~3 lines |
| Custom auth test | `test_handler` param | ~6 lines |
| Fully custom login | `login_handler` | Full handler |
| OAuth 1.0a + browser | `AUTH_EXTRA_PROMPTS` + `get_browser()` | ~3 lines (Bricklink pattern) |

### Real-World Examples

#### Bricklink (OAuth 1.0a + browser) — Zero Custom Handler

Bricklink uses OAuth 1.0a (manual token entry) + Playwright browser session. Previously required a 30-line custom `login_handler` + 50-line inline `auth test`. Now uses only declarative config:

**config.py:**
```python
class Config(BaseConfig):
    CREDENTIAL_TYPE = CredentialType.OAUTH          # Prompts CLIENT_ID, CLIENT_SECRET
    AUTH_EXTRA_PROMPTS = [                          # Also prompts token value/secret
        ("ACCESS_TOKEN", "Token Value", False),
        ("REFRESH_TOKEN", "Token Secret", True),
    ]

    def get_browser(self):                          # Browser session auto-handled
        from .browser import get_browser
        return get_browser()
```

**commands/auth.py:**
```python
from cli_tools_shared.auth_commands import create_auth_app
from ..config import get_config

def _test_handler(config):
    from ..client import BricklinkClient
    client = BricklinkClient()
    client.list_orders(direction="in")
    return {"api_test": "passed", "method": "oauth1_api"}

app = create_auth_app(get_config, tool_name="bricklink", test_handler=_test_handler)
```

**What happens during `bricklink auth login`:**
1. Common package prompts for Client ID, Client Secret (from OAUTH type)
2. Common package prompts for Token Value, Token Secret (from AUTH_EXTRA_PROMPTS)
3. Credentials saved to `.env`
4. Common package calls `config.get_browser()`, checks `is_authenticated()`
5. If not authenticated, opens browser for manual login

**What happens during `bricklink auth test`:**
1. Common package checks `config.has_credentials()` → `credentials_configured`
2. Calls `_test_handler(config)` → `api_test: "passed"`, `method: "oauth1_api"`
3. Common package calls `config.get_browser().is_authenticated()` → `browser_session`
4. Common package computes `authenticated = api_test passed AND browser_session`

#### Composing with `oauth_login`

For OAuth 2.0 CLIs that need a post-login custom step:

```python
from cli_tools_shared.oauth import oauth_login

def my_login_handler(config, force):
    # Step 1: Standard OAuth flow (built-in)
    oauth_login(config, force)

    # Step 2: Custom post-login logic
    response = requests.get(f"{config.base_url}/me",
        headers={"Authorization": f"Bearer {config.access_token}"})
    config._set("ACCOUNT_ID", response.json()["id"])

app = create_auth_app(get_config, tool_name="myservice", login_handler=my_login_handler)
```

#### Fully Custom Handler

When nothing else fits (rare — most cases are covered by the patterns above):

```python
def custom_login_handler(config, force):
    # CLIENT_ID and CLIENT_SECRET already prompted by create_auth_app
    # AUTH_EXTRA_PROMPTS already prompted by create_auth_app
    # You only need to handle the unique parts of your auth flow
    import requests
    response = requests.post("https://custom-auth.example.com/token", data={
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "custom_field": config._get("CUSTOM_FIELD"),
    })
    tokens = response.json()
    config.save_tokens(tokens["access_token"], tokens["refresh_token"], tokens["expires_at"])

app = create_auth_app(get_config, tool_name="custom", login_handler=custom_login_handler)
```
