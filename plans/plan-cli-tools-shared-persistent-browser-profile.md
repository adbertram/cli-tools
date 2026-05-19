# Implementation Plan: cli-tools-shared Persistent Chromium Profile Refactor

**Slug:** cli-tools-shared-persistent-browser-profile
**Level:** standard
**Discovery:** `plans/discovery-cli-tools-shared-persistent-browser-profile.md`
**Research:** `plans/research-cli-tools-shared-persistent-browser-profile.md`

---

## Overview

Switch `BrowserAutomation` in `cli-tools-shared` from a `storage_state` snapshot model (cookies + localStorage written to `auth-state.json`) to a **persistent Chromium user-data-dir** as the single source of truth. The httpx fast-path (`BrowserAuthState.from_config`) reads cookies live from the running browser-harness daemon via CDP — no on-disk JSON snapshot. Bricklink is the validation tool; all 62 `cli_tools_shared` consumers inherit the change via the base class — no per-tool code changes.

**No legacy handling.** No migration helper, no wipe script, no "please re-authenticate" warning. Users upgrading from the old version simply re-run `<tool> auth login` once; orphaned files under `~/Library/Caches/cli-tools-browser/daemon/` and old `auth-state.json` snapshots are ignored forever by the new code.

---

## Architecture decisions (frozen)

- **q1** Concurrent commands against the same profile: **fail fast** on a live SingletonLock; raise with PID + hint.
- **q2** Headed/headless overlap: B1's raw `BrowserHarnessError` is already actionable. No wrapper.
- **q3 / q4 / q18** **No migration scaffolding** — **supersedes discovery A18** ("detect legacy state, wipe, print one-time message"). Refined position: orphaned files are harmless; silent re-auth is simpler. New code never reads legacy paths.
- **q5 / q6** **No opt-in flag.** Persistent profile is the only code path.
- **q7** Keep `bricklink._check_session_expired()` as last-line defense; on match `try/finally` `clear_session()` and raise actionable `bricklink auth login --force` error.
- **q8** No silent excepts in browser-auth paths. Any stale-profile condition propagates as an unwrapped `BrowserHarnessError`.
- **q9 / q10** **Obsolete.** `auth-state.json` is deleted entirely; httpx reads cookies live from CDP. No regen, no piggyback, no lazy-load.
- **q11** Daemon key becomes `<tool>-<profile>` (e.g. `bricklink-default`).
- **q12** Hash daemon key to `bh-<sha8>` when raw key fails `^[A-Za-z0-9_-]{1,32}$`.
- **q13** Commands always run `--headless=new`.
- **q14 / q15 / q16** Unit tests + bricklink e2e + per-tool `auth status` rollout gate.
- **q17** Expiry = live `is_authenticated()`; keep `AUTH_CHECK_TTL=300` cache.
- **q19** Scope: `cli_tools_shared` consumers (62 tools). `cli_tools_shared` (e.g. `google`) is out of scope.
- **q20 / q21** Persistent user-data-dir path: `~/.local/share/cli-tools/<tool>/.profiles/<profile>/browser-data/chromium-profile/`. Chrome auto-creates `Default/` inside.

---

## Why this approach

- Persistent Chromium profile holds cookies (Default/Cookies SQLite), localStorage, IndexedDB, service workers, and cache natively.
- httpx code paths fetch cookies live from the running browser-harness daemon via CDP (`cookie_list()`). One source of truth.
- Subclasses (62 of them) are pure declarative — base class change inherits everywhere.
- Daemon socket stays at `/tmp/cli-tools-bh/<key>/` (short path, AF_UNIX-safe). Chrome's user-data-dir lives under `.local/share` alongside `.env`.

## Prerequisites

- macOS (scope is macOS-first).
- Existing `BrowserHarnessService` driver, `BaseConfig` profile machinery, and 62 inheriting CLIs.
- `bricklink` CLI installed and reachable (`bricklink --help`).

---

## TDD convention

Each step has **T:** (test, written and run first) and **C:** (code that makes T pass). Run T → confirm red → write C → run T → green.

---

## Implementation Steps

### Phase A — Path resolution

#### Step A1: `BaseConfig.get_persistent_profile_dir()`

**T:** Add to `cli-tools-shared/tests/test_config_profile_resolution.py`:
- `test_get_persistent_profile_dir_resolves_under_browser_data_dir` — asserts `config.get_persistent_profile_dir()` == `<browser_data_dir>/chromium-profile`.

**C:** `cli-tools-shared/cli_tools_shared/config.py` — add method on `BaseConfig` next to `get_browser_data_dir()` returning `self.get_browser_data_dir() / "chromium-profile"`. Paths belong to config, not BrowserAutomation.

**Why:** q21 — single source of truth for the persistent user-data-dir.

**Verify:** `pytest cli-tools-shared/tests/test_config_profile_resolution.py -k persistent_profile_dir -xvs`.

#### Step A2: `_session_name()` returns `<tool>-<profile>`

**T:** Add to `cli-tools-shared/tests/test_auth.py`:
```python
@pytest.mark.parametrize("profile,expected", [
    ("default", "bricklink-default"),
    ("work", "bricklink-work"),
    (None, "RAISES"),
])
def test_session_name_returns_tool_dash_profile(profile, expected): ...
```

**C:** `cli-tools-shared/cli_tools_shared/auth.py:93-97` — return `f"{tool}-{profile}"`. Raise loudly if either component is empty.

**Why:** q11 — daemon key mirrors per-profile scope.

**Verify:** `pytest cli-tools-shared/tests/test_auth.py::test_session_name_returns_tool_dash_profile -xvs`.

#### Step A3: `_safe_daemon_key()`

**T:** Add to `cli-tools-shared/tests/test_auth.py`:
- `test_safe_daemon_key_hashes_long_names` — input >32 chars → `^bh-[0-9a-f]{8}$`.
- `test_safe_daemon_key_hashes_names_with_unsafe_chars` — input with `/` or space → hashed.

**C:** `cli-tools-shared/cli_tools_shared/auth.py` — module-level helper alongside `_session_name`:
```python
_SAFE_KEY_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")
def _safe_daemon_key(session: str) -> str:
    if _SAFE_KEY_RE.fullmatch(session):
        return session
    return f"bh-{hashlib.sha256(session.encode()).hexdigest()[:8]}"
```

**Why:** q12.

**Verify:** `pytest cli-tools-shared/tests/test_auth.py -k safe_daemon_key -xvs`.

### Phase B — Concurrency + lifecycle

#### Step B1: Detect-and-refuse on live SingletonLock

**T:** Add to `cli-tools-shared/tests/test_browser_driver.py`:
- `test_cleanup_session_lock_raises_when_singletonlock_points_at_live_pid` — `os.readlink` → `"hostname-12345"`; `_pid_running(12345)` → True. Assert `BrowserHarnessError` with `"12345"` in message.
- `test_cleanup_session_lock_deletes_when_pid_is_dead` — `_pid_running(12345)` → False. Assert lock deleted; no raise.
- `test_cleanup_session_lock_treats_unparseable_target_as_stale` — `os.readlink` → `"garbage"`. Assert lock deleted.

**C:** `cli-tools-shared/cli_tools_shared/browser/driver.py` `_cleanup_session_lock_files()` at lines 339-357 — read symlink target, parse PID after last `-`, on parse failure delete (stale), on live PID raise `BrowserHarnessError(f"Browser session '{self.session}' is held by PID {pid}. Finish or kill it before retrying.")`. The B1 raw error is the user-facing message (no wrapper layer per code-eliminator finding 13).

**Why:** q1 — fail fast on real concurrency.

**Verify:** `pytest cli-tools-shared/tests/test_browser_driver.py -k cleanup_session_lock -xvs`.

#### Step B2: `clear_session()` rmtree + invalidate cached service

**T:** Add to `cli-tools-shared/tests/test_auth.py`:
- `test_clear_session_rmtrees_persistent_profile_dir` — pre-populate `<persistent_profile_dir>/Default/Cookies`. Call `clear_session()`. Assert dir gone.
- `test_clear_session_raises_when_rmtree_fails` — monkeypatch `shutil.rmtree` to raise `PermissionError`. Assert propagation.
- `test_clear_session_invalidates_cached_service` — populate `_get_service()` cache, call `clear_session()`, assert `self._service is None`.

**C:**
1. `auth.py:501-516` — `clear_session()` calls `self._get_service().data_delete()`, then `self._service = None`.
2. `driver.py:653-666` (`data_delete()`) — body becomes:
   ```python
   self.browser_close()
   shutil.rmtree(self._user_data_dir)
   ```
   Delete the surrounding `try/except Exception: pass` (656-659) and `try/except OSError` (662-665) blocks. No `ignore_errors=True`.

**Verify:** `pytest cli-tools-shared/tests/test_auth.py -k clear_session -xvs`.

#### Step B3: Bricklink `_check_session_expired()` — try/finally raise

**T:** Create `bricklink/tests/test_browser_runtime.py`:
- `test_check_session_expired_clears_session_and_raises_actionable_error` — mock page URL matching `r"identity\.lego\.com.*login"`. Assert `self.clear_session` called once AND raised error text == `"Bricklink session expired. Run 'bricklink auth login --force' to re-authenticate."`.
- `test_check_session_expired_no_match_does_not_clear` — page URL is `https://www.bricklink.com/orderList.asp`. Assert no clear, no raise.
- `test_check_session_expired_raises_actionable_even_if_clear_session_fails` — `clear_session()` raises. Assert the final exception still has the actionable Bricklink message.

**C:** `bricklink/bricklink_cli/browser_runtime.py:76-86`:
```python
def _check_session_expired(self, page):
    if self._matches_expired_url(page.url):
        try:
            self.clear_session()
        finally:
            raise RuntimeError(
                "Bricklink session expired. "
                "Run 'bricklink auth login --force' to re-authenticate."
            )
```
`finally` raises regardless — actionable message always surfaces. No wrapper, no exception registry (code-eliminator finding 14).

**Verify:** `pytest bricklink/tests/test_browser_runtime.py -xvs`.

### Phase C — State load/save changes + persistent_profile_dir wire-up

#### Step C1: Delete `state_load()` from the headless path

**T:** Add to `cli-tools-shared/tests/test_auth.py`:
- `test_get_page_does_not_load_storage_state_even_when_auth_state_file_exists` — pre-create a stale `auth-state.json`. Drive `get_page()`. Assert `_Service` mock's `state_load_calls` is empty.
- `test_browser_open_preserves_user_data_dir_across_opens` — open, write `<chromium-profile>/preserved.txt`, close, re-open, assert file still exists.

**C:** `cli-tools-shared/cli_tools_shared/auth.py:436-469` — delete the entire `target_url`/`state_file`/`has_state`/`state_load`/`open_url` block. Replace with:
```python
svc.browser_open(url or self.AUTH_CHECK_URL, headed=False, persistent_profile_dir=self.config.get_persistent_profile_dir())
if url:
    svc.goto(url)
self._page = svc
```

**Why:** q17 — persistent profile is authoritative.

**Verify:**
- `pytest cli-tools-shared/tests/test_auth.py -k "does_not_load_storage_state or preserves_user_data_dir" -xvs`
- `grep -n 'has_state\|state_load\|state_file\.exists' cli-tools-shared/cli_tools_shared/auth.py` → zero matches in `get_page()`.

#### Step C2: `browser_open()` receives `persistent_profile_dir`; delete legacy `_user_data_dir()` method

**T:** Add to `cli-tools-shared/tests/test_browser_driver.py`:
- `test_browser_open_uses_persistent_profile_dir_as_chrome_user_data_dir` — mock `subprocess.Popen`, capture argv, parse `--user-data-dir` value via existing `_command_user_data_dir` regex helper. Assert it equals the persistent profile dir passed in.
- `test_session_process_pids_filters_against_persistent_profile_dir` — register two fake Chrome processes with different `--user-data-dir`; assert only ours is returned.

**C:** `cli-tools-shared/cli_tools_shared/browser/driver.py`:
- Add required `persistent_profile_dir: Path` kwarg to `browser_open()`. Store on `self._user_data_dir` (attribute, not method).
- **Delete** the `_user_data_dir()` method at lines 157-160.
- **Convert callers** from `self._user_data_dir()` (call) to `self._user_data_dir` (attribute): driver.py:272 (browser_open argv build), driver.py:340 (_cleanup_session_lock_files path resolution), driver.py:395 (browser_open invocation path). Line 660 is rewritten by Step B2.
- `_session_process_pids()` filters against `self._user_data_dir`.
- Daemon socket/pid/log files continue at `/tmp/cli-tools-bh/<safe_key>/`.

**Verify:**
- `pytest cli-tools-shared/tests/test_browser_driver.py -k "persistent_profile_dir or session_process_pids" -xvs`
- `grep -n '_user_data_dir()' cli-tools-shared/cli_tools_shared/browser/driver.py` → zero matches.

### Phase D — Daemon key wire-up

#### Step D1: `BrowserHarnessService` receives the already-safe key

**T:** Add to `cli-tools-shared/tests/test_browser_driver.py`:
- `test_service_uses_safe_key_for_runtime_dir_and_bu_name` — construct `BrowserHarnessService("bricklink-default")`. Assert `_ensure_runtime_dir` received `"bricklink-default"` AND `BU_NAME` env in `_start_daemon` is `"bricklink-default"`.
- `test_service_uses_hash_for_long_session_name` — construct with `_safe_daemon_key`-applied 80-char input. Assert runtime dir and `BU_NAME` match.

**C:**
- `cli-tools-shared/cli_tools_shared/auth.py` `_get_service()` at line 99-103 — pass `_safe_daemon_key(self._session_name())` as the session arg.
- `cli-tools-shared/cli_tools_shared/browser/driver.py:127-141` — `BrowserHarnessService.__init__` trusts the caller, no internal re-sanitization. `_ensure_runtime_dir(self.session)`, `env["BU_NAME"] = self.session`.

**Why:** q11, q12.

**Verify:** `pytest cli-tools-shared/tests/test_browser_driver.py -k "service_uses_safe_key or service_uses_hash" -xvs`.

### Phase E — Cross-cutting tests + e2e gates

#### Step E1: Full shared-library test suite green

**Verify:** `pytest cli-tools-shared/tests bricklink/tests -x` → 0 failed, 0 errors.

#### Step E2: E2E manual checkpoint — happy path

**What:** From an interactive terminal on macOS:
1. `bricklink auth logout --profile default`
2. `bricklink auth login --profile default` → completes interactive login.
3. `bricklink orders list --profile default` → returns orders without re-auth.
4. `ls ~/.local/share/cli-tools/bricklink/.profiles/default/browser-data/chromium-profile/Default/` → exists with `Cookies`, `Local Storage/`.

**Why:** q14.

**Verify:** all 4 steps succeed; document outcome in PR.

#### Step E3: E2E manual checkpoint — interrupted login resilience

**What:**
1. `bricklink auth logout --profile default`
2. `bricklink auth login --profile default` → Ctrl+C before pressing Enter.
3. `ls .../chromium-profile/Default/SingletonLock` → either absent OR points at a dead PID (B1 handles both).
4. `bricklink orders list --profile default` → either succeeds OR fails with `"Bricklink session expired. Run 'bricklink auth login --force' to re-authenticate."` (from B3). NOT a Python traceback.

**Verify:** outcome matches a documented path; record which.

### Phase F — Rollout validation

#### Step F1: `discover_consumers()` public API + classifications-as-table

**T:** Add to `cli-tools-shared/tests/test_discovery.py` (new):
- `test_discover_consumers_finds_browser_py_under_cli_tools_shared_consumers` — fixture creates fake tool dirs; some import `cli_tools_shared`, one imports `cli_tools_shared`. Assert only the first set is returned.

Add to `cli-tools-shared/tests/test_validate_rollout.py` (new):
- `test_validate_rollout_classifies_green_red_unsupported` — monkeypatch `subprocess.run` per fake tool with exit 0, exit 1, and exit 2+stderr `"No such command 'auth'"`. Assert classifications.

**C:**
- Create `cli-tools-shared/cli_tools_shared/discovery.py` exposing `discover_consumers() -> list[Path]`. Globs `<repo_root>/*/[^_]*_cli/browser.py` and greps for `from cli_tools_shared`.
- Create `cli-tools-shared/scripts/validate_rollout.py`. Uses `discover_consumers()`. Classifications are a data table:
  ```python
  _CLASSIFICATIONS = [
      {"label": "green", "predicate": lambda r: r.returncode == 0, "fail_run": False},
      {"label": "unsupported", "predicate": lambda r: r.returncode != 0 and b"No such command 'auth'" in r.stderr, "fail_run": False},
      {"label": "red", "predicate": lambda r: r.returncode != 0, "fail_run": True},
  ]
  ```
  First matching predicate wins. Print summary; exit nonzero if any `fail_run=True` entry matched. For red tools, print the exact `<tool> auth login` re-auth command.

**Why:** q15 + code-eliminator finding 15 — shared public API for future audit scripts; classification rules are data.

**Verify:** `pytest cli-tools-shared/tests/test_discovery.py cli-tools-shared/tests/test_validate_rollout.py -xvs`.

### Phase G — Version + docs

#### Step G1: Bump version

**File:** `cli-tools-shared/pyproject.toml` line 7.
**What:** `version = "0.1.3"` → `version = "0.2.0"`.
**Verify:** `grep '^version' cli-tools-shared/pyproject.toml`.

#### Step G2: CHANGELOG entry

**File:** `cli-tools-shared/CHANGELOG.md` (new).
**Content:**
```
## 0.2.0 — 2026-05-16

### Breaking changes
- BrowserAutomation now uses a persistent Chromium user-data-dir at
  `~/.local/share/cli-tools/<tool>/.profiles/<profile>/browser-data/chromium-profile/`.
  Cookies, localStorage, IndexedDB, service workers, and cache all persist natively.
- `auth-state.json` is deleted. The httpx fast-path
  (`BrowserAuthState.from_config`) now reads cookies live from the
  browser-harness daemon via CDP.
- Users must re-run `<tool> auth login` once on upgrade. Orphaned legacy files
  under `~/Library/Caches/cli-tools-browser/` and old `auth-state.json`
  snapshots are ignored.

### Behavior changes
- Concurrent sessions against the same profile fail fast with a clear
  PID-naming error instead of stomping on each other's SingletonLock.
- Bricklink: `_check_session_expired()` auto-clears the session and raises
  `"Bricklink session expired. Run 'bricklink auth login --force'..."`.
- All silent excepts in browser-auth paths removed; failures raise.
- **httpx fast-path now starts Chrome on first call per process** via
  `live_cookies()`. Subsequent calls in the same process reuse the daemon.
  Budget ~1-2s for the first `BrowserAuthState.from_config(...)` call after
  a process starts.
```

**Verify:** `cat cli-tools-shared/CHANGELOG.md` shows the entry.

### Phase H — Eliminate `auth-state.json` (architectural pivot)

> Phase H and Phase C are independent — each deletes different sites. Recommended execution order: H1 first (largest delete; rewires `from_config`), then C1 (deletes residual `state_load` caller in `get_page`), then C2/D1 (path wire-up). E1 runs once all are green.

#### Step H1: Live CDP cookie read replaces `auth-state.json`

**T:**
- `cli-tools-shared/tests/test_http_session.py::test_from_config_reads_live_cookies_from_browser` — mock `config.get_browser().live_cookies()` → returns 2 cookies. Assert `BrowserAuthState.from_config(config)` returns a state object whose `cookies` list equals those 2.
- `test_from_config_raises_when_browser_has_no_session` — `live_cookies()` returns `[]`. Assert `BrowserAuthStateError` raised (no cookies means no session — this is fail-fast, not fallback: there is nothing to fall back TO).
- Existing tests that mock `auth-state.json` on disk: DELETE.

**C (multi-file deletion + targeted rewrite):**

1. **`cli-tools-shared/cli_tools_shared/http_session.py:60-65`** — rewrite `BrowserAuthState.from_config`:
   ```python
   @classmethod
   def from_config(cls, config) -> "BrowserAuthState":
       cookies = config.get_browser().live_cookies()
       if not cookies:
           raise BrowserAuthStateError(
               f"No browser session for {config._tool_name}. "
               f"Run '{config._tool_name} auth login'."
           )
       return cls(cookies=cookies, origins=[])
   ```

2. **`cli-tools-shared/cli_tools_shared/auth.py`** — add `live_cookies()` method on `BrowserAutomation`:
   ```python
   def live_cookies(self) -> list[dict]:
       """Fetch cookies from the running browser via CDP. Opens browser if not running."""
       svc = self._get_service()
       if not svc._opened:
           svc.browser_open(self.AUTH_CHECK_URL, headed=False,
                            persistent_profile_dir=self.config.get_persistent_profile_dir())
       return svc.cookie_list()
   ```

3. **DELETE** the following from `auth.py`:
   - `_save_auth_state()` (lines 202-230)
   - `_state_file_path()` (line ~135)
   - `_marker_path()`, `_write_marker()`, the `profile.json` marker concept
   - The `self._save_auth_state()` call in `is_authenticated()` (line 299) AND in `authenticate()` post-login save (line 370)
   - The `state_save` block in `close()` (lines 535-541)
   - `_on_authenticated` hook if it only existed for snapshot side effects (grep for callers first)
   - `_debug_file_state`, `_debug_service_state` if used only to debug auth-state.json content
   - **`has_session()` and `has_saved_session()` on `BrowserAutomation`** — delete entirely. Callers that need the check go through `self.config.has_saved_session()` (the single owner, see #6 below).

4. **DELETE** from `driver.py`:
   - `state_save()` (lines 620-632)
   - `state_load()` (lines 578-618)
   - `_local_storage_state()` (helper used only by state_save)

5. **Update `cli-tools-shared/cli_tools_shared/config.py`**:
   - Lines 702-710 (`BaseConfig.has_saved_session()`) — replace the dual-branch implementation (`profile.json` OR `browser-data` files) with a single check: `return (self.get_persistent_profile_dir() / "Default" / "Cookies").exists()`. No OR-fallback. Single source of truth.
   - Line 85 docstring — update the profile-layout description to remove references to `profile.json` and `auth-state.json`; replace with `chromium-profile/Default/`.
   - Line 468 comment — update to describe the new layout.

6. **Single-owner contract:** `BaseConfig.has_saved_session()` is the only definition of "does this profile have a usable session?". Callers that previously used `BrowserAutomation.has_session()` migrate to `self.config.has_saved_session()`. Grep for `\.has_session\(\)` / `\.has_saved_session\(\)` across the repo to find and update each caller.

**Verify:**
- `pytest cli-tools-shared/tests/test_http_session.py -xvs`
- `grep -rn 'auth-state\.json\|state_save\|state_load\|_save_auth_state\|_state_file_path\|profile\.json' --include='*.py' /Users/adam/Dropbox/GitRepos/cli-tools/ | grep -v __pycache__` → zero matches outside tests that target the now-deleted behavior (those tests are deleted per the T section).
- `grep -rn 'def has_session\|def has_saved_session' --include='*.py' /Users/adam/Dropbox/GitRepos/cli-tools/cli-tools-shared/` → exactly ONE match (`BaseConfig.has_saved_session` in `config.py`).
- `pytest cli-tools-shared/tests -x` — must remain green.

**Why:** code-eliminator TIER 6 — single source of truth (persistent profile); ~120 LoC deleted across auth.py + driver.py + http_session.py; ~30 LoC of new live-read code in their place. Net ~-90 LoC.

---

## Out of scope

- **`cli_tools_shared` consumers** (e.g. `google`, `ship7`). Separate migration; follow-up project.
- **Windows / Linux behavior.** Refactor targets macOS.
- **API-token-only CLIs** that don't use `BrowserAutomation`. Nothing to inherit.
- **Backporting cookies from any legacy state.** Users re-authenticate.
- **Live e2e tests in CI.** Bricklink e2e is a manual checkpoint (E2, E3).

---

## Risk register

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| `<tool>-<profile>` daemon key overflows AF_UNIX 104-byte budget | Med | `_safe_daemon_key()` hashes long/unsafe keys (A3). |
| Concurrent `auth login` and headless command corrupt the profile | Med | Detect-and-refuse on live SingletonLock PID (B1). |
| `live_cookies()` cold-start latency for pure-httpx flows | Cert | **Behavior change.** httpx fast-path now starts Chrome on first call per process via `live_cookies()`. Existing httpx-only callers (62 consumer tools) historically had zero browser-startup cost; first invocation now incurs a one-shot daemon launch (~1-2s on macOS). Subsequent calls in the same process reuse the running daemon. Documented in the CHANGELOG breaking-changes section so callers can budget for it. |
| 62-tool rollout reveals a tool with non-standard config that breaks `_session_name()` profile resolution | Med | `validate_rollout.py` (F1) flags failures per tool. Glob-based discovery picks up new tools automatically. |
| `live_cookies()` returns empty during a transient daemon hiccup → false `BrowserAuthStateError` | Low | Acceptable — fail-fast contract. User re-runs the command; the second invocation re-opens the daemon. No silent retry. |

---

## Simplicity check

- Files created: `validate_rollout.py`, `discovery.py`, `CHANGELOG.md`, `test_browser_runtime.py` (bricklink), `test_discovery.py`, `test_validate_rollout.py`. Six new files.
- Files deleted: none whole-file, but ~120 LoC removed from `auth.py`, `driver.py`, `http_session.py` (Step H1). Methods deleted: `_save_auth_state`, `_state_file_path`, `_marker_path`, `_write_marker`, `state_save`, `state_load`, `_local_storage_state`, `_user_data_dir()` (driver.py method form).
- One config method added (`get_persistent_profile_dir`), one BrowserAutomation method added (`live_cookies`), one module-level helper (`_safe_daemon_key`), one public discovery function (`discover_consumers`).
- 62 consumer files untouched.
- No flag, no env var, no migration scaffolding, no two-source-of-truth machinery.

---

## Success criteria

- [ ] `pytest cli-tools-shared/tests bricklink/tests -x` → 0 failed, 0 errors.
- [ ] E2 e2e round-trip succeeds.
- [ ] E3 interrupted-login resilience matches a documented path.
- [ ] `validate_rollout.py` shows green for `cli_tools_shared` consumer tools (after each user re-authenticates).
- [ ] `grep -rn 'auth-state\.json\|state_save\|state_load' cli-tools-shared/cli_tools_shared/` → zero matches.
- [ ] `cli-tools-shared` version is `0.2.0` and CHANGELOG.md documents the breaking change.
- [ ] `~/.local/share/cli-tools/bricklink/.profiles/default/browser-data/chromium-profile/Default/` exists after first login.
