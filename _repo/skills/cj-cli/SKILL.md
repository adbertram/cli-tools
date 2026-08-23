---
name: cj-cli
description: >-
  MANDATORY: Use this skill for service operations only. DO NOT use this skill
  for CLI implementation lifecycle work such as creating, testing, updating,
  troubleshooting, validating, removing, or documenting the CLI tool itself;
  delegate those tasks to cli-tool-expert.
  Execute cj operations using the `cj` CLI tool. CJ Affiliate publisher CLI --
  discover advertiser programs (REST API), bulk-apply to them (browser
  automation), and retrieve creatives or generate deep-link tracking URLs
  (Link Search API + offline URL builder).  Uses both a Personal Access Token
  and a persistent Marketplace browser session.
  Triggers: cj, cj cli, cj affiliate, commission junction, cj advertisers,
  cj relationships, cj marketplace, apply to cj advertiser, join cj program,
  cj publisher, list cj programs, bulk apply cj, cj advertiser search,
  cj pending applications, cj joined advertisers, cj links, cj link search,
  cj deeplink, cj tracking url, affiliate tracking link, cj creative,
  generate cj affiliate link, cj banner, cj text link.
---

<objective>
Execute CJ Affiliate publisher operations using the `cj` CLI. All CJ interactions (advertiser discovery, relationship management, program applications) must go through this CLI.
</objective>

<quick_start>
The `cj` CLI follows this pattern:
```bash
cj <command-group> <action> [arguments] [options]
```

| Common command | Purpose |
|----------------|---------|
| `cj auth login` | Configure PAT + interactive browser login |
| `cj auth status` | Per-profile JSON credential report |
| `cj advertisers list --relationship notjoined --table` | Find programs you have not joined |
| `cj advertisers search "*hosting*"` | Wildcard search advertiser names |
| `cj advertisers get <id>` | Full record (commission, link types, EPC) |
| `cj relationships list --status joined` | Inspect current relationships |
| `cj relationships apply <id>` | Submit a join request (idempotent) |
| `cj relationships apply-bulk targets.txt --delay 4` | Bulk apply from file/stdin |
| `cj links list <advertiser-id> --table` | List creatives (text links, banners) for a joined advertiser |
| `cj links get <link-id>` | Full detail for one creative |
| `cj links deeplink <advertiser-id> <destination-url>` | Generate a CJ deep-link tracking URL (offline; pure URL builder) |
| `cj links deeplink <id> <url> --sid <tag>` | Same, but tag clicks with a publisher sub-id for CJ reporting |
</quick_start>

<configuration>
Three publisher-account env vars live in the profile env file at
`~/.local/share/cli-tools/cj/.profiles/<profile>/.env`.  They are
distinct CJ ids -- conflating them returns HTTP 400 from CJ.

| Env var | Purpose | Required by |
|---------|---------|-------------|
| `PUBLISHER_ID` | Publisher *company* id (a.k.a. requestor-cid). Identifies the CJ company. | every API call |
| `WEBSITE_ID` | Publisher *website* id. Identifies one property of the company. | `cj links list`, `cj links get` |
| `PUBLISHER_ACCOUNT_ID` | Publisher *account* id -- the numeric segment between `/member/` and `/publisher/` in any authenticated members.cj.com URL. | `cj links deeplink` |

Find `WEBSITE_ID` and `PUBLISHER_ACCOUNT_ID` on members.cj.com.  The CLI fail-fasts with a clear error if either is missing; do not invent values.
</configuration>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `cj` command.**
It contains complete command syntax, all arguments, all options, and per-command usage instructions. Never guess at command syntax.
</principle>

<principle name="Dual Auth">
CJ has two authentication mechanisms and `cj` uses both:
- **PAT** (Personal Access Token) -- powers every `advertisers ...` command and `relationships list`/`get`. Generated at <https://members.cj.com/member/PersonalAccessTokens/tokens.cj>.
- **Browser session** -- required for `relationships apply` and `relationships apply-bulk`. CJ has no public mutation for joining a program; the CLI drives the Marketplace UI via a persistent Playwright session at <https://members.cj.com>.
Run `cj auth login` once to set both up. `cj auth status` reports the state of each credential type per profile.
</principle>

<principle name="Apply Is Idempotent">
`cj relationships apply` and `apply-bulk` always check the REST API first. If the publisher is already `joined`, `pending`, or `declined` for an advertiser, the command short-circuits without clicking. Outcomes are reported via the `ApplyOutcome` enum (`applied`, `already_joined`, `already_pending`, `declined`, `failed`, `skipped`). Failures capture a Playwright screenshot under the profile data directory.
</principle>

<principle name="AI Instruction Results">
After every `cj` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work.
</principle>

<principle name="Command Groups">
- `advertisers` -- read-only catalogue (list / search / get)
- `relationships` -- publisher relationship state plus browser-driven apply (list / get / apply / apply-bulk)
- `auth` -- credentials and profiles
- `cache` -- local response cache management
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in the requested format (JSON by default, `--table` for tables)
- Correct command and flags used (verified against `usage.json`)
- Apply commands report the resulting `ApplyOutcome` for every advertiser
</success_criteria>

## Known Issues

### 1. CJ advertiser-lookup returns sentinel strings ("New", "N/A") in numeric fields

**Symptom:** Multi-word `cj advertisers search "Google Cloud"` raised `Error: invalid literal for int() with base 10: 'New'`. `cj relationships list --status notjoined` raised `could not convert string to float: 'N/A'`. The errors varied by query because they came from the response payload, not from argument parsing.

**Cause:** CJ surfaces literal sentinel strings in fields the original model declared as `Optional[int]` / `Optional[float]`. `<network-rank>` carries `"New"` for newly listed programs; `<seven-day-epc>` and `<three-month-epc>` carry `"N/A"` for advertisers without enough data to compute EPC. The factory functions in `cj_cli/models/advertiser.py` coerced both via `int()` / `float()`, which raised `ValueError` and crashed the entire response.

**Fix:** Change `network_rank`, `seven_day_epc`, and `three_month_epc` to `Optional[str]` on `Advertiser`, `AdvertiserDetail`, and `Relationship`. Replace the `_to_optional_int` / `_to_optional_float` calls in `create_advertiser`, `create_advertiser_detail`, and `create_relationship` with a new `_to_optional_text` helper that preserves the raw string. None of the existing consumers do math on these fields — they're rendered to JSON or printed in a table — so preserving CJ's actual semantics is the correct shape.

**Verification:**
1. `cj advertisers search "Google Cloud" --limit 3` returns JSON with `"network_rank": "3"` (string) and no `int()` traceback.
2. `cj relationships list --status notjoined --limit 5` returns JSON and exits 0; no `float()` traceback.
3. `cd ~/Dropbox/GitRepos/cli-tools/cj && UV_PROJECT_ENVIRONMENT=~/.cache/uv/project-envs/cj-tests uv run --with pytest python -m pytest tests/test_bugfixes.py` — all 7 tests pass, including `test_bug1_network_rank_accepts_sentinel_string`, `test_bug3_epc_accepts_na_sentinel`, and `test_bug3_epc_accepts_numeric_value`.

**Recurrence Prevention:** Regression tests in `tests/test_bugfixes.py` feed hand-crafted XML with `<network-rank>New</network-rank>` and `<seven-day-epc>N/A</seven-day-epc>` through `create_advertiser` and `create_advertiser_detail` and assert the strings round-trip. If a future change reintroduces blind `int()` / `float()` coercion, those tests fail at the model layer before they reach a live API call.

**General rule:** External APIs that return sentinel strings ("N/A", "TBD", "New", "—") in nominally numeric fields belong in `Optional[str]` on the model. Coerce only at the rendering / consumer layer where the caller can decide what a sentinel means.

### 2. `--relationship all` sent literal "all" to CJ and got HTTP 400

**Symptom:** `cj advertisers list --relationship all` and `cj advertisers search ... --relationship all` failed with `CJ API error HTTP 400: Invalid advertiser id(s): all`.

**Cause:** `client.list_advertisers` forwarded `relationship` directly into the `advertiser-ids` query param. CJ's `advertiser-ids` accepts `joined`, `notjoined`, or a comma-separated list of advertiser IDs — but not the literal string `all`. The CLI's `--relationship` flag, however, documented `all` as a valid slice, so the help text and the API contract disagreed.

**Fix:** In `cj_cli/client.py::list_advertisers`, intercept `relationship == "all"` before building the request: recursively call `list_advertisers(relationship="joined")` and `list_advertisers(relationship="notjoined")`, concatenate the rows, and apply the `limit` slice once. `search_advertisers(..., relationship="all")` inherits the fix because it delegates to `list_advertisers`.

**Verification:**
1. `cj advertisers list --relationship all --limit 5` returns merged joined+notjoined rows and exits 0.
2. `cj advertisers search "Google" --relationship all --limit 5` returns merged rows.
3. `tests/test_bugfixes.py::test_bug2_list_relationship_all_splits_into_joined_and_notjoined` and `..._search_...` assert that `advertiser-ids=all` is NEVER sent to CJ; the recorded params contain only `joined` and `notjoined`.

**Recurrence Prevention:** The regression tests record every `params` dict passed to `_get` and assert `"all"` never appears in the `advertiser-ids` values. Any future code that forwards `relationship` straight to the API will fail those assertions.

### 3. `auth status` and the command credential gate disagreed about the same browser session

**Symptom:** `cj auth status` reported `credential_types.browser_session.authenticated: true`. The very next call, `cj relationships apply --dry-run 7453049`, exited 1 with `Authentication required. Missing credentials: - browser_session: browser session expired`. The two surfaces inspected the same on-disk session and produced opposite verdicts.

**Cause:** `auth status` uses `AuthVerifier._check_browser`, which is filesystem-only (`browser.has_session()` — marker + non-empty `auth-state.json`). The command-dispatch credential gate (`cli_tools_common.command_registry._check_credentials`) for `BROWSER_SESSION` walked a different path: it tried `_check_browser_saved_auth` (which needs `AUTH_STORAGE_KEY` or `AUTH_COOKIE_PATTERNS` declared on the browser subclass), got `None` because the CJ browser declares neither, then fell back to `browser.is_authenticated()` — a **live** navigation to `AUTH_CHECK_URL` that can fail when cookies are stale even while the filesystem session is intact. Two checks of the same thing, two different verdicts.

**Fix:** In `cli_tools_common/command_registry.py::_check_credentials`, when `_check_browser_saved_auth` returns `None` (no `AUTH_STORAGE_KEY` and no `AUTH_COOKIE_PATTERNS`), fall back to `browser.has_session()` — the same filesystem inspection `auth status` uses — instead of `browser.is_authenticated()`. The credential gate and `auth status` now agree on every browser-session CLI by construction. Commands that genuinely need a live check (the real apply path in `cj relationships apply`) still perform `browser.is_authenticated()` themselves at the point of use; the difference is the credential gate no longer rejects dry-runs and reads based on a transient live-navigation failure.

**Verification:**
1. `cj auth status` and `cj relationships apply --dry-run <id>` agree: both succeed with a valid saved session; both fail with `no saved browser session` after `cj auth logout`.
2. `cd ~/Dropbox/GitRepos/cli-tools/cli-tools-common && UV_PROJECT_ENVIRONMENT=~/.cache/uv/project-envs/cli-tools-common-tests uv run pytest tests/test_command_registry.py` — `test_browser_session_gate_uses_has_session_without_storage_or_cookie_hooks` and `test_browser_session_gate_fails_when_has_session_returns_false` both pass, asserting `browser.is_authenticated()` is never called when neither hook is declared.
3. Full cli-tools-common suite: 357 passed.

**Recurrence Prevention:** Two regression tests in `cli-tools-common/tests/test_command_registry.py` lock the contract: the gate MUST use `has_session` and MUST NOT call `is_authenticated` when no `AUTH_STORAGE_KEY` / `AUTH_COOKIE_PATTERNS` is set. The retired test `test_browser_session_gate_uses_live_check_without_storage_key` enforced the buggy behavior and was replaced. Any future change that adds a live-check fallback inside `_check_credentials` will fail these tests immediately.

**General rule:** When two surfaces inspect the same resource (here: a browser session on disk), they must run the same check or one must explicitly opt in to a stricter check. Diverging defaults across "status" and "gate" code paths guarantees user-visible disagreement.

### 4. `cj relationships apply` failed with "not authenticated" because of stale positive-nav-link selector

**Symptom:** `cj relationships apply 7453049` (real apply, not `--dry-run`) exited with `Error: CJ browser session is not authenticated. Run 'cj auth login' before applying to programs.` even though the session was valid: `cj auth status` reported authenticated, `cj auth login` short-circuited as already authenticated, and CJ's dashboard URL loaded without redirecting to `/login`. Under `DEBUG=1` the trace showed `has_session: True`, `_is_login_page: match=False`, then `_check_auth: selector="a[href*='/member/publisher/']" visible=False` → `is_authenticated: live check result=False`.

**Cause:** `CJBrowser.AUTH_SUCCESS_SELECTOR = "a[href*='/member/publisher/']"` was a positive nav-link marker. CJ refactored their member-shell HTML and no element with that href substring renders on the authenticated dashboard anymore. `BrowserAutomation._check_auth` walked priority `AUTH_URL_PATTERN` (not on login URL — good), then `AUTH_SUCCESS_SELECTOR` visibility (False — incorrectly reported "not authenticated"). Positive nav-link selectors are inherently brittle: they break whenever the target site refactors their dashboard, and we then chase the new selector — a cycle that recurs forever.

**Fix:** Replace the brittle positive marker with the more stable negative-of-login-form marker.

1. Added `AUTH_LOGIN_FORM_SELECTOR = ""` class constant to `BrowserAutomation` in `cli-tools-common/cli_tools_common/browser_automation.py`. When declared, `_check_auth` inserts a new priority-1 check between the URL-pattern check and the cookie check: if the login-form element is NOT visible on the page (and we are not on a login URL), the user is authenticated. Returns False if the element IS visible.
2. Updated `CJBrowser` in `cj/cj_cli/browser.py` — removed `AUTH_SUCCESS_SELECTOR = "a[href*='/member/publisher/']"` and added `AUTH_LOGIN_FORM_SELECTOR = 'input[type="password"], input[name="password"], form[action*="login"], form#loginForm'`.
3. Reinstalled the editable shared infra into the cj uv tool venv: `uv pip install --python /Users/adam/.local/share/uv/tools/cj-cli/bin/python3 -e ~/Dropbox/GitRepos/cli-tools/cli-tools-common`.

**Verification:**
1. `cd cli-tools-common && UV_PROJECT_ENVIRONMENT=~/.cache/uv/project-envs/cli-tools-common-tests uv run pytest tests/test_browser_automation.py -k bug5 -v` — 3 new tests pass: `test_bug5_check_auth_returns_true_when_login_form_absent`, `test_bug5_check_auth_returns_false_when_login_form_visible`, `test_bug5_check_auth_login_form_check_takes_priority_over_stale_positive_selector`.
2. Full cli-tools-common suite: 360 passed.
3. `cd cj && uv run --with pytest --with ~/Dropbox/GitRepos/cli-tools/cli-tools-common pytest` — 8 passed (includes new `test_bug5_cj_browser_uses_absence_of_login_form_check`).
4. `cj relationships apply --dry-run 7453049` → reports `outcome: "skipped"` (auth check no longer blocks).
5. `cj relationships apply 7453049` (real) → auth gate passes, browser navigates to Marketplace detail page. (A separate downstream issue — stale Marketplace `_APPLY_SELECTORS` — prevents the click stage from finding the Apply button; that is a different bug and out of scope for Bug 5.)

**Recurrence Prevention:** `tests/test_browser_automation.py` pins the new `_check_auth` priority order and the absence-of-login-form semantics. `cj/tests/test_bugfixes.py::test_bug5_cj_browser_uses_absence_of_login_form_check` asserts CJBrowser MUST declare `AUTH_LOGIN_FORM_SELECTOR` and MUST NOT re-introduce the stale `a[href*='/member/publisher/']` selector. Any future regression that reverts to positive-nav-link auth marking on CJ fails immediately.

**General rule:** When confirming authenticated state in a browser, prefer negative checks (absence of login-form elements) over positive checks (presence of authenticated nav elements). Login forms either render or they don't — that signal is stable. Authenticated nav elements get refactored, A/B-tested, and renamed regularly — that signal is brittle by construction.

### 5. `cj relationships apply` failed because the entire Marketplace URL + selectors went stale

**Symptom:** `cj relationships apply 7453049` returned `outcome: "failed", detail: "Could not locate an Apply control on the Marketplace detail page."` even with a fully valid browser session. Under `DEBUG=1` the trace showed the CLI navigating to `https://members.cj.com/member/<pub>/publisher/marketplace/advertiser-details.cj?adId=7453049` and then iterating `_APPLY_SELECTORS` (the brittle `data-testid='apply-button'` / `aria-label*='Apply'` tuple), all of which timed out at 4s each. Visiting that URL directly in a browser showed the stub page "Hey there! It looks like the link you clicked isn't currently active." — the old Marketplace was gone.

**Cause:** CJ retired the entire `advertiser-details.cj?adId=<id>` page and consolidated the publisher Apply flow into the new `findAdvertisers.cj` search view. Three layers of the apply path rotted simultaneously:

1. **URL.** `_marketplace_apply_url` pointed at the dead detail page. The real Apply UI now lives at `https://members.cj.com/member/<publisher_account_id>/publisher/advertisers/findAdvertisers.cj#<hash-state-json>`. The URL path uses the publisher *account id* (`7627660` in this account), NOT `CJ_PUBLISHER_ID` (`7955906`); the publisher_id is the hash-state `publisherId` field. The wrong path id 302s to `home.do`.
2. **Locator.** The Apply control is `<button class="ui-btn primary uppercase">Apply to Program</button>` — no testid, no aria-label, no data attributes. The only stable identifiers are its literal text and the row-anchoring sibling `<a href=".../links/search/#!advertiserIds=<id>">`. The legacy `_APPLY_SELECTORS` tuple was dead-letter from day one because CJ never rendered those attributes on the live page.
3. **Keyword filter.** CJ's findAdvertisers `keywords` field matches advertiser *name* substrings, not ids. Passing the raw advertiser id (`"7453049"`) as keywords returns 0 results, even though the advertiser exists. The apply path now MUST look up the advertiser name via the REST API first and use that as the keyword.

There is also a per-advertiser second step: every "Manual application review" advertiser on findAdvertisers routes to `joinprograms.do?advertiserId=<id>&publisherId=<pid>` after the first click. The actual application is registered only after clicking `<input type="submit" value="Accept and Apply">` on that page — and that control is an `<input>`, not a `<button>`, so a `button:has-text("Accept and Apply")` selector misses it.

**Fix:** Replace the URL + locator + flow in `cj/cj_cli/commands/relationships.py`:

1. **URL builder** `_find_advertisers_url(advertiser_id, publisher_account_id, keyword)` builds the live findAdvertisers.cj URL. Three required parameters, no defaults — passing `publisher_account_id=None` or `keyword=""` raises `ValueError`.
2. **Account-id discovery** `_discover_publisher_account_id(page)` navigates to `https://members.cj.com/member/publisher/home.do` and extracts the URL-path id from any rendered `a[href*="/member/<id>/publisher/"]` link via `page_eval`. Note: `PlaywrightService.page_eval` returns `{result, page_url, page_title}` — the raw value is under `.result`.
3. **Locator** `_apply_locator(advertiser_id)` returns the row-scoped selector `div.adv-row:has(a[href*="advertiserIds=<id>"]) button:has-text("Apply to Program")`. `div.adv-row` is the row container class; pinning the outer `:has()` to that class is what keeps the match to exactly one element (a bare `div:has(...) button` matches ~55 ancestor divs).
4. **Second-step Accept and Apply** after the first click, if the page URL contains `joinprograms.do`, wait for and click `input[type="submit"][value="Accept and Apply"], button:has-text("Accept and Apply")`. Poll the document title for "submitted" so the confirmation check below has a real chance.
5. **No-Apply-button state** when the row renders but the locator times out, re-poll REST. If the relationship is now pending/joined/declined, return that outcome with a clear "apply already registered" detail. Otherwise return FAILED with a state-aware message ("CJ may be gating apply — Network Profile / onboarding incomplete, advertiser deactivated apply, or REST propagation lag"), not the misleading "selector broken".
6. **One REST round-trip** instead of two: `_lookup_advertiser` runs once; `_outcome_from_status` decides short-circuit; the advertiser name from the same call is passed as the keyword.

**Verification:**
1. `cd ~/Dropbox/GitRepos/cli-tools/cj && UV_PROJECT_ENVIRONMENT=~/.cache/uv/project-envs/cj-tests uv run --with pytest pytest tests/test_bugfixes.py` — 13 passed (4 new Bug-6 tests pin the URL shape, the row-scoped locator contract, the absence of the legacy dead-letter selectors, and the end-to-end mocked apply flow).
2. Full cli-tools-common suite: 360 passed.
3. cli-tool compliance for cj: 128 passed, 21 skipped (all browser-CLI skips).
4. Real apply against advertiser 7453049 navigated through findAdvertisers → joinprograms.do → "Application submitted for review" (confirmed by page title). CJ's REST `relationship_status` propagation lags the UI by minutes; the row on the search page drops its Apply button immediately, which is the CLI's signal that the apply registered.

**Recurrence Prevention:** `cj/tests/test_bugfixes.py` adds four Bug-6 regression tests: `test_bug6_apply_url_targets_findAdvertisers_not_dead_detail_page` (URL shape + account-id-vs-publisher-id distinction), `test_bug6_find_advertisers_url_rejects_missing_account_id` (no silent fallback to publisher_id for the path id, no silent fallback to raw id as keyword), `test_bug6_apply_locator_is_row_scoped_and_text_matched` (selector contract: contains advertiser id, contains "Apply to Program", uses `:has(... advertiserIds=...)`), and `test_bug6_legacy_apply_selectors_tuple_is_gone` (dead-letter testid/aria patterns must never ship again). Any future reversion to the old URL or selector tuple fails immediately.

**General rule:** When a CLI drives a third-party SPA, the URL is part of the contract that rots with the site. Treat URL builders as first-class parsers/locators: parameterize every site-specific id, never reuse one id where two exist (publisher_account_id vs publisher_id), require — never default — the values that the wrong choice would silently break. And never assume a single page is the whole flow: walk the post-click navigation and pin the final-state signal (page title, REST propagation, or absence of the Apply button) rather than the first transient banner you see.

### 7. `cj relationships apply` reported `failed` for auto-approve advertisers even though REST already showed `joined`; screenshots silently never saved

**Symptom:** `cj relationships apply 4837117` (NordVPN) returned `outcome: "failed", detail: "Reached joinprograms.do for advertiser 4837117 but the Accept and Apply button never resolved: Timeout waiting for selector: input[type=\"submit\"][value=\"Accept and Apply\"], button:has-text(\"Accept and Apply\")"`. The Accept-and-Apply click was therefore NEVER executed. Yet `cj relationships get 4837117` immediately afterward returned `relationship_status: "joined"`. The CLI surfaced FAILED while the apply had in fact succeeded. The `screenshot_path` field in every FAILED ApplyResult was always `null` regardless of failure reason.

**Cause:** Two distinct bugs that surfaced together.

1. **Auto-approve flow assumption.** The post-click code path assumed every advertiser routes through a joinprograms.do T&C form ("manual review"). In reality, "auto-approve" advertisers (NordVPN among them) register the application on the FIRST "Apply to Program" click on findAdvertisers.cj. The page may or may not navigate to joinprograms.do afterwards — and when it does, it shows a processing state, not a T&C form. Waiting for an Accept-and-Apply selector that will never render produced a guaranteed false-negative FAILED.
2. **Screenshot API misuse.** All four `page.page_screenshot(ref=str(shot))` call sites passed a `Path` as the `ref` kwarg. `ref` on `PlaywrightService.page_screenshot` is a Playwright element locator string — `page.locator(ref)` is called internally — so passing a file path raises an invalid-selector exception. Every call site wrapped the call in a bare `except Exception: shot = None`, so the failure was silently swallowed. The `_screenshot_path` helper that constructed the destination paths was therefore entirely dead code.

Live-DOM verification (probe at `_temp/probe_joinprograms.py` for advertiser 1849166): direct navigation to `joinprograms.do?advertiserId=<id>&publisherId=<pid>` returns CJ's 1020-byte stub page (`<div class="error-page"><span>Hey there! It looks like the link you clicked isn't currently active.</span>...`). The joinprograms.do URL is session-stateful — it only renders the T&C form when reached via the in-flight Apply-to-Program click. Direct navigation cannot be used to probe its DOM.

A secondary contributing factor: the manual-review T&C form's `wait_for_selector(accept_selector, timeout=6000)` window was too short for joinprograms.do hydration on advertisers that DO render a T&C form. Bumping to 15000 ms gives the page realistic headroom.

**Fix:** In `cj/cj_cli/commands/relationships.py`:

1. **Add a REST-first poll** after the first Apply-to-Program click, before the joinprograms.do URL check. After settling the page (`wait_for_load_state("networkidle", 10000)`), sleep 2 s and call `_existing_outcome(advertiser_id)`. If REST returns any non-None outcome (`already_joined`, `already_pending`, `declined`), return immediately — the apply registered on the first click. Only fall through to the joinprograms.do branch when REST still reports `notjoined`.
2. **Inside the joinprograms.do branch's `except`**, re-poll REST one more time before returning FAILED. Some advertisers route to joinprograms.do AND register the apply on the first click, in which case the T&C form never renders. If the post-failure REST poll returns a terminal outcome, return that success instead of the misleading "Accept and Apply never resolved" failure.
3. **Bump the Accept-and-Apply `wait_for_selector` timeout from 6000 to 15000 ms.** Document why in the inline comment so a future refactor doesn't shrink it again.
4. **Replace the `_screenshot_path` helper** with a `_capture_screenshot(page)` helper that calls `page.page_screenshot()` with NO arguments (the service writes to `$TMPDIR/playwright-screenshots/<session>-<ts>.png` itself) and returns `result["file"]` — or `None` if the screenshot raised. Replace all four buggy call sites that did `page.page_screenshot(ref=str(shot))`.
5. **Delete `_screenshot_path`** — it was constructing destination paths that PlaywrightService ignored. The replacement helper consumes the path the service actually wrote.

**Verification:**

1. `cd ~/Dropbox/GitRepos/cli-tools/cj && UV_PROJECT_ENVIRONMENT=~/.cache/uv/project-envs/cj-tests uv run --with pytest --with ~/Dropbox/GitRepos/cli-tools/cli-tools-common pytest tests/test_bugfixes.py` — 19 passed (6 new Bug-7 tests + 13 prior bug regressions).
2. NordVPN status confirmed: `cj relationships get 4837117` returns `relationship_status: "joined"` (auto-approve succeeded on the first click despite the prior client-side timeout — this was the original symptom proof).
3. No live re-apply was performed during the fix — Bug-7 verification is via the regression-test suite. The first real apply attempt after this fix will exercise the REST-first short-circuit on auto-approve advertisers and the bumped timeout on manual-review advertisers.

**Recurrence Prevention:** `cj/tests/test_bugfixes.py` adds six Bug-7 regression tests:

- `test_bug7_capture_screenshot_helper_uses_correct_api` — pins that `_capture_screenshot` calls `page_screenshot()` with no `ref=` kwarg and returns `result["file"]`.
- `test_bug7_capture_screenshot_returns_none_on_failure` — pins fail-safe behaviour so a screenshot error cannot mask the underlying apply failure.
- `test_bug7_no_legacy_screenshot_ref_path_callsites` — source-level guard: greps `relationships.py` for any `page_screenshot(ref=...)` call. The misuse was textual, so the test must be textual.
- `test_bug7_rest_first_poll_short_circuits_auto_approve` — end-to-end mocked test: first REST call returns notjoined, post-click REST returns joined; asserts `_apply_single` returns `ALREADY_JOINED` and that `wait_for_selector` was never called for the Accept-and-Apply selector.
- `test_bug7_accept_and_apply_selector_timeout_bumped_from_6s` — source-level regex assertion that the Accept-and-Apply `wait_for_selector` timeout is `>= 10000` ms. A future PR that shrinks the window back to 6 s fails immediately.
- `test_bug7_screenshot_path_helper_is_removed` — asserts `_screenshot_path` is gone so a future change can't accidentally reintroduce the misleading dead helper.

**General rule:** When a CLI drives a third-party action whose true success is recorded server-side (a database row, a REST relationship status, an OAuth callback), make the server state the source of truth and consult it before — not after — chasing UI confirmation selectors. UI selectors document one rendering of one flow shape; the server state documents what happened. If a flow has multiple shapes (auto-approve vs manual review, instant vs delayed, single-page vs multi-step), the UI-confirmation-first design will always have a shape it doesn't recognise and surface FAILED on a success. Re-poll the server first; reach for the next UI step only when the server still says "nothing happened".
