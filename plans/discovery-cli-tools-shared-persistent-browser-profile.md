# Discovery: Persistent Chromium Profile Refactor for cli-tools-shared

## Task

Switch the `BrowserAutomation` base class in `cli-tools-shared` from a `storage_state` snapshot model (cookies + localStorage only, written to `auth-state.json`) to a **persistent Chromium user-data-dir** model co-located with the per-profile `.env` file. Bricklink-first validation, then rely on shared-base inheritance for the other browser-using CLIs.

## Codebase Context

### Key files (verified in this discovery pass)

| File | Role | Key lines |
|---|---|---|
| `cli-tools-shared/cli_tools_shared/auth.py` | `BrowserAutomation` base class. State save/load, login flow, `get_page()`, `clear_session()`, `is_authenticated()` TTL cache. | `authenticate()` 307-398; `clear_session()` 501-516; `get_page()` 401-472 (silent `state_load` swallow at 462); `_save_auth_state()` 202-230; `is_authenticated()` 264-305 (`AUTH_CHECK_TTL=300`). |
| `cli-tools-shared/cli_tools_shared/browser/driver.py` | `BrowserHarnessService` — CDP, Chrome lifecycle, daemon mgmt, state serialization. | `_user_data_dir()` 157-160 (today: `_DAEMON_PROFILES_DIR / f"ud-{self.session}"`); `state_save()` 620-632 (cookies + localStorage origins only); `_cleanup_stale_session()` 339-368 (deletes singleton locks, **does NOT rmtree user-data-dir**); `data_delete()` 653-666 (does rmtree); `_start_daemon()` 183-198 (`BU_NAME=session`); runtime dir at line 36 (`/tmp/cli-tools-bh/<session>`, AF_UNIX 104-byte cap). |
| `cli-tools-shared/cli_tools_shared/browser/__init__.py` | `_DAEMON_PROFILES_DIR` → `~/Library/Caches/cli-tools-browser/daemon` on macOS. | |
| `cli-tools-shared/cli_tools_shared/auth_commands.py` | `create_auth_app()` factory; `_handle_browser_login()` 48-99 (force flag handling, live re-check); shared `auth_status` 75-83. | |
| `cli-tools-shared/cli_tools_shared/config.py` | Profile layout. `env_path_for_profile()` 76-88; `get_browser_data_dir()` 696-700 returns `<profile_data_dir>/browser-data/`. `has_saved_session()` honors both new (profile.json) and legacy (browser-data) markers. | |
| `cli-tools-shared/cli_tools_shared/http_session.py` | `BrowserAuthState.from_config(config)` — reads `auth-state.json` for httpx-backed code paths. Raises `BrowserAuthStateError` when missing/empty. | |
| `bricklink/bricklink_cli/browser.py` | Bricklink subclass. `SESSION_NAME="bricklink"`, `AUTH_URL_PATTERN`, `AUTH_COOKIE_PATTERNS`. 54 lines. | |
| `bricklink/bricklink_cli/browser_runtime.py` | Bricklink browser-backed operations. `_check_session_expired()` 76-86 (URL regex; raises generic `RuntimeError("Session expired...")`). `_get_page_for()` 189 calls `BrowserAuthState.from_config(self.config)` before `self.get_page(url)`. | |
| `bricklink/bricklink_cli/commands/auth.py` | Calls `create_auth_app(get_config, tool_name="bricklink", ...)`. 26 lines. | |
| `ebay/ebay_cli/browser.py` | Reference subclass — `SESSION_NAME="ebay"`, no overrides. Pure declarative. 23 lines. | |
| `google/google_cli/browser.py` | **OUT OF SCOPE.** Imports from `cli_tools_shared` (older sibling library), not `cli_tools_shared`. | |

### Authoritative facts established

1. **`auth-state.json` snapshot contains cookies + localStorage origins only** — IndexedDB, service workers, cache are NOT captured (`driver.py:625-627`).
2. **The persistent user-data-dir at `~/Library/Caches/cli-tools-browser/daemon/ud-<session>/` already survives across `browser_open()` calls.** `_cleanup_stale_session()` only kills processes + deletes singleton lock files. The earlier framing that "user-data-dir gets wiped on every browser_open()" was wrong. Only `clear_session()` → `data_delete()` rmtree's it.
3. **`state_load()` exceptions silently swallowed** at `auth.py:462`. Misdiagnoses real failures as "Session expired."
4. **Login is headed, commands are headless** (`auth.py:341` vs `auth.py:453`). `--headless=new` is the same Chromium runtime — service workers + IndexedDB work in it.
5. **Profile paths today already co-locate `.env` + `auth-state.json` + marker** under `~/.local/share/cli-tools/<tool>/.profiles/<profile>/`. Only the Chromium user-data-dir lives elsewhere (under `~/Library/Caches/`). The user's goal of co-location is half done.
6. **Scope correction:** "79 CLIs" is inflated. The actual count is `cli_tools_shared` consumers only. `cli_tools_shared` (used by at least `google`) is excluded — track as follow-up.

## Q&A Results

### Wave: Concurrency & Locking

**Q1:** Two concurrent commands against the same profile — Chrome refuses to share `--user-data-dir`. Behavior?
**A1:** **Fail fast.** Detect live SingletonLock + running PID; raise `BrowserAutomationError` with PID + hint. No flock waiting, no tmp clone.

**Q2:** Headed `auth login` and headless command overlap. Behavior?
**A2:** **Refuse + clear message.** Headless command exits with "Login in progress for profile `<p>`; finish or cancel auth login first." No blocking.

### Wave: Migration & Cleanup

**Q3:** Migration handling for legacy `ud-<session>/` and existing `auth-state.json` on rollout?
**A3:** **Wipe + force re-login.** Delete legacy state on first run; print clear "cli-tools browser auth was upgraded; please run `<tool> auth login` to re-authenticate." message. Every user re-authenticates once, per tool they actually use.

**Q4:** When delete legacy `~/Library/Caches/cli-tools-browser/daemon/ud-<session>/`?
**A4:** **As part of the first-run wipe** (consistent with q3). One deterministic transition per tool, no leftover legacy state.

### Wave: Opt-In Flag & Rollout

**Q5:** `USE_PERSISTENT_PROFILE` flag rollout strategy?
**A5:** **No flag at all.** User pushback: "is there a time when it should NOT use a persistent profile? Remove that env var." Persistent profile is the only code path.

**Q6:** Endgame for the flag?
**A6:** **Remove entirely** (already done by q5 — no flag was introduced in the first place). Consistent with fail-fast / one-path principles.

### Wave: Error UX & Detection

**Q7:** Tool-specific URL expiry check at `browser_runtime.py:76-86` — keep or remove?
**A7:** **Keep + auto-clear.** Keep bricklink's URL regex as a last-line defense. On match, call `clear_session()` then raise an actionable error naming the exact `auth login --force` command. Two layers of detection is fine.

**Q8:** Loud error message format for stale state?
**A8:** **Generic stale message.** `"Persistent browser profile is stale. Re-run auth login."` Tool-agnostic; user knows which CLI they're running.

### Wave: auth-state.json Regeneration

**Q9:** When regenerate `auth-state.json`?
**A9:** **On every successful `is_authenticated()`.** Piggyback on the existing TTL'd live check. Cheap, keeps cookies fresh for httpx code paths.

**Q10:** Missing `auth-state.json` but profile valid — lazy regenerate?
**A10:** **Yes, lazy regenerate.** First httpx-backed read triggers a headless `browser_open()` against `AUTH_CHECK_URL`, calls `state_save`, then proceeds. Transparent to caller.

### Wave: Daemon & BU_NAME Coupling

**Q11:** Daemon key with persistent profiles?
**A11:** **`<tool>-<profile>`** — e.g. `bricklink-default`, `bricklink-work`. Mirrors user-data-dir scope. Multiple profiles can run concurrently across different tools.

**Q12:** Runtime path length cap (`/tmp/cli-tools-bh/<key>`, AF_UNIX 104-byte limit)?
**A12:** **Hash long names.** If `<tool>-<profile>` exceeds threshold, hash to `bh-<sha8>`. Human-readable when short, safe when long.

### Wave: Headless/Headed Parity

**Q13:** Headless mode policy for commands?
**A13:** **Always `--headless=new`.** Same Chromium runtime as headed mode. Service workers + IndexedDB persist correctly. Keep current.

### Wave: Test Strategy

**Q14:** Test plan?
**A14:** **Unit + bricklink e2e.** Unit tests for path resolution, locking, migration in `cli-tools-shared`. Real `bricklink auth login` + at least one browser-backed read command (e.g. orders list) against live Bricklink as the e2e gate.

**Q15:** Rollout validation across remaining tools?
**A15:** **Per-tool live `auth status`.** The shared helper already does a live round-trip (`auth_commands.py:75-83`). Green = migrated successfully. Automate as a script.

**Q16:** Regression test for "browser_open() does not wipe user-data-dir"?
**A16:** **Write a regression test.** New unit test: open, write marker file in user-data-dir, close, re-open, assert marker still there. Locks down the invariant.

### Wave: Expiry Semantics

**Q17:** What does "session naturally expired" mean in the new world?
**A17:** **Live `is_authenticated()` only.** Profile is authoritative; expiry == live check returns False. Keep TTL cache (`AUTH_CHECK_TTL=300`) to avoid hammering.

### Wave: Backward Compatibility

**Q18:** Upgrade UX for users mid-session?
**A18:** **Always force re-login on upgrade** (consistent with q3). Detect legacy state, wipe, print one-time clear message. No best-effort migration of legacy cookies into new profile.

**Q19:** `cli_tools_shared` (used by `google`) in scope?
**A19:** **No — `cli_tools_shared` only.** Track `cli_tools_shared` migration as a follow-up project. The "79 tools" count gets revised downward to actual `cli_tools_shared` consumers.

### Wave: Profile Path Details

**Q20:** `chromium-profile/` or `chromium-profile/Default/`?
**A20:** **Pass `chromium-profile/`.** Chrome auto-creates `Default/` inside. Standard convention; clean `rmtree` for cleanup.

**Q21:** Final path location?
**A21:** **Co-locate with .env.** `~/.local/share/cli-tools/<tool>/.profiles/<profile>/browser-data/chromium-profile/`. Single per-profile root makes `auth logout` and cleanup atomic.

## Key Decisions Summary

1. **No flag, no opt-in.** Persistent profile is the only code path. Single base-class change in `cli-tools-shared`; all `cli_tools_shared`-based CLIs inherit at once.
2. **New profile location:** `~/.local/share/cli-tools/<tool>/.profiles/<profile>/browser-data/chromium-profile/` (Chrome auto-creates `Default/` inside).
3. **Migration:** wipe legacy state on first run + force re-login (per tool, per user, once).
4. **Concurrency:** fail fast on SingletonLock collisions, refuse mid-login overlaps with a clear message.
5. **Daemon key:** `<tool>-<profile>` with sha8 fallback for long names.
6. **Headless policy:** keep `--headless=new` for commands (same Chromium runtime as headed, persists everything we need).
7. **`auth-state.json` survives as a secondary artifact** for httpx code paths; regenerated on every successful `is_authenticated()`, lazily regenerated on first httpx need if missing.
8. **Loud failures:** `state_load` exceptions raise (generic message: "Persistent browser profile is stale. Re-run auth login."). Bricklink's URL-based `_check_session_expired` remains as last-line defense with auto-clear.
9. **Expiry semantics:** live `is_authenticated()` with `AUTH_CHECK_TTL=300` cache.
10. **Tests:** unit tests for path/lock/migration + bricklink e2e + per-tool `auth status` rollout gate + regression test for "browser_open preserves user-data-dir."
11. **Scope:** `cli_tools_shared` consumers only. `cli_tools_shared` consumers (e.g. `google`) tracked as follow-up.
