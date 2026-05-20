---
name: cli-tool-browser-expert
description: "MANDATORY: SUPPORTING SKILL for cli-tool-expert. Parent sessions must delegate CLI browser lifecycle work to the cli-tool-expert agent. DO NOT perform CLI browser lifecycle work inline outside cli-tool-expert. When loaded inside cli-tool-expert, covers BrowserAutomation base class, AuthVerifier integration, browser auth lifecycle, and scaffold templates for CLI tools. Triggers: browser automation, add browser support, browser cli, BrowserAutomation, browser auth, playwright-cli session, browser login, is_authenticated, get_browser, browser session, add browser to cli, browser cli expert."
---

<objective>
Add, update, or troubleshoot browser automation in CLI tools built on cli-tools-shared.
Every browser CLI must delegate auth lifecycle to the common package — zero custom auth logic.
</objective>

<agent_routing>
When this skill is invoked by a parent Codex or Claude session and the current agent is not `cli-tool-expert`, delegate the work to `cli-tool-expert` instead of performing CLI browser lifecycle work inline. Pass the complete user request, relevant file paths, constraints, and required validation.

When the current agent is `cli-tool-expert`, follow this skill normally.
</agent_routing>

<quick_start>
Route based on intent:

| Intent | Route |
|--------|-------|
| Add browser support to existing CLI | workflows/add-browser-support.md |
| Create new browser CLI from scratch | Use the `cli-tool` skill with `--type browser` |
| Fix browser auth issues | workflows/troubleshoot-browser.md |
| Understand the architecture | references/architecture.md |
</quick_start>

<essential_principles>

<principle name="Zero Custom Auth Logic">
Browser CLIs NEVER implement auth state detection, session checking, or login flows.
All auth lifecycle is handled by `cli_tools_shared.auth.BrowserAutomation` and `cli_tools_shared.auth_verifier.AuthVerifier`.
The CLI's `browser.py` provides ONLY declarative hooks (class constants). No methods.
</principle>

<principle name="Minimal browser.py (~15 lines)">
A compliant browser.py declares 5 constants and nothing else:

```python
from cli_tools_shared.auth import BrowserAutomation
from .config import get_config

class MyBrowser(BrowserAutomation):
    SESSION_NAME = "myservice"
    LOGIN_URL = "https://myservice.com/login"
    AUTH_CHECK_URL = "https://myservice.com/dashboard"
    AUTH_URL_PATTERN = r"/login|/register"
    AUTH_SUCCESS_SELECTOR = 'selector-visible-when-logged-in'

    def __init__(self, config=None):
        config = config or get_config()
        super().__init__(config)
```

If browser.py has custom methods beyond `__init__`, something is wrong.
</principle>

<principle name="Config Wires Browser to AuthVerifier">
`config.py` implements `get_browser()` returning the BrowserAutomation subclass.
AuthVerifier automatically calls `config.get_browser().is_authenticated()` during `auth status`.
No other wiring needed.
</principle>

<principle name="Forbidden Patterns">
These patterns in CLI code (outside browser.py/config.py) indicate logic duplication:

- `def is_logged_in` / `def is_authenticated` / `def check_auth`
- `def _ensure_logged_in` / `def verify_session` / `def check_session`
- `def _check_browser_status` / `def check_browser_session`
- Direct `sync_playwright()` or `async_playwright()` imports
- Direct `launch_persistent_context` calls
- Custom `BrowserService` classes (legacy pattern)
</principle>

<principle name="Selector Validation">
`AUTH_SUCCESS_SELECTOR` must target a VISIBLE element on the authenticated page.
Hidden elements (collapsed menus, avatars in sidebars) cause false negatives.
Always validate selectors against real page snapshots using `playwright-cli page snapshot`.
</principle>

</essential_principles>

<intake>
What would you like to do?

1. **Add browser support** to an existing API or wrapper CLI
2. **Fix browser auth** (selector issues, session problems, false negatives)
3. **Understand architecture** (how BrowserAutomation/AuthVerifier work)
4. **Review compliance** (check if a CLI follows best practices)
5. Something else

**Wait for response before proceeding.**
</intake>

<routing>
| Response | Workflow |
|----------|----------|
| 1, "add browser", "browser support" | workflows/add-browser-support.md |
| 2, "fix", "broken", "selector", "not working" | workflows/troubleshoot-browser.md |
| 3, "understand", "how does", "explain", "architecture" | Read references/architecture.md, then explain |
| 4, "review", "compliance", "check" | workflows/review-compliance.md |
| 5, other | Clarify intent, then route |

**After reading the workflow, follow it exactly.**
</routing>

<reference_index>
All domain knowledge in `references/`:

**Architecture:** architecture.md (full system design, class hierarchy, data flow)
**Hooks:** hooks-reference.md (all BrowserAutomation class constants and overridable methods)
**Dual Auth:** dual-auth.md (combining browser_session with OAuth/API key)
**Scaffold:** See templates/scaffold/ for complete file examples
</reference_index>

<workflows_index>
| Workflow | Purpose |
|----------|---------|
| add-browser-support.md | Add browser automation to an existing CLI tool |
| troubleshoot-browser.md | Diagnose and fix browser auth issues |
| review-compliance.md | Audit a CLI for browser best practices |
</workflows_index>

<success_criteria>
- browser.py is ~15 lines with only class constants
- config.py implements `get_browser()` returning BrowserAutomation subclass
- config.py sets `CREDENTIAL_TYPES` including `CredentialType.BROWSER_SESSION`
- main.py uses `create_auth_app()` from cli_tools_shared
- No forbidden patterns exist anywhere in the CLI package
- `auth status` returns `credential_types.browser_session.browser_session: true/false` via AuthVerifier
- `auth logout` clears browser session (handled by common package)
- All browser automation tests pass
</success_criteria>

<validated>
Validated by validate-skill on 2026-03-04 18:45
</validated>

## Known Issues

### 1. BrowserAutomation must keep browser state outside source trees

**Symptom:** A browser-backed CLI writes session markers, cookie snapshots, browser profiles, or other runtime state under `<cli-tools-root>/` or another source repo. A fresh clone then contains Adam-local paths, stale browser state, or Dropbox-synced runtime artifacts that do not belong to the CLI source.

**Cause:** Older browser automation patterns treated storage-state JSON and profile markers as separate artifacts. That created multiple state stores and made it easy for one path to drift into the source tree.

**Fix:** Keep the current `cli_tools_shared.auth.BrowserAutomation` model: the persistent Chromium user-data-dir under `~/.local/share/cli-tools/<tool>/.profiles/<profile>/browser-data/chromium-profile/` is the single browser-session source of truth. HTTP-backed reads use `BrowserAutomation.live_cookies()` instead of source-tree snapshots. Do not add per-CLI state files, repo-local browser profiles, or compatibility snapshots.

**Verification:**
1. Run `pytest tests/test_auth.py tests/test_http_session.py` in `cli-tools-shared`.
2. Confirm browser data resolves under `~/.local/share/cli-tools/<tool>/`, never under `<cli-tools-root>/`.
3. Run the real installed launcher for the target CLI and a domain command that requires auth.

**Recurrence Prevention:** `cli-tools-shared/tests/test_auth.py` documents the persistent-profile contract and explicitly removes the old `_save_auth_state`, `_state_file_path`, marker, and state-save/state-load expectations. Any future browser-auth implementation must preserve one browser state location outside the repo.

**General rule:** Browser session state is runtime data, not source. If a browser file is needed after cloning, it belongs in the user profile data directory and must be recreated by `auth login`, not committed or synced in the repo tree.

### 2. `auth status` and `auth login` lie about session validity by trusting on-disk state instead of round-tripping

**Symptom:** `<cli> auth status` reports `credential_types.browser_session.authenticated: true` (and `authenticated: true` at the top level) for any CLI with `CredentialType.BROWSER_SESSION` whose persistent session has expired server-side. The very next data command (`bricklink messages list`, `cj relationships apply`, `doordash orders list`, etc.) immediately fails with `Error: Session expired. Please login again with '<cli> auth login'.`. Running `<cli> auth login` at that point also lies: it prints `✓ Already authenticated (<cli> browser session)` and exits without re-authenticating. The same class of bug applies to non-expiring OAuth (OAuth 1.0a / static-credential OAuth, `OAUTH_TOKEN_EXPIRES=False`): `auth status` reports `oauth_status: "valid"` based purely on the presence of all four credential fields in `.env`, never actually round-tripping to the API. The user directive that drives this entry: "auth status must do LIVE checks with the auth method in question always to ensure accuracy."

**Cause:** This is a deliberate policy reversal of an earlier "auth status is filesystem-only" position. Three independent code paths were trusting on-disk state as proof of being authenticated:

1. **`AuthVerifier._check_browser`** delegated to `browser.has_session()` (marker + non-empty `auth-state.json` exist) and never called `browser.is_authenticated()` — so any cookie that had been server-side-revoked or expired in place still reported `authenticated: true`.
2. **`AuthVerifier._verify_single_type` for OAuth with `OAUTH_TOKEN_EXPIRES=False`** returned `oauth_status: "valid"` solely based on `_has_static_oauth_credentials()` — a presence check across `OAUTH_STATIC_REQUIRED_FIELDS`. No API call. Revoked OAuth1 tokens reported as valid.
3. **`_handle_browser_login` in `auth_commands.py`** short-circuited on `browser.has_session()` alone, printing "Already authenticated" and skipping the interactive flow even when the saved cookies were dead. Worse: when the user `--force`d, the inner `BrowserAutomation.authenticate()` also short-circuited on `has_session()` if force wasn't propagated correctly, so the browser never opened.

The earlier policy (status is filesystem-only, never instantiate a browser) optimized for cheap status — but the cost was that `auth status` couldn't tell the truth about whether the session was actually usable. Users were repeatedly hitting "status says authenticated → next command says expired" and could not trust the status command. The user explicitly chose accuracy over speed: every auth method must be verified with a real round-trip, every time.

**Fix:** Apply ALL of the following in `cli-tools-shared/cli_tools_shared/`:

1. **`auth_verifier.py::_check_browser`** — when `browser.has_session()` is True, call `browser.is_authenticated()` and use the live result as the source of truth for `authenticated` and `available`. Close the browser in a `try/finally`. When `has_session()` is False there is nothing to live-check, so skip the probe. Coerce both `AuthResult` and plain bool return shapes (`bool(live)` + `getattr(live, "available", authenticated)`).
2. **`auth_verifier.py::_verify_single_type`** for OAuth with `OAUTH_TOKEN_EXPIRES=False` — delegate to `_check_api()` exactly like API_KEY types do. When the live test passes set `oauth_status="valid"` + `authenticated=True`; when it fails set `oauth_status="invalid"` + `api_test="failed: ..."` + `authenticated=False`; when no handler is wired set `oauth_status="saved"` + `api_test="skipped: no test handler"` + `authenticated=False` (we have credentials but no way to verify they work — do NOT claim valid).
3. **`auth_commands.py::create_auth_app`** — resolve `effective_test_handler` ONCE at the top of the factory and pass it to BOTH `auth status` and `auth test`. The historical code only passed it to `auth test`, so `auth status` was structurally incapable of live-verifying OAuth even when a handler existed.
4. **`auth_commands.py::_handle_browser_login`** — before claiming "Already authenticated", call `browser.is_authenticated()` after `has_session()`. If the live check fails, print "Saved session is no longer valid — re-running browser login." and proceed to `browser.login(force=True)` — the `force=True` is REQUIRED so the inner `authenticate()` doesn't short-circuit on its own `has_session()` check.
5. **Per-CLI `AUTH_URL_PATTERN`** — audit for regex patterns that don't actually match the real expired-session landing URL. Bricklink's pattern was `identity\.lego\.com/login` but the live redirect is `identity.lego.com/en-US/login?ReturnUrl=...`, so the locale segment broke the match and `_check_auth` reported authenticated when it wasn't. Fixed pattern: `identity\.lego\.com/[^?]*login|/v2/login\.page`. Always validate `AUTH_URL_PATTERN` against the actual expired-session URL by deliberately invalidating the session and capturing `page.url`.

**Verification:**
1. `cd cli-tools-shared && UV_PROJECT_ENVIRONMENT=~/.cache/uv/project-envs/cli-tools-shared-tests uv run pytest tests/test_auth_verifier.py tests/test_auth_commands.py -v` — 40 tests pass, including `TestAuthStatusLiveVerifiesBrowserSession::test_status_reports_false_when_session_files_exist_but_live_check_fails` and `test_browser_session_login_falls_through_when_live_check_fails`.
2. Full suite: `cd cli-tools-shared && UV_PROJECT_ENVIRONMENT=~/.cache/uv/project-envs/cli-tools-shared-tests uv run pytest` — 254 passed.
3. End-to-end reproduction with bricklink:
   - Before fix: `bricklink auth status` returns `browser_session.authenticated: true` while `bricklink messages list --limit 1` immediately errors with `Session expired`.
   - After fix: `bricklink auth status` returns `browser_session.authenticated: false` and the JSON top-level may still report `authenticated: true` only via the OAuth pathway (OR-over-configured types). `bricklink auth login` prints "Saved session is no longer valid — re-running browser login." instead of "Already authenticated".

**Recurrence Prevention:** Three regression test classes in `cli-tools-shared/tests/test_auth_verifier.py` pin the new contract:

* `TestAuthStatusLiveVerifiesBrowserSession::test_status_reports_false_when_session_files_exist_but_live_check_fails` asserts that when `has_session()` returns True and `is_authenticated()` returns False, the resulting block reports `credentials_saved: true` but `browser_session: false` and `authenticated: false`. This is the canonical bricklink-style scenario.
* `TestVerifyOutputFields::test_static_oauth_credentials_with_failed_live_test_report_invalid` asserts that saved OAuth1 credentials whose live API call raises produce `oauth_status: "invalid"` + `authenticated: false` — NOT "valid".
* `TestVerifyOutputFields::test_static_oauth_credentials_without_test_handler_report_unverified` asserts that saved OAuth1 credentials with no test handler produce `oauth_status: "saved"` + `authenticated: false` — we never claim valid without proof.

In `tests/test_auth_commands.py`, `test_browser_session_login_live_verifies_before_claiming_already_authenticated` and `test_browser_session_login_falls_through_when_live_check_fails` lock the `auth login` contract. The fall-through test additionally asserts `browser.login.assert_called_once_with(force=True)` so a future change that drops the force-propagation fails immediately.

The OLDER guard tests that pinned the opposite "auth status is filesystem-only" contract (`TestAuthStatusDoesNotLaunchBrowser` in this file, plus `browser.is_authenticated.assert_not_called()` assertions across multiple tests) were intentionally rewritten in this policy reversal. If you find them in any restored older file, treat them as stale — they document an explicitly rejected previous direction.

**General rule:** Status / login / "report current state" commands for auth MUST do a live round-trip per auth method, not infer from on-disk artifacts. Credentials on disk can be revoked, expired, or rotated server-side without our knowledge. Trusting `has_session()` / `has_credentials()` / "all four OAuth fields are set" as proof of being authenticated produces lying status reports and broken `already-authenticated` short-circuits. This is more expensive than a filesystem check (a network round-trip per type, a browser launch for browser_session) — that is the deliberately accepted cost of telling the truth.

### 3. `auth status` and the command credential gate disagree about the same browser session

**Symptom:** `<cli> auth status` reports `credential_types.browser_session.authenticated: true` for a CLI that declares `CredentialType.BROWSER_SESSION` but no `AUTH_STORAGE_KEY` and no `AUTH_COOKIE_PATTERNS` (e.g. `cj`). The next data command (`cj relationships apply --dry-run 7453049`) immediately fails with `Authentication required. Missing credentials: - browser_session: browser session expired`. The two surfaces inspect the same on-disk session and produce opposite verdicts. Re-running `cj auth login` reports "already authenticated" and does nothing — the disagreement persists across runs.

**Cause:** Two different code paths verify the same browser session and the defaults disagree. `auth status` runs through `AuthVerifier._check_browser`, which is filesystem-only via `browser.has_session()` (marker + non-empty `auth-state.json`). The dispatch-time credential gate runs through `cli_tools_shared.command_registry._check_credentials`, which first tries `_check_browser_saved_auth` (looking at `AUTH_STORAGE_KEY` for localStorage or `AUTH_COOKIE_PATTERNS` for cookies). When the browser subclass declares neither hook, `_check_browser_saved_auth` returns `None` and the historical gate fell back to `browser.is_authenticated()` — a **live** navigation to `AUTH_CHECK_URL` that can fail when cookies are stale even while the on-disk session is intact (transient network issue, cookie rotation, slow SPA hydrate, headed-mode race). Same resource, two checks, two verdicts.

**Fix:** In `cli_tools_shared/command_registry.py::_check_credentials`, when the `BROWSER_SESSION` branch sees `_check_browser_saved_auth` return `None`, fall back to `browser.has_session()` — the same filesystem inspection `auth status` uses — instead of `browser.is_authenticated()`. The gate and `auth status` now agree by construction for every browser-session CLI. Commands that genuinely need a live check (the real apply path in `cj relationships apply`, real read paths in DoorDash, etc.) still perform `browser.is_authenticated()` themselves at the point of use; the difference is the **dispatch gate** no longer rejects commands based on a transient live-navigation failure that disagrees with the rest of the system. CLIs that need a stricter dispatch-time check should declare `AUTH_STORAGE_KEY` or `AUTH_COOKIE_PATTERNS` on the browser subclass — that turns on the deterministic saved-auth check rather than the flaky live check.

**Verification:**
1. `cd cli-tools-shared && UV_PROJECT_ENVIRONMENT=~/.cache/uv/project-envs/cli-tools-shared-tests uv run pytest tests/test_command_registry.py` — `test_browser_session_gate_uses_has_session_without_storage_or_cookie_hooks` and `test_browser_session_gate_fails_when_has_session_returns_false` both pass; assert `browser.is_authenticated.assert_not_called()`.
2. Full cli-tools-shared suite: 357 passed.
3. `cj auth status` and `cj relationships apply --dry-run <id>` agree end-to-end against a real saved session.

**Recurrence Prevention:** Two regression tests in `cli-tools-shared/tests/test_command_registry.py` enforce the contract — the gate MUST use `has_session` and MUST NOT call `is_authenticated` when neither `AUTH_STORAGE_KEY` nor `AUTH_COOKIE_PATTERNS` is declared. The retired `test_browser_session_gate_uses_live_check_without_storage_key` enforced the buggy behavior and is now replaced. Any future change that adds an implicit live-check fallback inside `_check_credentials` will fail these tests immediately.

**General rule:** When two surfaces inspect the same on-disk state (`auth status` and the command dispatch gate; UI and API; cache and source of truth), they MUST use the same default check. Diverging defaults across "status" and "gate" code paths guarantees user-visible disagreement and produces "it says I'm logged in but the command says I'm not" bugs.

### 4. Positive site-specific selectors (auth, action buttons, status pills) rot whenever the target site refactors

**Symptom:** A CLI declares positive selectors targeting specific HTML attributes the target site ships today, and those selectors silently stop matching after the site refactors. Two manifestations seen so far:

* **Auth probe (CJ, Bug 5):** `AUTH_SUCCESS_SELECTOR = "a[href*='/member/publisher/']"` reported "not authenticated" on a valid session. `auth status` said authenticated, `auth login --force` short-circuited, dashboard URL loaded without redirecting to `/login`, but `DEBUG=1` showed `_check_auth: selector="..." visible=False`.
* **Apply / action button (CJ, Bug 6):** `_APPLY_SELECTORS = ("button[data-testid='apply-button']", "button[aria-label*='Apply' i]", "a[data-testid='apply-button']", "a[aria-label*='Apply' i]", "button:has-text('Apply to Program')", "button:has-text('Join Program')")` — every one of the testid/aria patterns timed out at 4s because CJ never actually rendered those attributes on the live page. The legacy tuple was dead-letter from day one; only the text-match members ever stood a chance, and once CJ rebuilt the page they too disappeared.

The pattern is the same in both cases: a positive marker pinned to surface attributes that the target site actively iterates on. Marketing renames the menu, eng restructures the URL space, an A/B test ships a different shell, the testid scheme moves to a new component library — and the selector silently stops matching.

**Cause:** Positive site-specific markers — `data-testid`, `aria-label*=`, `class*=`, nav-link `href*=`, role + name combinations — target HTML the target site owns and changes. There is no contract between us and the site; we are pattern-matching against incidental DOM. Every refactor of theirs is a regression of ours.

**Fix:** Prefer selector strategies in this order of resilience, from most to least durable:

1. **Negative of a logged-out signal** for auth probes. Declare `AUTH_LOGIN_FORM_SELECTOR` on the browser subclass — a selector targeting the login form's password input or `<form action*=login>`. Example: `AUTH_LOGIN_FORM_SELECTOR = 'input[type="password"], input[name="password"], form[action*="login"], form#loginForm'`. The shared `_check_auth` runs the absence check between the URL-pattern check and the cookie check. When the login form is NOT visible on a non-login URL, the user is authenticated. Login forms either render or they don't — that signal is stable.
2. **Stable semantic affordances** (`<form action=...>`, `<input type="submit" value="...">`, `<a href="...">`, ARIA roles with exact `name=`) — these are part of the site's accessibility contract and survive longer than presentational attributes. Note that the same control may switch between `<button>` and `<input type="submit">` across pages (CJ does this with "Apply to Program" vs "Accept and Apply") — match by visible label + role, not by tag.
3. **Row/group-scoped text matches** for action buttons. When you need a specific advertiser's / order's / item's button on a list page, do NOT use a flat `button:has-text("...")` — there will be many. Pin the outer `:has()` to the row container by a stable class AND by a property anchor unique to the target row, e.g. `div.adv-row:has(a[href*="advertiserIds=<id>"]) button:has-text("Apply to Program")`. Two filters guarantee exactly one match; one filter is a flaky bet.
4. **`data-testid` / `aria-label*=` only when the site documents them as a stable contract** (rare for third-party apps). Treat as fragile by default; review every appearance during PR.
5. **Pure CSS class selectors are a last resort** — `button.btn-primary` or `class*="apply"` rots on every redesign.

**Verification:**
1. Compliance tests: `cd cli-tools-shared && UV_PROJECT_ENVIRONMENT=~/.cache/uv/project-envs/cli-tools-shared-tests uv run pytest tests/test_auth.py -k bug5 -v` — 3 tests pin the new auth-probe priority order and the login-form-visible-vs-absent semantics.
2. Per-CLI: write a regression test that asserts the browser subclass declares `AUTH_LOGIN_FORM_SELECTOR` and does NOT re-declare any legacy positive nav-link selector. For action buttons, add a string-contract test on the locator-builder helper (assert the locator contains the row id + the action text + a row-class scope) so a future regression that loosens scope fails immediately.
3. End-to-end: a real command that exercises the selector (e.g. `cj relationships apply <id>` for auth + action) succeeds against a live page.

**Recurrence Prevention:** Two layers of tests:

* **Shared layer:** `cli_tools_shared/tests/test_auth.py` locks the `_check_auth` priority order: when `AUTH_LOGIN_FORM_SELECTOR` is declared, `_check_auth` returns True when the form is absent and False when it is visible.
* **Per-CLI layer:** every browser CLI's `tests/test_bugfixes.py` (or equivalent) pins the declarative shape of its selectors. CJ's `test_bug5_cj_browser_uses_absence_of_login_form_check` and `test_bug6_apply_locator_is_row_scoped_and_text_matched` are the templates — the first asserts the absence of the legacy positive nav-link, the second asserts the apply locator contains the advertiser id, the action label, and the row-scope `:has()`.

When auditing a new browser CLI during code review: reject positive nav-link `AUTH_SUCCESS_SELECTOR` values, reject `data-testid` / `aria-label*=` tuples used as the only identifiers for click targets, and require row-scope on any per-row click selector. These are tomorrow-bugs by construction.

**General rule:** A selector strategy is durable when its inputs cannot be silently changed by the site owner. Auth-state probes should test for the absence of a "logged out" signal (login form, redirect to `/login`), not the presence of a "logged in" signal (avatar, nav menu, dashboard widget). Action-button locators should be scoped to a row container by both a stable class AND a target-specific property (an anchor href, a row id), with a text match on the visible action label. Selectors built on presentational attributes (testid, class names, aria-label) are fragile and must be treated as known-rotting by construction.

### 5. `BrowserHarnessService.cookie_list()` used page-scoped `Network.getCookies`, returned `[]` on `about:blank`, then silently swallowed CDP errors

**Symptom:** A browser CLI that combines `BrowserAutomation` (persistent profile login) with `BrowserAuthState.from_config(config)` + `BrowserAuthenticatedHttpClient` (httpx-backed reads) fails with `Error: No browser session for <tool>. Run '<tool> auth login'.` on every data command — `bricklink order search 3001 --ids-only`, `bricklink messages list -l 1`, `bricklink invoice get`, etc. `auth status` reports `authenticated: true`, the persistent Chromium profile under `~/.local/share/cli-tools/<tool>/.profiles/default/browser-data/chromium-profile/Default/Cookies` has 30+ valid cookies in SQLite, `auth login` short-circuits with "already authenticated", and Chrome spawns successfully (`browser_open` succeeds, `_start_daemon: daemon up` logs) — but `BrowserAuthState.from_config` raises immediately after the daemon comes up.

**Cause:** Two compounding bugs in `cli_tools_shared/browser/driver.py::cookie_list`:

1. **Wrong CDP method.** It called `cdp("Network.getCookies")` — the **page-scoped** variant that returns only cookies applicable to the current top-frame URL. `cookie_list()` runs immediately after `browser_open()` returns, which only waits for the CDP port to be reachable (`_wait_for_cdp`), not for the URL passed to `--user-data-dir` Chrome to actually commit. At that instant Chrome is on `about:blank`, so `Network.getCookies` returns `[]` even though the persistent profile is fully loaded — `Network.getAllCookies` (browser-wide, all origins) returned 33 cookies from the same daemon at the same instant in a side-by-side comparison.
2. **Silent exception swallowing.** The body was wrapped in `try: ... except Exception: return []`, so every CDP transport failure, daemon crash, or unexpected payload was indistinguishable from "no cookies" — making the downstream `BrowserAuthStateError("No browser session for <tool>")` a structurally misleading message for any underlying problem.

The two parallel state stores referenced in the bug report (`config.has_saved_session()` = SQLite-existence check, `config.get_browser().live_cookies()` = CDP query) were correct-by-construction once the CDP query stopped being page-scoped — they read the same persistent profile, just through different APIs. The disagreement was an implementation defect in `cookie_list`, not an architectural fault.

**Fix:** In `cli-tools-shared/cli_tools_shared/browser/driver.py::cookie_list`:

* Replace `cdp("Network.getCookies")` with `cdp("Network.getAllCookies")` — returns every cookie in the browser's network stack regardless of current URL.
* Remove the `except Exception: return []` swallow. Failures must propagate (fail-fast policy).
* When `_opened` is False, raise `BrowserHarnessError` instead of returning `[]` — calling `cookie_list` without an open browser is a programming error, not "no cookies".
* When the CDP payload is not a dict, raise `BrowserHarnessError` with the unexpected payload included — never coerce to `[]`.

**Verification:**
1. `cd cli-tools-shared && UV_PROJECT_ENVIRONMENT=~/.cache/uv/project-envs/cli-tools-shared-tests uv run pytest tests/test_browser_driver.py -v` — 23 tests pass, including 4 new tests pinning the new contract: `test_cookie_list_calls_get_all_cookies_not_get_cookies`, `test_cookie_list_raises_when_browser_not_opened`, `test_cookie_list_propagates_cdp_errors_no_silent_fallback`, `test_cookie_list_rejects_non_dict_payload`.
2. Full shared suite: `cd cli-tools-shared && UV_PROJECT_ENVIRONMENT=~/.cache/uv/project-envs/cli-tools-shared-tests uv run pytest` — 282 passed, 132 skipped.
3. Side-by-side CDP comparison on a live daemon (immediately after `browser_open` returns, current URL still `about:blank`): `Network.getCookies` returns 0 cookies, `Network.getAllCookies` returns 33 cookies from the same persistent profile.
4. Live end-to-end against bricklink with a valid persistent session: `bricklink order search 3001 --ids-only` now returns a valid JSON result instead of `Error: No browser session for bricklink.`; `bricklink messages list --limit 1` returns the real message JSON.

**Recurrence Prevention:** Four regression tests in `cli-tools-shared/tests/test_browser_driver.py` enforce the new contract. `test_cookie_list_calls_get_all_cookies_not_get_cookies` asserts the CDP method name explicitly — any future refactor that re-introduces `Network.getCookies` fails immediately. `test_cookie_list_propagates_cdp_errors_no_silent_fallback` and `test_cookie_list_rejects_non_dict_payload` lock the fail-fast contract: every error path must raise, never return `[]`. The bricklink data commands (`messages list`, `order search`, etc.) exercise the full code path end-to-end against a live session, so any regression surfaces in the next test-cli-tool run.

**General rule:** When a CDP/protocol method has both a scoped variant (current URL, current frame, current target) and an unscoped variant (all origins, all frames, all targets), the unscoped variant is the right choice for "give me everything in the session" use cases. The scoped variant exists for page-instrumentation use cases (e.g. "what cookies will this fetch send"), not for persistence/snapshot purposes. Always verify whether the chosen variant actually returns what the caller needs by running both in a live trace before committing — names like `getCookies` vs `getAllCookies` can read interchangeably in code but behave radically differently at runtime. Pair the API choice with strict fail-fast: a CDP call that silently returns `[]` on any error is structurally worse than a loud crash, because the downstream consumer's error message is forced to be misleading.
