---
name: cli-tool-browser-expert
description: "MANDATORY: SUPPORTING SKILL for cli-tool-expert. Parent sessions must delegate CLI browser lifecycle work to the cli-tool-expert agent. DO NOT perform CLI browser lifecycle work inline outside cli-tool-expert. When loaded inside cli-tool-expert, covers BrowserAutomation base class, AuthVerifier integration, browser auth lifecycle, and scaffold templates for CLI tools. Triggers: browser automation, add browser support, browser cli, BrowserAutomation, browser auth, playwright-cli session, browser login, is_authenticated, get_browser, browser session, add browser to cli, browser cli expert."
---

<objective>
Add, update, or troubleshoot browser automation in CLI tools built on cli-tools-shared.
Every browser CLI must delegate auth lifecycle to the shared package — zero custom auth logic.
</objective>

<agent_routing>
When this skill is invoked by a parent Codex or Claude session and the current agent is not `cli-tool-expert`, delegate the work to `cli-tool-expert` instead of performing CLI browser lifecycle work inline. Pass the complete user request, relevant file paths, constraints, and required validation.

When the current agent is `cli-tool-expert`, follow this skill normally.
</agent_routing>

<quick_start>
Route based on intent:

| Intent | Route |
|--------|-------|
| Add browser support to existing CLI | Follow `<essential_principles>` below, starting from the scaffold at `_repo/skills/cli-tool/templates/browser/{{name_underscore}}_cli/browser.py` |
| Create new browser CLI from scratch | Use the `cli-tool` skill with `--type browser` |
| Fix browser auth issues | Check `## Known Issues` below first, then read `_repo/cli-tools-shared/cli_tools_shared/auth.py` (`BrowserAutomation`) and `auth_verifier.py` (`AuthVerifier`) |
| Understand the architecture | Read `_repo/cli-tools-shared/cli_tools_shared/auth.py` and `auth_verifier.py` directly — their docstrings are the source of truth |
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


<principle name="Shared Chromium Profile (default)">
Browser-session CLIs on the ``default`` authentication profile share one
Chromium user-data-dir so Google/SSO login is once across tools:

``~/.local/share/cli-tools/_shared/chromium-profile``

Resolved by ``BaseConfig.get_persistent_profile_dir()`` / ``uses_shared_chromium_profile()``.
New browser CLIs need **zero** per-CLI glue — the shared package owns the path.

**Stay isolated when:**
- the active auth profile name is not ``default`` (multi-account tools), or
- ``CLI_TOOLS_ISOLATE_CHROME_PROFILE=1``, or
- the config does not declare ``CredentialType.BROWSER_SESSION``.

**Overrides:** ``CLI_TOOLS_SHARED_CHROME_PROFILE=/absolute/or/~/path`` changes the shared dir.

**Concurrency:** Chrome allows only one process on a given user-data-dir. Run browser CLIs that need Chrome sequentially, or isolate.

**Logout:** ``clear_session()`` clears tool-local ``browser-data/`` but does **not** wipe the shared profile (so one CLI logout does not log every tool out of Google). Use ``clear_shared_chromium_profile()`` for a full shared reset.

**Tests:** ``_repo/cli-tools-shared/tests/test_shared_chromium_profile.py``.
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
| Response | Action |
|----------|----------|
| 1, "add browser", "browser support" | Apply `<essential_principles>` to the target CLI, starting from the scaffold at `_repo/skills/cli-tool/templates/browser/{{name_underscore}}_cli/browser.py` |
| 2, "fix", "broken", "selector", "not working" | Check `## Known Issues` below for a matching symptom first, then read the live source in `_repo/cli-tools-shared/cli_tools_shared/auth.py` and `auth_verifier.py` |
| 3, "understand", "how does", "explain", "architecture" | Read `_repo/cli-tools-shared/cli_tools_shared/auth.py` (`BrowserAutomation`) and `auth_verifier.py` (`AuthVerifier`) directly, then explain |
| 4, "review", "compliance", "check" | Audit the CLI against `<success_criteria>` below and the `Forbidden Patterns` principle |
| 5, other | Clarify intent, then route |
</routing>

<reference_index>
This skill has no separate `references/` or `workflows/` directory — every route above points at
either the sections in this file or the real, currently-existing source in this repo:

**Architecture / hooks:** `_repo/cli-tools-shared/cli_tools_shared/auth.py` (`BrowserAutomation` class — constants and overridable methods are documented in its docstrings) and `auth_verifier.py` (`AuthVerifier`)
**Dual Auth:** `cj/cj_cli/config.py` is a live example combining `CredentialType.PERSONAL_ACCESS_TOKEN` with `CredentialType.BROWSER_SESSION`
**Scaffold:** `_repo/skills/cli-tool/templates/browser/{{name_underscore}}_cli/browser.py` is the real scaffold file used by `cli-tool --type browser`
</reference_index>

<success_criteria>
- browser.py is ~15 lines with only class constants
- config.py implements `get_browser()` returning BrowserAutomation subclass
- config.py sets `CREDENTIAL_TYPES` including `CredentialType.BROWSER_SESSION`
- main.py uses `create_auth_app()` from cli_tools_shared
- No forbidden patterns exist anywhere in the CLI package
- `auth status` returns `credential_types.browser_session.browser_session: true/false` via AuthVerifier
- `auth logout` clears browser session (handled by the shared package)
- All browser automation tests pass
</success_criteria>

<validated>
Validated by validate-skill on 2026-10-05
</validated>

## Known Issues

### 1. (Resolved by the H1 refactor) Dual marker/snapshot session files — do not resurrect this

Earlier revisions of this skill described a bug where `BrowserAutomation` persisted a `profile.json`
marker but not a separate Playwright `storage_state` snapshot (`auth-state.json`), causing httpx-backed
reads to report a misleading "Session expired" while `auth status` said authenticated. That entire
marker-plus-snapshot architecture — `has_session()`, `_save_auth_state()`, `_state_file_path()`,
`state_save`/`state_load` — was deliberately deleted from `cli_tools_shared/auth.py` as part of a later
refactor (tracked in this repo's history as "H1"); see the module docstring at the top of
`_repo/cli-tools-shared/tests/test_auth.py`.

The current, single source of truth is the persistent Chromium user-data-dir
(`chromium-profile/Default/`) — there is no separate snapshot file. httpx-backed code paths fetch
cookies live via `live_cookies()` instead of reading a cached snapshot. Session presence on disk is
checked via `config.has_saved_session()` (see `cli_tools_shared/config.py`), and real liveness is
always checked via `browser.is_authenticated()` (see Known Issue #2 below) — never infer either one
from a marker file.

**Do not** re-add `_save_auth_state`, `_state_file_path`, or a two-file `has_session()` check to
`cli_tools_shared/auth.py` — that machinery was intentionally removed, and its tests were deleted
with it. If a future symptom looks like "cookies are valid but a data command still reports Session
expired," re-diagnose against the *current* `live_cookies()` path instead of assuming this old bug
recurred.

### 2. `auth status` and `auth login` lie about session validity by trusting on-disk state instead of round-tripping

**Symptom:** `<cli> auth status` reports `credential_types.browser_session.authenticated: true` (and `authenticated: true` at the top level) for any CLI with `CredentialType.BROWSER_SESSION` whose persistent session has expired server-side. The very next data command (`bricklink messages list`, `cj relationships apply`, `doordash orders list`, etc.) immediately fails with `Error: Session expired. Please login again with '<cli> auth login'.`. Running `<cli> auth login` at that point also lies: it prints `✓ Already authenticated (<cli> browser session)` and exits without re-authenticating. The same class of bug applies to non-expiring OAuth (OAuth 1.0a / static-credential OAuth, `OAUTH_TOKEN_EXPIRES=False`): `auth status` reports `oauth_status: "valid"` based purely on the presence of all four credential fields in `.env`, never actually round-tripping to the API. The user directive that drives this entry: "auth status must do LIVE checks with the auth method in question always to ensure accuracy."

**Cause:** This is a deliberate policy reversal of an earlier "auth status is filesystem-only" position. Three independent code paths were trusting on-disk state as proof of being authenticated:

1. **`AuthVerifier._check_browser`** delegated to `config.has_saved_session()` (on-disk profile presence) and never called `browser.is_authenticated()` — so any cookie that had been server-side-revoked or expired in place still reported `authenticated: true`.
2. **`AuthVerifier._verify_single_type` for OAuth with `OAUTH_TOKEN_EXPIRES=False`** returned `oauth_status: "valid"` solely based on `_has_static_oauth_credentials()` — a presence check across `OAUTH_STATIC_REQUIRED_FIELDS`. No API call. Revoked OAuth1 tokens reported as valid.
3. **`_handle_browser_login` in `auth_commands.py`** short-circuited on `browser.has_session()` alone, printing "Already authenticated" and skipping the interactive flow even when the saved cookies were dead. Worse: when the user `--force`d, the inner `BrowserAutomation.authenticate()` also short-circuited on `has_session()` if force wasn't propagated correctly, so the browser never opened.

The earlier policy (status is filesystem-only, never instantiate a browser) optimized for cheap status — but the cost was that `auth status` couldn't tell the truth about whether the session was actually usable. Users were repeatedly hitting "status says authenticated → next command says expired" and could not trust the status command. The user explicitly chose accuracy over speed: every auth method must be verified with a real round-trip, every time.

**Fix:** Apply ALL of the following in `_repo/cli-tools-shared/cli_tools_shared/`:

1. **`auth_verifier.py::_check_browser`** — when `config.has_saved_session()` is True, call `browser.is_authenticated()` and use the live result as the source of truth for `authenticated` and `available`. Close the browser in a `try/finally`. When `has_saved_session()` is False there is nothing to live-check, so skip the probe. Coerce both `AuthResult` and plain bool return shapes (`bool(live)` + `getattr(live, "available", authenticated)`).
2. **`auth_verifier.py::_verify_single_type`** for OAuth with `OAUTH_TOKEN_EXPIRES=False` — delegate to `_check_api()` exactly like API_KEY types do. When the live test passes set `oauth_status="valid"` + `authenticated=True`; when it fails set `oauth_status="invalid"` + `api_test="failed: ..."` + `authenticated=False`; when no handler is wired set `oauth_status="saved"` + `api_test="skipped: no test handler"` + `authenticated=False` (we have credentials but no way to verify they work — do NOT claim valid).
3. **`auth_commands.py::create_auth_app`** — resolve `effective_test_handler` ONCE at the top of the factory and pass it to BOTH `auth status` and `auth test`. The historical code only passed it to `auth test`, so `auth status` was structurally incapable of live-verifying OAuth even when a handler existed.
4. **`auth_commands.py::_handle_browser_login`** — before claiming "Already authenticated", call `browser.is_authenticated()` after `config.has_saved_session()`. If the live check fails, print "Saved session is no longer valid — re-running browser login." and proceed to `browser.login(force=True)` — the `force=True` is REQUIRED so the inner `authenticate()` doesn't short-circuit on its own saved-session check.
5. **Per-CLI `AUTH_URL_PATTERN`** — audit for regex patterns that don't actually match the real expired-session landing URL. Bricklink's pattern was `identity\.lego\.com/login` but the live redirect is `identity.lego.com/en-US/login?ReturnUrl=...`, so the locale segment broke the match and `_check_auth` reported authenticated when it wasn't. Fixed pattern: `identity\.lego\.com/[^?]*login|/v2/login\.page`. Always validate `AUTH_URL_PATTERN` against the actual expired-session URL by deliberately invalidating the session and capturing `page.url`.

**Verification:**
1. `cd _repo/cli-tools-shared && UV_PROJECT_ENVIRONMENT=~/.cache/uv/project-envs/cli-tools-shared-tests uv run pytest tests/test_auth_verifier.py tests/test_auth_commands.py -v` — 40 tests pass, including `TestAuthStatusLiveVerifiesBrowserSession::test_status_reports_false_when_session_files_exist_but_live_check_fails` and `test_browser_session_login_falls_through_when_live_check_fails`.
2. Full suite: `cd _repo/cli-tools-shared && UV_PROJECT_ENVIRONMENT=~/.cache/uv/project-envs/cli-tools-shared-tests uv run pytest` — 254 passed.
3. End-to-end reproduction with bricklink:
   - Before fix: `bricklink auth status` returns `browser_session.authenticated: true` while `bricklink messages list --limit 1` immediately errors with `Session expired`.
   - After fix: `bricklink auth status` returns `browser_session.authenticated: false` and the JSON top-level may still report `authenticated: true` only via the OAuth pathway (OR-over-configured types). `bricklink auth login` prints "Saved session is no longer valid — re-running browser login." instead of "Already authenticated".

**Recurrence Prevention:** Three regression test classes in `_repo/cli-tools-shared/tests/test_auth_verifier.py` pin the new contract:

* `TestAuthStatusLiveVerifiesBrowserSession::test_status_reports_false_when_session_files_exist_but_live_check_fails` asserts that when `config.has_saved_session()` returns True and `is_authenticated()` returns False, the resulting block reports `credentials_saved: true` but `browser_session: false` and `authenticated: false`. This is the canonical bricklink-style scenario.
* `TestVerifyOutputFields::test_static_oauth_credentials_with_failed_live_test_report_invalid` asserts that saved OAuth1 credentials whose live API call raises produce `oauth_status: "invalid"` + `authenticated: false` — NOT "valid".
* `TestVerifyOutputFields::test_static_oauth_credentials_without_test_handler_report_unverified` asserts that saved OAuth1 credentials with no test handler produce `oauth_status: "saved"` + `authenticated: false` — we never claim valid without proof.

In `tests/test_auth_commands.py`, `test_browser_session_login_live_verifies_before_claiming_already_authenticated` and `test_browser_session_login_falls_through_when_live_check_fails` lock the `auth login` contract. The fall-through test additionally asserts `browser.login.assert_called_once_with(force=True)` so a future change that drops the force-propagation fails immediately.

The OLDER guard tests that pinned the opposite "auth status is filesystem-only" contract (`TestAuthStatusDoesNotLaunchBrowser` in this file, plus `browser.is_authenticated.assert_not_called()` assertions across multiple tests) were intentionally rewritten in this policy reversal. If you find them in any restored older file, treat them as stale — they document an explicitly rejected previous direction.

**General rule:** Status / login / "report current state" commands for auth MUST do a live round-trip per auth method, not infer from on-disk artifacts. Credentials on disk can be revoked, expired, or rotated server-side without our knowledge. Trusting `has_saved_session()` / `has_credentials()` / "all four OAuth fields are set" as proof of being authenticated produces lying status reports and broken `already-authenticated` short-circuits. This is more expensive than a filesystem check (a network round-trip per type, a browser launch for browser_session) — that is the deliberately accepted cost of telling the truth.

### 3. `auth status` and the command credential gate disagree about the same browser session

**Symptom:** `<cli> auth status` reports `credential_types.browser_session.authenticated: true` for a CLI that declares `CredentialType.BROWSER_SESSION` but no `AUTH_STORAGE_KEY` and no `AUTH_COOKIE_PATTERNS` (e.g. `cj`). The next data command (`cj relationships apply --dry-run 7453049`) immediately fails with `Authentication required. Missing credentials: - browser_session: browser session expired`. The two surfaces inspect the same on-disk session and produce opposite verdicts. Re-running `cj auth login` reports "already authenticated" and does nothing — the disagreement persists across runs.

**Cause:** Two different code paths verify the same browser session and used to disagree. `auth status` runs through `AuthVerifier._check_browser`: it checks `config.has_saved_session()` first, and when a session exists it live-verifies via `browser.is_authenticated()` (see Known Issue #2 above) — its `authenticated` field reflects a live round-trip, not just file presence. The dispatch-time credential gate in `cli_tools_shared/command_registry.py::_check_credentials` used to take a different path for `CredentialType.BROWSER_SESSION`: it inspected the browser subclass's `AUTH_STORAGE_KEY` (localStorage) or `AUTH_COOKIE_PATTERNS` (cookies) for an offline snapshot check, and when a CLI declared neither — as `cj` did not — it fell back to a **live** `browser.is_authenticated()` navigation of its own. That live navigation could fail transiently (cookie rotation, slow SPA hydrate, a stray network error) even while the on-disk session was intact, so the gate would reject a command that `auth status` had just reported as authenticated. Same resource, two independently-maintained checks, two verdicts.

**Fix:** In `cli_tools_shared/command_registry.py::_check_credentials`, the `BROWSER_SESSION` branch (around line 349) was simplified to a single check: `config.has_saved_session()`. The `AUTH_STORAGE_KEY` / `AUTH_COOKIE_PATTERNS` offline-snapshot branch and its live-check fallback were removed entirely — there is no `_check_browser_saved_auth` helper in this codebase and no per-CLI escape hatch; declaring either attribute on a browser subclass has no effect on the gate. The gate and `auth status` now share the same on-disk signal for "is there a session to use." Commands that need proof the session still works server-side (the real apply path in `cj relationships apply`, real read paths in DoorDash, etc.) still call `browser.is_authenticated()` themselves at the point of use — that live check is no longer the dispatch gate's job.

**Verification:**
1. `cd _repo/cli-tools-shared && UV_PROJECT_ENVIRONMENT=~/.cache/uv/project-envs/cli-tools-shared-tests uv run pytest tests/test_command_registry.py` — `test_browser_session_gate_passes_when_config_has_saved_session`, `test_browser_session_gate_fails_when_config_has_no_saved_session`, and `test_browser_session_gate_does_not_call_live_is_authenticated` all pass; the last asserts `browser.is_authenticated.assert_not_called()`.
2. Full `_repo/cli-tools-shared` suite.
3. `cj auth status` and `cj relationships apply --dry-run <id>` agree end-to-end against a real saved session.

**Recurrence Prevention:** Regression tests in `_repo/cli-tools-shared/tests/test_command_registry.py` enforce the contract: `test_browser_session_gate_passes_when_config_has_saved_session` and `test_browser_session_gate_fails_when_config_has_no_saved_session` assert the gate calls `config.has_saved_session()`; `test_browser_session_gate_does_not_call_live_is_authenticated` asserts neither `browser.is_authenticated()` nor `browser.has_session()` is ever called from the gate; and `test_browser_session_gate_does_not_consider_browser_class_attributes` asserts that even when a browser subclass declares both `AUTH_STORAGE_KEY` and `AUTH_COOKIE_PATTERNS`, the gate still fails when `has_saved_session()` is False — those attributes have no effect on dispatch. Any future change that reintroduces a live-check fallback, or makes `AUTH_STORAGE_KEY`/`AUTH_COOKIE_PATTERNS` affect the gate again, will fail these tests immediately.

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
1. Compliance tests: `cd _repo/cli-tools-shared && UV_PROJECT_ENVIRONMENT=~/.cache/uv/project-envs/cli-tools-shared-tests uv run pytest tests/test_auth.py -k bug5 -v` — pins the new auth-probe priority order and the login-form-visible-vs-absent semantics (see `test_bug5_check_auth_returns_true_when_login_form_absent`, `test_bug5_check_auth_returns_false_when_login_form_visible`, `test_bug5_check_auth_login_form_check_takes_priority_over_stale_positive_selector`).
2. Per-CLI: write a regression test that asserts the browser subclass declares `AUTH_LOGIN_FORM_SELECTOR` and does NOT re-declare any legacy positive nav-link selector. For action buttons, add a string-contract test on the locator-builder helper (assert the locator contains the row id + the action text + a row-class scope) so a future regression that loosens scope fails immediately.
3. End-to-end: a real command that exercises the selector (e.g. `cj relationships apply <id>` for auth + action) succeeds against a live page.

**Recurrence Prevention:** Two layers of tests:

* **Shared layer:** `_repo/cli-tools-shared/tests/test_auth.py` locks the `_check_auth` priority order: when `AUTH_LOGIN_FORM_SELECTOR` is declared, `_check_auth` returns True when the form is absent and False when it is visible.
* **Per-CLI layer:** every browser CLI's `tests/test_bugfixes.py` (or equivalent) pins the declarative shape of its selectors. CJ's `test_bug5_cj_browser_uses_absence_of_login_form_check` and `test_bug6_apply_locator_is_row_scoped_and_text_matched` are the templates — the first asserts the absence of the legacy positive nav-link, the second asserts the apply locator contains the advertiser id, the action label, and the row-scope `:has()`.

When auditing a new browser CLI during code review: reject positive nav-link `AUTH_SUCCESS_SELECTOR` values, reject `data-testid` / `aria-label*=` tuples used as the only identifiers for click targets, and require row-scope on any per-row click selector. These are tomorrow-bugs by construction.

**General rule:** A selector strategy is durable when its inputs cannot be silently changed by the site owner. Auth-state probes should test for the absence of a "logged out" signal (login form, redirect to `/login`), not the presence of a "logged in" signal (avatar, nav menu, dashboard widget). Action-button locators should be scoped to a row container by both a stable class AND a target-specific property (an anchor href, a row id), with a text match on the visible action label. Selectors built on presentational attributes (testid, class names, aria-label) are fragile and must be treated as known-rotting by construction.
