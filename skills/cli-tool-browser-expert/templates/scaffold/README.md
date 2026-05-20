# Browser CLI Scaffold — File Inventory

This scaffold shows all files needed for a compliant browser CLI.
Replace `{{ServiceName}}`, `{{cli_name}}`, and `{{domain}}` with actual values.

## Files

| File | Lines | Purpose |
|------|-------|---------|
| `browser.py` | ~15 | BrowserAutomation subclass with 5 class constants |
| `config.py` | ~50 | BaseConfig subclass with `get_browser()`, CREDENTIAL_TYPES |
| `main.py` | ~70 | Typer app with `create_auth_app()`, test_handler |
| `client.py` | ~50 | Domain logic using `get_page()` for page automation |

## What Each File Does vs Doesn't Do

### browser.py
- **DOES:** Declare `SESSION_NAME`, `LOGIN_URL`, `AUTH_CHECK_URL`, `AUTH_URL_PATTERN`, `AUTH_SUCCESS_SELECTOR`
- **DOESN'T:** Implement `is_authenticated()`, `login()`, `clear_session()`, `_check_auth()`, or any auth methods

### config.py
- **DOES:** Extend `BaseConfig`, set `CREDENTIAL_TYPES`, implement `get_browser()`
- **DOESN'T:** Manage browser sessions, check auth state, clear sessions

### main.py
- **DOES:** Use `create_auth_app()` with a `_test_handler`, register standard subcommands
- **DOESN'T:** Create custom auth login/logout/status commands

### client.py
- **DOES:** Use `get_page(url)` for page navigation, implement domain methods
- **DOESN'T:** Call `is_authenticated()`, `login()`, or do any session management

## Auth Lifecycle (handled entirely by cli-tools-common)

```
User runs `auth login`
  → create_auth_app.auth_login()
    → _handle_browser_login(config, tool_name, force)
      → config.get_browser()  → browser.py instance
      → browser.is_authenticated()  → BrowserAutomation._check_auth()
      → browser.login(force)  → BrowserAutomation.authenticate()
      → browser.close()

User runs `auth status`
  → create_auth_app.auth_status()
    → AuthVerifier(config).verify()
      → AuthVerifier._check_browser()
        → config.get_browser().is_authenticated()
        → browser.close()
    → returns {"profiles": [{"authenticated": bool, "credential_types": {"browser_session": {"browser_session": bool, ...}}}]}

User runs `auth logout`
  → create_auth_app.auth_logout()
    → config.clear_credentials()
    → config.get_browser().clear_session()  → removes marker + session data
    → browser.close()
```
