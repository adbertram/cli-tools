# Browser Automation Architecture

## System Overview

Browser automation in cli-tools-shared follows a layered architecture where CLI tools provide minimal declarative configuration and the shared package handles all auth lifecycle, session management, and verification.

```
CLI Tool (minimal)          cli-tools-shared (all logic)
─────────────────          ──────────────────────────────
browser.py                  BrowserAutomation
  5 class constants    →      is_authenticated()
  __init__ only               authenticate()
                              login() / clear_session()
                              get_page() / close()

config.py                   BaseConfig
  get_browser()        →      has_credentials()
  CREDENTIAL_TYPES            has_saved_session()
                              get_browser_data_dir()
                              clear_session() / clear_ephemeral()

main.py                     auth_commands.py
  create_auth_app()    →      auth login (+ _handle_browser_login)
  test_handler               auth logout (+ browser.clear_session)
                              auth status (+ AuthVerifier)
                              auth test (+ AuthVerifier)

                            auth_verifier.py
                              _check_browser()
                              → config.get_browser().is_authenticated()
```

## Class Hierarchy

### BrowserAutomation (base class)

**Location:** `cli_tools_shared/auth.py`

All browser CLIs subclass this. It wraps `BrowserHarnessService` into a high-level auth lifecycle.

**Key public methods:**

| Method | Returns | Description |
|--------|---------|-------------|
| `is_authenticated()` | `AuthResult` | Live headless check with TTL caching (300s) |
| `authenticate(force)` | None | Interactive headed login, polls until detected |
| `login(force)` | `dict` | Calls authenticate(), returns `{"success": bool}` |
| `get_page(url)` | `BrowserHarnessService` | Opens/reuses headless browser, navigates to url |
| `has_session()` | `bool` | Checks if profile.json marker file exists |
| `clear_session()` | None | Removes marker file + clears browser session data |
| `test_session()` | `dict` | Headless verify: loads AUTH_CHECK_URL, calls _check_auth() |
| `close()` | None | Closes browser via BrowserHarnessService.browser_close() |

**Auth check priority** (in `_check_auth()`):
1. Cookie patterns (`AUTH_COOKIE_PATTERNS`)
2. CSS selector (`AUTH_SUCCESS_SELECTOR`)
3. localStorage key (`AUTH_STORAGE_KEY`)
4. Success URL pattern (`AUTH_SUCCESS_URL`)
5. Not-on-login-page fallback (`AUTH_URL_PATTERN`)

### AuthVerifier

**Location:** `cli_tools_shared/auth_verifier.py`

Central verification service used by `auth status` and `auth test`. Performs live checks per credential type.

**Browser-specific flow:**
```python
def _check_browser(self) -> Optional[bool]:
    browser = self.config.get_browser()
    if browser is None:
        return None
    try:
        return bool(browser.is_authenticated())
    except Exception:
        return False
    finally:
        browser.close()
```

**Output fields for browser CLIs appear under `profiles[].credential_types.browser_session`:**
```json
{
  "profiles": [
    {
      "authenticated": true,
      "credential_types": {
        "browser_session": {
          "authenticated": true,
          "credentials_saved": true,
          "browser_session": true
        }
      }
    }
  ]
}
```

`browser_session` is ONLY present when `CredentialType.BROWSER_SESSION` is in the config's credential types.

### BaseConfig (browser-related)

**Location:** `cli_tools_shared/config.py`

| Method | Description |
|--------|-------------|
| `get_browser()` | Returns None by default. Override to return BrowserAutomation subclass. |
| `get_browser_data_dir()` | Returns `~/.local/share/cli-tools/<tool>/.profiles/<profile>/browser-data/` |
| `has_saved_session()` | True if `profile.json` marker exists |
| `has_credentials()` | For BROWSER_SESSION: requires `has_saved_session()` |
| `clear_session()` | `shutil.rmtree` on profile directory |
| `clear_ephemeral()` | Clears tokens AND calls `clear_session()` |

### BrowserHarnessService

**Location:** `cli_tools_shared/browser/driver.py`

Low-level browser-harness/Chrome CDP wrapper. BrowserAutomation uses this internally. CLI tools should NEVER interact with BrowserHarnessService directly.

Key operations: `browser_open()`, `browser_close()`, `goto()`, `evaluate()`, `cookie_list()`, `wait_for_selector()`, `data_delete()`.

## CredentialType.BROWSER_SESSION

**Properties:**
- `required_fields` → `[]` (no env vars needed)
- `all_fields` → `["BASE_URL"]`
- `login_prompts` → `[]` (no interactive prompts)
- `ephemeral_fields` → `[]`

Credential validity is determined purely by `has_saved_session()` (profile.json marker exists).

## Auth Command Flow

### auth login
1. If `--credential-type browser_session`: calls `_handle_browser_login()` directly
2. Otherwise: prompts for credential fields, then calls `_handle_browser_login()` at end
3. `_handle_browser_login()` calls `browser.is_authenticated()` → if not auth'd, calls `browser.login(force)`
4. Always calls `browser.close()` in finally block

### auth logout
1. Calls `config.clear_credentials()` (clears env vars)
2. Calls `browser.clear_session()` (wipes browser session data + marker)
3. Calls `browser.close()` in finally block

### auth status
1. Creates `AuthVerifier(config)`
2. Calls `verifier.verify()` → includes `credential_types.browser_session.browser_session: true/false`
3. Returns JSON with `profiles[].authenticated` and browser results under `profiles[].credential_types.browser_session`

### auth test
1. Creates `AuthVerifier(config, api_test_handler=test_handler)`
2. Calls `verifier.verify()` → runs test_handler AND browser check
3. Returns JSON with full verification results

## Profile Data Directory

```
~/.local/share/cli-tools/<tool>/
  .profiles/
    <profile_name>/
      .env                    # Profile environment variables
      browser-data/           # Persistent browser data (managed by BrowserHarnessService)
      profile.json            # Marker file (written after successful login)
```

The marker file `profile.json` is the single source of truth for "has a browser session been established."
