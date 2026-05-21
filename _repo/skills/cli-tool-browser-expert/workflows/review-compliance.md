# Review Browser CLI Compliance

<required_reading>
- references/architecture.md — Expected patterns
- references/hooks-reference.md — What should/shouldn't be in browser.py
</required_reading>

<process>

## Step 1: Identify the CLI

If not provided, ask: "Which CLI tool should I review for browser compliance?"

Locate the CLI directory:
```
<cli-tools-root>/<cli_name>/<cli_name>_cli/
```

## Step 2: Check browser.py

Read `browser.py` and verify:

| Check | Pass Criteria |
|-------|--------------|
| Extends `BrowserAutomation` | `class X(BrowserAutomation)` |
| Has `SESSION_NAME` | Non-empty string |
| Has `LOGIN_URL` | Valid URL |
| Has `AUTH_CHECK_URL` | Valid URL |
| Has `AUTH_URL_PATTERN` | Valid regex |
| Has `AUTH_SUCCESS_SELECTOR` | Non-empty selector |
| No custom methods | Only `__init__` defined |
| `__init__` calls `super().__init__(config)` | Proper delegation |
| File is ~15 lines | Minimal code |

**Red flags:** Any `def` besides `__init__`, any import besides `BrowserAutomation` and `get_config`.

## Step 3: Check config.py

Read `config.py` and verify:

| Check | Pass Criteria |
|-------|--------------|
| Extends `BaseConfig` | `class Config(BaseConfig)` |
| Has `CREDENTIAL_TYPES` with `BROWSER_SESSION` | `CredentialType.BROWSER_SESSION` in list |
| Implements `get_browser()` | Returns BrowserAutomation subclass |
| Uses lazy import in `get_browser()` | `from .browser import X` inside method |
| Has `get_config()` factory | Module-level factory function |

## Step 4: Check main.py

Read `main.py` and verify:

| Check | Pass Criteria |
|-------|--------------|
| Uses `create_auth_app()` | From `cli_tools_shared.auth_commands` |
| Has `test_handler` | Function that calls `browser.test_session()` |
| No top-level `profiles` command | Profile management is under `auth profiles` from `create_auth_app()` |
| No custom auth commands | No manual `auth login`/`auth status`/etc. |

## Step 5: Scan for Forbidden Patterns

Search the entire CLI package for forbidden patterns:

```python
# These should NOT exist outside browser.py/config.py:
"def is_logged_in"
"def is_authenticated"
"def check_auth"
"def _ensure_logged_in"
"def verify_session"
"def check_session"
"def _check_browser_status"
"def check_browser_session"
"sync_playwright"
"async_playwright"
"launch_persistent_context"
"class BrowserService"
```

If ANY of these are found, they indicate duplicated logic that must be removed.

## Step 6: Run Automated Tests

```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name "<cli_name>" --command auth
```

Key tests that must pass:
- `test_browser_cli_has_browser_automation_subclass` — browser.py extends BrowserAutomation
- `test_browser_cli_config_has_get_browser` — config.py has get_browser()
- `test_browser_cli_no_direct_playwright_auth` — no raw Playwright auth in CLI code
- `test_browser_cli_no_custom_auth_check` — no custom auth check methods
- `test_no_custom_browser_status_check` — no duplicated browser status functions
- `test_auth_status_has_credentials_saved` — auth status returns credentials_saved
- `test_auth_test_has_credentials_saved` — auth test uses AuthVerifier

## Step 7: Report

Present findings as a compliance report:

```
## Browser Compliance Report: <cli_name>

### Files
- browser.py: [PASS/FAIL] — [details]
- config.py: [PASS/FAIL] — [details]
- main.py: [PASS/FAIL] — [details]

### Forbidden Patterns
- [PASS] No duplicated auth logic found
  OR
- [FAIL] Found X violations (list each)

### Tests
- [X/Y] browser automation tests passing
- [X/Y] auth command tests passing

### Recommendations
1. [Any fixes needed]
```

</process>

<success_criteria>
- All 6 steps completed
- Clear PASS/FAIL for each check
- Any FAIL items have specific fix recommendations
- Forbidden pattern scan covers all .py files in the CLI package
</success_criteria>
