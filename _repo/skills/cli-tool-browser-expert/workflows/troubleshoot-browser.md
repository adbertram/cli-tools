# Troubleshoot Browser Auth Issues

<required_reading>
- references/hooks-reference.md — Auth detection hooks and selector guidelines
- references/architecture.md — Auth flow and data flow
</required_reading>

<process>

## Step 1: Identify the Symptom

Common symptoms and their likely causes:

| Symptom | Likely Cause | Jump To |
|---------|-------------|---------|
| `profiles[].authenticated: false` but user is logged in | Bad `AUTH_SUCCESS_SELECTOR` | Step 2 |
| `profiles[].authenticated: true` but user is NOT logged in | Stale session marker | Step 3 |
| `auth login` opens browser but doesn't detect login | `AUTH_URL_PATTERN` or `AUTH_SUCCESS_SELECTOR` wrong | Step 4 |
| `auth logout` doesn't fully clear session | Missing `browser.clear_session()` in logout | Step 5 |
| `browser_session` field missing from `auth status` | `get_browser()` not implemented or returns None | Step 6 |
| Timeout during `is_authenticated()` | Page not loading, selector never appears | Step 7 |

## Step 2: False Negative — `profiles[].authenticated: false` When Logged In

This is the most common issue. The selector is wrong.

**Debug steps:**
1. Check current selector:
   ```bash
   grep AUTH_SUCCESS_SELECTOR <cli_dir>/<cli_name>_cli/browser.py
   ```

2. Navigate to the auth check URL and take a snapshot:
   ```bash
   playwright-cli page goto "<AUTH_CHECK_URL>" -s=<SESSION_NAME>
   playwright-cli page snapshot -s=<SESSION_NAME>
   ```

3. Look for the selector in the snapshot. Common problems:
   - Element exists in DOM but is **hidden** (collapsed sidebar, mobile menu)
   - Element is **lazy-loaded** (avatar images, profile pictures)
   - Element only appears **after JavaScript hydration**
   - Selector is **too specific** (includes dynamic IDs or classes)

4. Choose a better selector:
   - Target main content area elements (headings, nav items)
   - Use `playwright-cli page locator "<selector>" -s=<SESSION_NAME>` to test
   - Verify with `playwright-cli page evaluate "document.querySelector('<selector>').offsetParent !== null" -s=<SESSION_NAME>` — must return true (visible)

5. Update `AUTH_SUCCESS_SELECTOR` in browser.py and re-test:
   ```bash
   <cli_name> auth status
   ```

## Step 3: False Positive — `profiles[].authenticated: true` When NOT Logged In

**Debug steps:**
1. Check if profile.json marker exists:
   ```bash
   ls ~/.local/share/cli-tools/<cli_name>/.profiles/default/profile.json
   ```

2. If marker exists but session is expired, the session data is stale:
   ```bash
   <cli_name> auth logout   # Clear everything
   <cli_name> auth status   # Should show profiles[].authenticated: false
   ```

3. If `is_authenticated()` returns true even without marker, check:
   - Is `AUTH_CHECK_TTL` too high? Cached results may be stale.
   - Is the auth check URL redirecting to a public page?

## Step 4: Login Detection Failure

**Debug steps:**
1. Check `AUTH_URL_PATTERN` — does it match the actual login URL?
   ```bash
   # Open browser headed
   <cli_name> auth login --force
   # Check what URL the browser navigates to
   ```

2. If the site uses a third-party auth provider (LEGO ID, Google, etc.), the URL pattern needs to include both:
   ```python
   AUTH_URL_PATTERN = r"/login|identity\.provider\.com|accounts\.google\.com"
   ```

3. After login, check if `AUTH_SUCCESS_SELECTOR` appears on the redirected page:
   ```bash
   playwright-cli page snapshot -s=<SESSION_NAME>
   ```

## Step 5: Logout Not Clearing Session

**Verify the common package handles this:**
```python
# auth_commands.py auth_logout should:
# 1. config.clear_credentials()
# 2. browser.clear_session()  → removes marker + session data
# 3. browser.close()
```

If using an old version of cli-tools-shared, update:
```bash
cd <cli-tools-root>/<cli_name>
pip install --force-reinstall --no-deps <cli-tools-root>/_repo/cli-tools-shared
```

## Step 6: Missing `browser_session` Field

This means `AuthVerifier._check_browser()` returned None.

**Check chain:**
1. Does config have `CredentialType.BROWSER_SESSION`?
   ```bash
   grep CREDENTIAL_TYPES <cli_dir>/<cli_name>_cli/config.py
   ```

2. Does `get_browser()` return a BrowserAutomation instance (not None)?
   ```bash
   grep "def get_browser" <cli_dir>/<cli_name>_cli/config.py
   ```

3. Is cli-tools-shared up to date (has AuthVerifier)?
   ```bash
   python -c "from cli_tools_shared.auth_verifier import AuthVerifier; print('OK')"
   ```

## Step 7: Timeout Issues

If `is_authenticated()` hangs:

1. The page may not be loading. Check manually:
   ```bash
   playwright-cli page goto "<AUTH_CHECK_URL>" -s=<SESSION_NAME> --headed
   ```

2. Check for stale Playwright locks:
   ```bash
   # BrowserHarnessService owns the running Chrome session, but check:
   ls ~/Library/Caches/ms-playwright/daemon/<SESSION_NAME>/SingletonLock
   ```

3. Try deleting the session and re-authenticating:
   ```bash
   <cli_name> auth logout
   <cli_name> auth login
   ```

</process>

<success_criteria>
- Root cause identified with evidence (not speculation)
- Fix applied to the correct layer (constants, not custom methods)
- `auth status` returns correct `browser_session` value
- `auth login` / `auth logout` cycle works end-to-end
</success_criteria>
