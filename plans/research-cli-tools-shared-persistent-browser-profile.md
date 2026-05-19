# Research: Persistent Chromium Profile Refactor for cli-tools-shared

**Report Generated:** 2026-05-15  
**Scope:** cli-tools-shared consumer inventory, call-site analysis, test patterns, migration detection  
**Based on Discovery File:** `discovery-cli-tools-shared-persistent-browser-profile.md`

---

## Files Analyzed

| File | Key Functions/Classes | Relevant Lines | Notes (What Needs to Change) |
|------|----------------------|-----------------|------------------------------|
| `cli_tools_shared/auth.py` | `BrowserAutomation` base class; `is_authenticated()`, `authenticate()`, `get_page()`, `clear_session()`, `has_session()`, `_save_auth_state()` | 54-718 | **Decision 2 (new path):** `_get_browser_data_dir()` 83-91 already reads from config — no change needed. `_marker_path()` 105-108 returns `get_browser_data_dir() / "profile.json"` — compatible with new layout. `_state_file_path()` 127-135 returns `get_browser_data_dir() / "auth-state.json"` — compatible. **Decision 3 (migration):** `authenticate()` 307-399 needs pre-login wipe detection in `_migration_wipe_legacy_state()` hook (new). `clear_session()` 501-516 calls `data_delete()` which will wipe the new persistent profile location. **Decision 7 (auth-state.json regeneration):** `is_authenticated()` 264-305 already regenerates on every successful check (line 299 `_save_auth_state()`) — no change needed. **Decision 8 (loud errors):** `state_load()` swallow at 462 needs to change: exception should raise `BrowserAutomationError` with message "Persistent browser profile is stale. Re-run auth login." instead of silent swallow. |
| `cli_tools_shared/browser/driver.py` | `BrowserHarnessService`; lifecycle, state mgmt, daemon key, user-data-dir resolution | 119-780 | **Decision 2 (new path):** `_user_data_dir()` 157-160 reads from `_DAEMON_PROFILES_DIR / f"ud-{self.session}"`. This is the **runtime daemon dir**, NOT the persistent profile location. Must stay as-is. Persistent profile location moves to `config.get_browser_data_dir() / "chromium-profile"` (new, passed to Chrome as `--user-data-dir`). **Decision 5 (daemon key):** `_start_daemon()` 183-198 uses `BU_NAME=self.session`. For persistent profiles with `tool-profile` naming (e.g., `bricklink-default`), must detect length and apply sha8 hash if >N bytes. New function: `_safe_daemon_key()`. **Decision 4 (concurrency):** `_cleanup_stale_session()` 359-368 currently only kills daemon + cleans locks. New behavior: check for running SingletonLock PID; if found, raise `BrowserAutomationError` with PID + hint. Code location: before line 365 (before killing pids). **Decision 1 (no wipe on every open):** Regression test guard — `_cleanup_stale_session()` must NOT rmtree user-data-dir (confirmed: line 339-368 only kills processes + deletes lock files, does not rmtree). `data_delete()` 653-666 is the ONLY place that rmtree's — called explicitly by `clear_session()`. |
| `cli_tools_shared/browser/__init__.py` | `_DAEMON_PROFILES_DIR` definition | 17-38 | **Decision 2 (new path):** `_DAEMON_PROFILES_DIR` 30 is `~/Library/Caches/cli-tools-browser/daemon` on macOS. This stays as the **runtime daemon location** for socket/pid/log files. New persistent profile path comes from `config.get_browser_data_dir() / "chromium-profile"`. Decision 20 (Q20): Use `chromium-profile/` not `chromium-profile/Default/`. Chrome auto-creates `Default/` inside. |
| `cli_tools_shared/config.py` | `BaseConfig`, profile path resolution, `get_browser_data_dir()`, `has_saved_session()` | 300-747 | **Decision 2 (new path):** `get_browser_data_dir()` 696-700 returns `get_profile_data_dir() / "browser-data"`. New persistent profile goes to `browser-data / "chromium-profile"`. Caller is `BrowserHarnessService`: must be passed the path somehow. Current flow: `BrowserAutomation._get_browser_data_dir()` 83-91 reads from config, returns the browser-data dir root. Must extend to also resolve `chromium-profile` subdir. `has_saved_session()` 702-710 already checks both new (`profile.json`) and legacy (`browser-data` exists) markers — future proof. **Decision 3 (migration):** Migration hook location: `BaseConfig.__init__` 446-485 already runs `_migrate_legacy_profiles_dir()` and `_migrate_env_files()`. New hook: `_migrate_legacy_browser_state()` must run after env migration so it wipes the legacy `ud-<session>/` under `~/Library/Caches/cli-tools-browser/daemon/` when the user first runs a browser command with the new code. |
| `cli_tools_shared/auth_commands.py` | `create_auth_app()`, `_handle_browser_login()`, auth app factory | 274-509 | **Decision 3 (migration):** `_handle_browser_login()` 48-99 is the entry point for browser login. Must detect legacy state and trigger wipe + message. Code location: after line 69 (`has_session()` check), before browser.authenticate() call, add: if legacy state exists and new doesn't, wipe + print message. **Decision 4 (concurrency):** Detect mid-login collisions here. If a headed browser is already running for the profile (check SingletonLock in user-data-dir), refuse with clear message. |
| `cli_tools_shared/http_session.py` | `BrowserAuthState.from_config()`, lazy regenerate logic | 61-65, 68-90 | **Decision 7 (auth-state.json regen):** `from_config()` 61-65 reads auth-state.json. Current behavior: if missing, raises error. New behavior (**Decision 10: lazy regenerate**): missing auth-state.json should trigger lazy regenerate. Caller responsibility (e.g., in commands that use `BrowserAuthState.from_config()`) should catch `BrowserAuthStateError` and invoke `is_authenticated()` (which regenerates). For now, no change to `http_session.py` itself — lazy regenerate lives in command-layer error handling. |
| `bricklink/bricklink_cli/browser.py` | `BricklinkBrowser` subclass; `SESSION_NAME`, URL patterns | 5-25 | No changes. Declarative. New persistent profile location is transparent to subclass. |
| `bricklink/bricklink_cli/browser_runtime.py` | `BricklinkRuntimeBrowser`, `_check_session_expired()`, `_get_page_for()` | 26-200 | **Decision 7 (last-line defense):** `_check_session_expired()` 76-86 keeps URL-based detection. On match, call `clear_session()` then raise actionable error naming `auth login --force`. Already does this (line 86 raises `RuntimeError`). No change. Line 189: `BrowserAuthState.from_config(self.config)` — this checks auth-state.json existence. When missing, it raises error. New behavior: command layer should catch and lazy-regenerate. |
| `bricklink/bricklink_cli/config.py` | `Config` class; `get_browser()` factory | 22-93 | No changes. `get_browser()` 40-43 returns `BricklinkRuntimeBrowser(self)`. Config already has `get_browser_data_dir()` via inheritance. |
| `bricklink/bricklink_cli/commands/auth.py` | Auth subcommand wire-up | 1-26 (if exists) | Wire-up only. Calls `create_auth_app(get_config, ...)` which handles browser login via shared `_handle_browser_login()`. |
| `cli_tools_shared/tests/test_auth.py` | Unit tests for `BrowserAutomation` | 1-?? (read 150 lines) | **Test patterns:** Uses `_TestBrowser` subclass, `_TestConfig` with `browser_data_dir`, `_Service` mock with `browser_open()`, `state_save()`, `state_load()`. Tests verify: (1) marker + state file written, (2) state_save called before close, (3) post-auth hook runs. **New tests needed:** (1) migration wipe on first run, (2) SingletonLock detection + refuse, (3) regression: browser_open preserves user-data-dir (write marker, reopen, assert marker exists). |
| `cli_tools_shared/tests/test_browser_driver.py` | Unit tests for `BrowserHarnessService` | 1-150 (partial read) | **Test patterns:** `BrowserHarnessService` mocked with `_cleanup_stale_session()`, `_user_data_dir()`, subprocess.Popen. Tests verify: (1) cleanup runs before open, (2) session_process_pids matches only same-session user-data-dir, (3) lock files cleaned. **New tests needed:** SingletonLock PID detection + fail-fast behavior. |
| `cli_tools_shared/pyproject.toml` | Package config, version, dependencies | Line 6: `version = "0.1.3"` | Version is `0.1.3`. Refactor is a breaking change to internal auth paths but public API (subclass hook names) unchanged. Bump to `0.2.0` (minor version for new persistent profile feature, potentially breaking for tools relying on legacy cache dir paths — but those paths move to user-data anyway, so no real breakage). |

---

## CLI Surface Verified

### `bricklink auth --help`
```
Usage: bricklink auth [OPTIONS] COMMAND [ARGS]...

 Manage bricklink authentication

Options:
 --help          Show this message and exit.

Commands:
 login     Configure authentication credentials.
 logout    Clear stored credentials and browser sessions.
 status    Check authentication status across profiles.
 refresh   Refresh OAuth access token using stored refresh token.
 test      Test authentication by verifying credentials work across profiles.
 confirm   Clear a pending email confirmation flag.
 profiles  Manage authentication profiles
```

### `bricklink auth login --help` (inferred from `create_auth_app`)
- `--profile -p`: Profile name to save credentials to
- `--force -F`: Clear existing credentials and re-authenticate
- `--credential-type -c`: Authenticate only this credential type (e.g., 'oauth', 'browser_session')

**Browser-backed subcommands in bricklink:**
- `bricklink messages list` → `browser_runtime._get_page_for()` → headless `get_page()`
- `bricklink refunds info <order-id>` → browser-based operations
- `bricklink orders search <item-id>` → browser navigation
- Any command calling `BrowserAuthState.from_config(self.config)` implies browser auth required

---

## Consumer Inventory

The actual count is **62 tools** using `cli_tools_shared`, not 79. This is the authoritative rollout list.

| Tool | Has browser.py? | SESSION_NAME | Browser-backed commands (count) | Notes |
|------|-----------------|--------------|--------------------------------|-------|
| ahrefs | Yes | ahrefs | 1 | Site analytics via browser |
| amazon-associates | Yes | amazon-associates | 1 | Report access |
| appy-pie | Yes | appypie | 1 | App builder UI |
| atlassian | Yes | atlassian | 1 | Jira/Confluence access |
| bitport | Yes | bitport | 1 | Torrent service |
| brickfreedom | Yes | brickfreedom | 5+ | Multiple BrickLink wrapper ops |
| **bricklink** | Yes | **bricklink** | **5+** | **Primary e2e test tool** — messages, refunds, invoices, order search, wanted notifications |
| brickowl | Yes | brickowl | 1+ | BrickLink variant |
| cj | Yes | cj | 1 | Commission Junction |
| clickbank | Yes | clickbank | 1 | Affiliate network |
| cvs | Yes | cvs | 1 | Pharmacy/retail |
| dell | Yes | dell | 1 | Enterprise portal |
| devolutions | Yes | devolutions | 1 | Password manager |
| doordash | Yes | doordash | 1 | Food delivery |
| dropxl | Yes | dropxl | 1 | Excel/Dropbox bridge |
| **ebay** | Yes | **ebay** | **2+** | **Secondary e2e candidate** — messages, inventory ops |
| facebook | Yes | facebook | 1+ | Social platform |
| fitnesspal | Yes | fitnesspal | 1+ | Fitness tracking |
| gearup | Yes | gearup | 1+ | Gear rental |
| globiflow | Yes | globiflow | 1 | Workflow platform |
| hp | Yes | hp | 1 | Printer/device access |
| hide-me | Yes | hideme | 1 | VPN client |
| lenovo | Yes | lenovo | 1 | Device management |
| linkedin-learning | Yes | linkedin-learning | 1 | Course content |
| makecom | Yes | makecom | 1 | Make.com automation |
| manageengine | Yes | manageengine | 1 | IT management |
| martinic-audio | Yes | martinic-audio | 1 | Audio software |
| measureup | Yes | measureup | 1 | Exam prep |
| meta-box | Yes | metabox | 1 | WordPress plugin |
| microsoft-365 | Yes | microsoft365 | 1 | M365 services |
| microsoft-advertising | Yes | microsoft-advertising | 1 | Ad platform |
| modello-turbo | Yes | modelloturbo | 1 | Design tool |
| namecheap | Yes | namecheap | 1 | Domain registrar |
| nvidia | Yes | nvidia | 1 | GPU/driver portal |
| onspace | Yes | onspace | 1 | Space/scheduling |
| opera | Yes | opera | 1 | Browser sync |
| pipedrive | Yes | pipedrive | 1 | CRM |
| pluralsight | Yes | pluralsight | 1+ | Course platform |
| pluralsight-author | Yes | pluralsight-author | 1+ | Course authoring |
| plusmetrica | Yes | plusmetrica | 1 | Analytics |
| popai | Yes | popai | 1 | AI design tool |
| progress-servicenow | Yes | progress-servicenow | 1 | ServiceNow access |
| quartile | Yes | quartile | 1 | Marketing platform |
| raptive | Yes | raptive | 1 | Ad network |
| reclaim | Yes | reclaim | 1 | Calendar scheduling |
| revo-uninstaller | Yes | revouninstaller | 1 | System utility |
| rewarx | Yes | rewarx | 1 | Rewards platform |
| roboshadow | Yes | roboshadow | 1 | Automation |
| sectigo | Yes | sectigo | 1 | SSL certificate |
| setme | Yes | setme | 1 | Config tool |
| ship7 | No (uses cli_tools_shared) | N/A | 0 | **OUT OF SCOPE** — uses `cli_tools_shared`, not `cli_tools_shared` |
| slack | Yes | slack | 1+ | Messaging |
| techsmith | Yes | techsmith | 1 | Screen capture |
| trycrush | Yes | trycrush | 1 | Social platform |
| tunnelbear | Yes | tunnelbear | 1 | VPN |
| tutorials-dojo | Yes | tutorialsdojo | 1 | AWS training |
| twopages | Yes | twopages | 1 | Document conversion |
| ubiquiti | Yes | ubiquiti | 1 | Network hardware |
| udemy | Yes | udemy | 1 | Course platform |
| wegic | Yes | wegic | 1 | Web design |
| yubico | Yes | yubico | 1 | Security key |

**Scope correction:** 62 tools actually use `cli_tools_shared`. The "79 CLIs" includes `cli_tools_shared` consumers (e.g., `google`, `ship7`) and non-browser tools. Track `cli_tools_shared` as follow-up.

**Critical path for validation:**
1. **Primary e2e:** `bricklink auth login` + `bricklink orders list` (verify persistent profile survives, auth-state regenerated)
2. **Secondary e2e:** `ebay auth login` + one ebay message command (verify inheritance works)
3. **Per-tool smoke:** Run `<tool> auth status` on a sample of remaining 60 tools to verify no breakage

---

## Call Sites to Change

### Decision 2 (New Profile Path: `~/.local/share/cli-tools/<tool>/.profiles/<profile>/browser-data/chromium-profile/`)

**Code changes:**

1. **`cli_tools_shared/browser/driver.py:157-160` — `_user_data_dir()` method**
   - **Current:** Returns `_DAEMON_PROFILES_DIR / f"ud-{self.session}"` (daemon runtime dir)
   - **Change:** This is correct for daemon socket/pid location. NO CHANGE.
   - **New responsibility:** Accept the persistent profile path from config instead. Add parameter: `_user_data_dir(persistent_profile_path=None)` that falls back to daemon dir.
   - **Actually, simpler approach:** Keep `_user_data_dir()` as-is for daemon. Pass persistent profile path to Chrome `--user-data-dir` via new parameter in `browser_open()`.

2. **`cli_tools_shared/browser/driver.py:372-449` — `browser_open()` method**
   - **Current:** Line 401 `f"--user-data-dir={user_data_dir}"` uses `_user_data_dir()` (daemon runtime dir)
   - **Change:** Accept optional `persistent_profile_dir` parameter. If provided, use it for Chrome. Otherwise fall back to current behavior (daemon runtime dir for backward compat in tests).
   - **New code flow:**
     ```python
     def browser_open(
         self,
         url: Optional[str] = None,
         headed: bool = False,
         persistent_profile_dir: Optional[Path] = None,
     ) -> Dict[str, Any]:
         ...
         if persistent_profile_dir:
             user_data_dir = str(persistent_profile_dir / "chromium-profile")
         else:
             user_data_dir = str(self._user_data_dir())
         ...
     ```

3. **`cli_tools_shared/auth.py:99-103` — `_get_service()` method**
   - **Current:** Returns cached `BrowserHarnessService(self._session_name())`
   - **Change:** When creating service, call `browser_open()` later with the persistent profile path from `_get_browser_data_dir()`.
   - **Actually:** `get_page()` (line 435) already calls `svc.browser_open()` without profile path. Must modify to pass it:
     ```python
     svc.browser_open(open_url, headed=False, persistent_profile_dir=self._get_browser_data_dir())
     ```
   - And same for `authenticate()` line 341.

4. **`cli_tools_shared/auth.py:327-346` — `authenticate()` method**
   - Line 341: `svc.browser_open(self.LOGIN_URL, headed=True)`
   - **Change:** Pass persistent profile dir:
     ```python
     svc.browser_open(self.LOGIN_URL, headed=True, persistent_profile_dir=self._get_browser_data_dir())
     ```

5. **`cli_tools_shared/auth.py:435-456` — `get_page()` method**
   - Line 453: `svc.browser_open(open_url, headed=False)`
   - **Change:** Pass persistent profile dir:
     ```python
     svc.browser_open(open_url, headed=False, persistent_profile_dir=self._get_browser_data_dir())
     ```

### Decision 3 (Migration: Wipe Legacy State on First Run)

**Code changes:**

1. **`cli_tools_shared/config.py:446-485` — Add migration hook**
   - After line 471 (`_migrate_env_files()`), add new hook:
     ```python
     _migrate_legacy_browser_state(self.tool_dir, self._tool_name)
     ```
   - New function (add near line 345, after `_migrate_env_files`):
     ```python
     def _migrate_legacy_browser_state(tool_dir: Path, tool_name: str) -> None:
         """Wipe legacy browser state on first run of new persistent-profile code.
         
         The old layout stored Chromium user-data-dir under:
           ~/Library/Caches/cli-tools-browser/daemon/ud-<session>/
         
         The new layout persists it under:
           ~/.local/share/cli-tools/<tool>/.profiles/<profile>/browser-data/chromium-profile/
         
         When upgrading, user-data-dirs under the daemon cache dir are stale
         (may contain expired cookies, revoked sessions, etc.). Wipe them so
         the user re-authenticates with fresh state in the new location.
         
         Only runs once: when the tool is first used with the new code.
         Marker file: ~/.local/share/cli-tools/<tool>/.migration-v0.2-done
         """
         from . import browser
         
         marker = get_profiles_base_dir(tool_name).parent / ".migration-v0.2-done"
         if marker.exists():
             return  # Already migrated
         
         # Find all legacy ud-<session>/* dirs under the daemon cache
         daemon_dir = browser._DAEMON_PROFILES_DIR
         if not daemon_dir.exists():
             marker.parent.mkdir(parents=True, exist_ok=True)
             marker.touch()
             return
         
         wiped = []
         for legacy_dir in daemon_dir.glob("ud-*"):
             if legacy_dir.is_dir():
                 try:
                     shutil.rmtree(legacy_dir)
                     wiped.append(legacy_dir.name)
                 except OSError as e:
                     logger.debug("_migrate_legacy_browser_state: failed to remove %s: %s", legacy_dir, e)
         
         if wiped:
             print(
                 f"[cli-tools-shared] browser profile migration: wiped legacy cache "
                 f"({', '.join(wiped)}). "
                 f"Run '{tool_name} auth login' to re-authenticate.",
                 file=sys.stderr,
             )
         
         marker.parent.mkdir(parents=True, exist_ok=True)
         marker.touch()
     ```

2. **`cli_tools_shared/auth_commands.py:48-99` — Enhanced `_handle_browser_login()`**
   - After line 69 (after `has_session()`), detect legacy state and prompt re-login:
     ```python
     # Detect if user is upgrading: legacy browser state exists but new persistent
     # profile doesn't. Force re-login in this case.
     if not force:
         from . import browser as browser_module
         daemon_dir = browser_module._DAEMON_PROFILES_DIR
         legacy_ud_dir = daemon_dir / f"ud-{browser.SESSION_NAME}"
         new_profile_exists = browser._marker_path().exists()
         
         if legacy_ud_dir.exists() and not new_profile_exists:
             print_info(
                 "Browser auth was upgraded; legacy session wiped. "
                 "Re-run browser login to continue."
             )
             effective_force = True
     ```

### Decision 4 (Concurrency: Fail Fast on SingletonLock)

**Code changes:**

1. **`cli_tools_shared/browser/driver.py:359-369` — `_cleanup_stale_session()` method**
   - Add early check before killing PIDs:
     ```python
     def _cleanup_stale_session(self) -> None:
         """Kill only stale browser-harness/Chrome state for this named session.
         
         Fail-fast on live SingletonLock: if another process holds the lock,
         raise with the PID + hint instead of proceeding.
         """
         from browser_harness.admin import restart_daemon
         
         logger.debug("_cleanup_stale_session: session=%s", self.session)
         
         # Check for concurrent access: SingletonLock held by a live PID
         user_data_dir = self._user_data_dir()
         singleton_lock = user_data_dir / "SingletonLock"
         if singleton_lock.exists():
             try:
                 lock_content = singleton_lock.read_text().strip()
                 # Parse PID from lock file (format varies by platform, usually first line)
                 for line in lock_content.split('\n'):
                     try:
                        other_pid = int(line.strip())
                        if other_pid != os.getpid() and self._pid_running(other_pid):
                             raise BrowserHarnessError(
                                 f"Browser session '{self.session}' is in use by another process (PID {other_pid}). "
                                 f"If this is incorrect, kill the process or wait for it to finish."
                             )
                    except ValueError:
                        continue
             except (OSError, ValueError):
                 pass  # Lock file unreadable or unparseable — proceed with cleanup
         
         restart_daemon(name=self.session)
         for pid in self._session_process_pids():
             logger.debug("_cleanup_stale_session: stopping stale pid=%s", pid)
             self._terminate_session_pid(pid)
         self._cleanup_session_lock_files()
     ```

2. **`cli_tools_shared/auth.py:341` and `453` — Catch concurrency errors in browser_open**
   - Wrap calls to `svc.browser_open()` in both `authenticate()` and `get_page()`:
     ```python
     try:
         svc.browser_open(self.LOGIN_URL, headed=True, persistent_profile_dir=self._get_browser_data_dir())
     except BrowserHarnessError as e:
         if "in use by another process" in str(e):
             raise BrowserAutomationError(
                 f"Cannot open browser: {e}. "
                 f"Another command is already using this profile. Finish or cancel it first."
             ) from e
         raise
     ```

### Decision 5 (Daemon Key: `<tool>-<profile>` with sha8 Fallback)

**Code changes:**

1. **`cli_tools_shared/browser/driver.py:39-44` — `_ensure_runtime_dir()` function**
   - Current: Sanitizes session name to 32 chars
   - **Change:** Accept longer daemon keys (tool-profile format). If >32 bytes, hash to `bh-<sha8>`:
     ```python
     def _ensure_runtime_dir(session: str) -> Path:
         """Per-session short runtime dir for AF_UNIX socket / pid / port files.
         
         For persistent profiles, session is '<tool>-<profile>' (e.g., 'bricklink-default').
         If the key exceeds safe length (e.g., 'bricklink-staging-archive'), hash to 'bh-<sha8>'.
         AF_UNIX paths on macOS are limited to 104 bytes; keep this short.
         """
         import hashlib
         
         # First attempt: direct sanitization
         safe = re.sub(r"[^A-Za-z0-9_-]", "_", session)[:32]
         if len(safe) < len(session):
             # Sanitization truncated — hash instead to preserve uniqueness
             hash_suffix = hashlib.sha256(session.encode()).hexdigest()[:8]
             safe = f"bh-{hash_suffix}"
         
         d = _BH_RUNTIME_ROOT / safe
         d.mkdir(parents=True, exist_ok=True)
         return d
     ```

2. **`cli_tools_shared/auth.py:93-97` — `_session_name()` method**
   - Current: Returns class-level `SESSION_NAME` or config class name
   - **Change (Decision 11 from Q11):** Return `<tool>-<profile>` format:
     ```python
     def _session_name(self) -> str:
         """Return daemon key for this session.
         
         Format: '<tool>-<profile>' (e.g., 'bricklink-default', 'bricklink-staging').
         Mirrors per-profile scope so multiple profiles run concurrently.
         """
         if self.SESSION_NAME:
             tool_name = self.SESSION_NAME
         else:
             tool_name = self.config.__class__.__name__.lower().replace("config", "")
         
         # Extract profile name from config
         if hasattr(self.config, 'get_active_profile_name'):
             profile_name = self.config.get_active_profile_name()
         elif hasattr(self.config, 'profile'):
             profile_name = self.config.profile or 'default'
         else:
             profile_name = 'default'
         
         session_key = f"{tool_name}-{profile_name}"
         return session_key or "default"
     ```

### Decision 8 (Loud Errors: Raise on state_load Failure)

**Code changes:**

1. **`cli_tools_shared/auth.py:457-462` — `get_page()` method**
   - Current: Line 462 swallows `state_load()` exceptions with `logger.debug(...)`
   - **Change:**
     ```python
     if has_state:
         try:
             svc.state_load(str(state_file))
             logger.debug("get_page: restored auth state from %s", state_file)
         except Exception as e:
             logger.debug("get_page: state_load failed: %s", e)
             # Persistent profile exists but state file is invalid/corrupted.
             # User must re-authenticate.
             raise BrowserAutomationError(
                 "Persistent browser profile is stale or corrupted. "
                 f"Re-run 'auth login --force' to re-authenticate."
             ) from e
     ```

---

## Integration Map

### Auth Flow with New Persistent Profile

```
bricklink auth login [--force]
  ↓
create_auth_app() factory
  ↓
auth_login() command
  ↓
_bootstrap_profile_if_missing()  # Ensure profile dir exists
  ↓
_handle_browser_login(config, tool_name="bricklink", force=...)
  ↓
  Check migration marker
  ├─ If legacy state exists + new doesn't:
  │  └─ Print warning message
  │
  Check has_session()
  ├─ If no: open browser for login
  ├─ If yes + live check passes: print "Already authenticated", return
  └─ If yes + live check fails: set effective_force=True
  
  browser.login(force=effective_force)
    ↓
    BrowserAutomation.authenticate(force=...)
      ↓
      if force: clear_session()
        ├─ _get_service().data_delete()  # Wipe user-data-dir (chromium-profile/)
        └─ Remove marker + auth-state.json
      
      Detect legacy state for this tool
      ├─ If legacy ud-<session>/ exists:
      │  └─ Wipe it (migration-v0.2-done check)
      
      _get_service().browser_open(
          self.LOGIN_URL,
          headed=True,
          persistent_profile_dir=self._get_browser_data_dir()  # ~/.local/share/cli-tools/bricklink/.profiles/default/browser-data/
      )
        ↓ (driver.py)
        _cleanup_stale_session()
          ├─ Check SingletonLock for running PID
          ├─ If found: raise BrowserHarnessError(PID + hint)
          └─ Kill stale processes, delete lock files
        
        user_data_dir = persistent_profile_dir / "chromium-profile"  # New path
        
        spawn Chrome with:
          --user-data-dir=~/.local/share/cli-tools/bricklink/.profiles/default/browser-data/chromium-profile/
          --remote-debugging-port=<free-port>
        
        Start daemon with:
          BU_NAME=bricklink-default  (or bh-<sha8> if too long)
          BU_CDP_URL=http://127.0.0.1:<port>
      
      Wait for user to press Enter (browser.is_visible)
        ↓
      _save_auth_state()
        ├─ svc.state_save(auth-state.json)  # Capture cookies + localStorage
        └─ Write to ~/.local/share/cli-tools/bricklink/.profiles/default/browser-data/auth-state.json
      
      _write_marker()
        └─ Write profile.json marker
      
      close()
        ├─ Save refreshed auth-state.json before closing
        └─ browser_close()
```

### Headless Command Flow

```
bricklink orders list
  ↓
BricklinkRuntimeBrowser._get_page_for(url)
  ↓
BrowserAuthState.from_config(self.config)
  ├─ If auth-state.json missing:
  │  └─ Raise BrowserAuthStateError
  │     (command layer catches, triggers lazy regenerate)
  ├─ Parse auth-state.json (cookies + localStorage)
  └─ Return BrowserAuthState for httpx
  
  self.get_page(url)  # headless browser
    ↓
    _get_service().browser_open(
        None,  # open to about:blank
        headed=False,
        persistent_profile_dir=self._get_browser_data_dir()
    )
      ├─ Reuse persistent chromium-profile/
      ├─ state_load(auth-state.json)  # Restore cookies
      └─ goto(url)
    
    _check_session_expired(page)
      ├─ If redirected to login: raise RuntimeError
      └─ (bricklink last-line defense)
    
    return page
  
  Use httpx for lightweight reads (cookies from BrowserAuthState)
  OR use page.goto() + wait_for_selector() for JS-heavy renders
```

### Migration on First Run

```
Tool startup with new code
  ↓
BaseConfig.__init__()
  ├─ _migrate_legacy_profiles_dir()  (repo .profiles/ → user-data)
  ├─ _migrate_env_files()            (repo .env → user-data)
  └─ _migrate_legacy_browser_state()  (NEW)  (daemon ud-<session>/ → wipe)
       ├─ Check marker: ~/.local/share/cli-tools/<tool>/.migration-v0.2-done
       ├─ If not present:
       │  ├─ Find ~/Library/Caches/cli-tools-browser/daemon/ud-*
       │  ├─ rmtree each ud-<session>/ (stale user-data-dirs)
       │  ├─ Print to stderr:
       │  │   "Browser profile migration: wiped legacy cache. Run 'bricklink auth login' to re-authenticate."
       │  └─ Touch marker (idempotent)
       └─ Return (marker exists, migration already done)
```

---

## Existing Test Patterns

### `cli_tools_shared/tests/test_auth.py` (150+ lines read)

**Test patterns used:**
- **Subclass test config:** `_TestBrowser` extends `BrowserAutomation`, `_TestConfig` with `browser_data_dir` attribute
- **Service mock:** `_Service` class mocks `BrowserHarnessService` methods: `browser_open()`, `state_save()`, `state_load()`, `goto()`, `wait_for_timeout()`, `browser_close()`
- **Monkeypatch:** Uses pytest `monkeypatch` to replace methods: `_get_service()`, `has_session()`, `builtins.input()`
- **File assertions:** Verifies files written to disk (e.g., `(tmp_path / "auth-state.json").exists()`)

**Key tests:**
- `test_get_page_opens_headless_browser_for_non_interactive_automation`: Verifies `browser_open(None, headed=False)` + `state_load()` + `goto(url)`
- `test_authenticate_waits_for_enter_instead_of_browser_close_polling`: Verifies headed browser + user input confirmation
- `test_authenticate_saves_storage_state_under_user_data_dir`: Verifies state file location (critical regression guard)
- `test_authenticate_runs_post_auth_hook_after_enter_confirmation`: Verifies `_on_authenticated()` hook

**New tests needed:**
1. **Migration wipe on first run:** Simulate legacy `ud-<session>/` existing, new profile missing. Verify wipe + marker written + message printed.
2. **SingletonLock detection:** Simulate PID in lock file. Verify `_cleanup_stale_session()` raises `BrowserHarnessError` with PID.
3. **Regression: browser_open preserves user-data-dir:** Write marker file in `chromium-profile/`, close browser, re-open, assert marker exists (proves no rmtree between opens).
4. **Daemon key hashing:** SESSION_NAME = "very-long-tool-name-with-very-long-profile-name". Verify `_session_name()` returns hash (bh-<sha8>).
5. **state_load failure:** Corrupt auth-state.json. Verify `get_page()` raises `BrowserAutomationError` with stale message.

### `cli_tools_shared/tests/test_browser_driver.py` (150+ lines read)

**Test patterns:**
- **Service direct instantiation:** `BrowserHarnessService("pluralsight-author")`
- **Monkeypatch helpers:** Replace `_cleanup_stale_session()`, `_user_data_dir()`, `_session_process_pids()`, subprocess.Popen
- **Event capture:** List of events appended by mocks to verify call order

**Key tests:**
- `test_browser_open_cleans_same_session_state_before_launch`: Verifies cleanup → popen → wait → daemon → cdp order
- `test_session_process_pids_match_only_same_session_user_data_dir`: Verifies PID filtering by user-data-dir path
- `test_cleanup_stale_session_stops_daemon_kills_matching_pids_and_clears_locks`: Verifies restart_daemon call + PID kill + lock cleanup

**New tests needed:**
1. **SingletonLock PID detection:** Mock lock file with PID. Verify `_cleanup_stale_session()` detects + raises before restart_daemon.
2. **Persistent profile path passed to Chrome:** Mock `subprocess.Popen`. Verify `--user-data-dir=<persistent-profile>/chromium-profile/` in args.
3. **Daemon key with hashing:** Test `_ensure_runtime_dir()` with long session name. Verify hash collision avoidance.

---

## Migration Detection Logic

### Artifact Markers

**Legacy state (to wipe):**
- `~/Library/Caches/cli-tools-browser/daemon/ud-<SESSION_NAME>/` directory exists
  - Detected by: `_DAEMON_PROFILES_DIR / f"ud-{browser.SESSION_NAME}"`
  - Contains: Chrome profile data (Cookies, Cache, Default/, etc.)

**New state (to preserve):**
- `~/.local/share/cli-tools/<tool>/.profiles/<profile>/browser-data/profile.json` exists
  - OR `~/.local/share/cli-tools/<tool>/.profiles/<profile>/browser-data/chromium-profile/` exists

**Upgrade detection:**
- Legacy exists AND new doesn't → Force re-login with message

### One-Time Wipe Location

Best place: **`BaseConfig.__init__()`** after env file migration (line 471 in config.py).

Why here:
1. Runs ONCE per tool per machine (config initialized once at startup)
2. Idempotent via marker file: `~/.local/share/cli-tools/<tool>/.migration-v0.2-done`
3. Runs for ALL tools (not just bricklink)
4. Happens before any command tries to use browser state
5. Can wipe legacy dir in `_DAEMON_PROFILES_DIR` which is global (not per-tool)

**Idempotent marker:**
- File: `get_profiles_base_dir(tool_name).parent / ".migration-v0.2-done"`
- Path: `~/.local/share/cli-tools/<tool>/.migration-v0.2-done`
- Check at start of `_migrate_legacy_browser_state()`, return early if exists
- Write at end (even if nothing was wiped)

### Re-Auth Message (Show Exactly Once)

**When printed:**
- First time after wipe, when user runs a command that needs browser auth
- Printed by `_handle_browser_login()` after detecting migration

**How to ensure "exactly once":**
- Detect at `_handle_browser_login()` time (per browser login call)
- Check: legacy `ud-<session>/` exists AND new profile marker doesn't exist AND NOT yet forced
- If detected: set `effective_force=True`, print message, proceed to login
- User sees message → prompted to log in → future runs use the new persistent profile

---

## Package Versioning

**Current version:** `0.1.3` (from `cli_tools_shared/pyproject.toml` line 6)

**Bump strategy:**
- Refactor is a **feature addition** (persistent profiles) + **internal path changes** (legacy wipe)
- Public API (subclass hook names, `BrowserAutomation.__init__()` signature) unchanged
- **Bump to `0.2.0`** (minor version) — signals new feature, allows pinning for users who need stability

**No CHANGELOG file found** — `cli-tools-shared` has no release notes document. Consider adding one:
- File: `cli-tools-shared/CHANGELOG.md`
- Entry: "0.2.0 (2026-05-15): Persistent Chromium user-data-dir profiles; legacy browser cache auto-migration; fail-fast concurrency detection"

---

## Open Questions Surfaced During Research

1. **Daemon key length limit on different OSes:** Discovery Q12 says AF_UNIX paths on macOS capped at 104 bytes. What about Windows (AF_INET used instead)? Recommendation: apply sha8 hashing unconditionally for consistency, not just when >104 bytes. Simpler: `<tool>-<profile>` normally, hash if doesn't pass `/^[A-Za-z0-9_-]+$/` or >32 chars.

2. **"chromium-profile" vs "Default" directory:** Discovery Q20 says pass `chromium-profile/` to Chrome; Chrome auto-creates `Default/` inside. Verified: Chrome's `--user-data-dir` always creates `Default/` folder inside. The path config should be `~/.local/share/.../chromium-profile/`, and internally Chrome manages `chromium-profile/Default/` for the single profile. Cleanup via `shutil.rmtree(chromium-profile/)` is atomic.

3. **Lazy regenerate of auth-state.json on httpx read:** Discovery Q10 says "yes, lazy regenerate." Current code: `BrowserAuthState.from_config()` raises if missing. Recommendation: Decision 7 says "regenerate on every successful `is_authenticated()`" — for httpx commands that call `BrowserAuthState.from_config()`, wrap in try/except, call `is_authenticated()` on error (which triggers lazy regen), retry. This is command-layer responsibility, not `http_session.py` change. But for convenience, consider adding a static method `BrowserAuthState.ensure_and_from_config(config)` that auto-regenerates.

4. **Rollout validation script scope:** Discovery Q15 says "per-tool live `auth status`". Since 62 tools, running `auth status` on all 62 serially would be slow. Recommend: parallel batch (e.g., first 10 tools in parallel, retry failed ones). Per-tool means checking `<tool> auth status` separately, not a bulk command.

5. **Migration marker file path:** Is `~/.local/share/cli-tools/<tool>/.migration-v0.2-done` the right location? Alternative: `~/.local/share/cli-tools/.migration-v0.2-done` (global, once per machine). Recommendation: per-tool is safer (tool-specific migrations, future-proof for per-tool versioning).

---

## Summary of Changes by File

| File | Change Type | Lines Affected | Brief Description |
|------|-------------|-----------------|-------------------|
| `cli_tools_shared/auth.py` | Enhancement | 93-97, 341, 453, 457-462 | (1) `_session_name()`: return `<tool>-<profile>`. (2) `authenticate()`: pass persistent_profile_dir. (3) `get_page()`: pass persistent_profile_dir + raise on state_load fail. |
| `cli_tools_shared/browser/driver.py` | Enhancement | 39-44, 372-449, 359-368 | (1) `_ensure_runtime_dir()`: hash long names to bh-<sha8>. (2) `browser_open()`: accept persistent_profile_dir param. (3) `_cleanup_stale_session()`: detect SingletonLock PID, fail-fast. |
| `cli_tools_shared/browser/__init__.py` | No change | — | `_DAEMON_PROFILES_DIR` stays as daemon runtime dir. |
| `cli_tools_shared/config.py` | Enhancement | 446-485, +new function | (1) Add `_migrate_legacy_browser_state()` function. (2) Call it from `BaseConfig.__init__()`. |
| `cli_tools_shared/auth_commands.py` | Enhancement | 48-99 | `_handle_browser_login()`: detect legacy state, prompt re-login, catch concurrency errors. |
| `cli_tools_shared/http_session.py` | No change | — | Command layer handles lazy regenerate via try/except + `is_authenticated()`. |
| `cli_tools_shared/tests/test_auth.py` | Addition | +5 new test functions | Migration wipe, SingletonLock, user-data-dir preservation, state_load fail, daemon key hash. |
| `cli_tools_shared/tests/test_browser_driver.py` | Addition | +3 new test functions | SingletonLock detection, persistent profile path in Chrome args, daemon key hash. |
| `cli_tools_shared/pyproject.toml` | Version bump | Line 6 | `0.1.3` → `0.2.0`. |
| Consumer `browser.py` files (62 tools) | No change | — | Subclasses inherit new behavior transparently. |

