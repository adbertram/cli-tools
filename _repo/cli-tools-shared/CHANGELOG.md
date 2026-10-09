# Changelog

## Unreleased

### Added
- `BrowserAutomation.AUTH_LOGIN_FORM_LINK_SELECTOR`: a declarative hook for
  services whose `LOGIN_URL` lands on a page that only links to the real
  credential form (e.g. a marketing page whose "LOGIN" link starts an
  `/oauth/authorize` redirect). `_complete_noninteractive_login` follows
  that link and waits for the username control before submitting, so
  subclasses no longer need to override the method for this. Globiflow
  moved onto it. Tests: `tests/test_auth.py`.

### Fixes
- A CLI invocation now runs the secret manager once per profile secret instead
  of once per config build. The command credential check and the API client
  each built a `BaseConfig`, so every call spawned `secrets.sh get` twice for
  the same token (airtable: ~0.1s of each call). `_get_secret_value` memoizes
  successful reads per process, keyed by secret name and profile path; a missing
  secret or a secret-manager error is never stored and fails on every lookup,
  and `_set_secret_value` / `_delete_secret_value` (auth login, `_clear`,
  profile rename) evict that secret name first. Tests:
  `tests/test_secret_resolution_cache.py`.
- `bounded_read.run_bounded_read` works on macOS under Python 3.11 and 3.12, the
  versions the package declares: it called `os.waitid`, which macOS only has from
  Python 3.13, so every bounded read raised `AttributeError` there. Where `os.waitid`
  is missing it now watches the owned leader's exit through a kqueue
  `EVFILT_PROC`/`NOTE_EXIT` event, which, like `WNOWAIT`, never reaps it, so the
  PID/PGID stays reserved until cleanup. Tests: `tests/test_bounded_read.py`.
- Every engine launch of the real Google Chrome app (CDP, Playwright,
  Webwright local CDP, manual login) now waits while a Tether UI lease holds
  the `remote-bare` demo desktop (`warden status --provider remote-bare`, any
  state), polling every 10s and failing with the holding lease after 600s.
  A Chrome from the same bundle, even headless, made Ronin prep's
  by-name Chrome lookups hit the wrong process (agent-issues#1277). A process
  inside the lease's own Tether session is not held; a host without
  `~/.tether/venv/bin/warden` is never held; an unreadable ledger fails the
  launch. `cli_tools_shared/browser/desktop_lease.py`, tests:
  `tests/test_browser_desktop_lease.py`.
- `data_cache.cached` no longer refuses to serve cached values for
  non-browser methods on a multi-credential CLI. `_cache_allowed_for_instance`
  gated EVERY cached method on a saved browser session whenever the tool
  declared `browser_session` among its `CREDENTIAL_TYPES`, so on a machine with
  no saved session an OAuth- or API-key-backed cached read never hit its cache
  and re-issued the (sometimes metered) upstream call every time. The gate now
  keys off the decorated method's OWN credential: declare it with
  `@cached(credential_type=CredentialType.BROWSER_SESSION)`, or let it be
  inferred when the tool declares exactly one credential type. Single-credential
  browser CLIs are unaffected. Mixed-credential CLIs (bricklink, brickowl,
  clickbank, ebay) now cache their non-browser reads; a browser-backed cached
  method on such a CLI must declare `credential_type` to keep the gate.
  Tests: `tests/test_data_cache.py`.
- `press()` no longer double-types every printable character.
  `browser_harness.helpers.press_key` dispatched `text` on BOTH the `keyDown`
  event and a separate `char` event; Chrome inserts the character once for each,
  so `locator.press("4")` on an empty input left it holding `"44"` and
  `fill_input()` (which types char-by-char via `press_key`) doubled every field.
  `text` now rides on the `keyDown` event only — Chrome still synthesizes the
  `keypress` from it, so `Enter` keeps its `\r` payload and listeners checking
  `e.key`/`e.keyCode` are unaffected. Non-printable keys (Enter, Tab, Backspace,
  arrows) were never affected. This reaches every CLI through
  `BrowserHarnessService.keyboard_press` and the `_ServiceLocator.press` /
  `_ServiceElement.press` wrappers. Tests:
  `tests/test_browser_harness_helpers.py`, `tests/test_browser_driver.py`.
- browser-harness daemon startup no longer fails on a transient CDP WS
  opening-handshake timeout. A just-spawned Chrome can accept the TCP
  connection but be too busy (profile load, host load) to complete the
  WebSocket upgrade before websockets' 10s open_timeout, so the daemon died
  with `fatal: CDP WS handshake failed: timed out during opening handshake`
  even though the parent had proven the endpoint live via `/json/version`
  moments earlier — an immediate identical CLI rerun succeeded. Neither
  `_spawn_daemon` retry classifier covered this class: the transient one only
  matches `BU_CDP_URL=... unreachable`, and the chrome://inspect prompt branch
  is gated to local-discovery mode (BU_CDP_WS unset). `browser_harness.daemon`
  now retries the SAME handshake up to `HANDSHAKE_ATTEMPTS` (3) times with
  growing backoff (`connect_cdp`), retrying only the timeout class
  (`_is_transient_handshake_timeout`) — 403/bad-URL handshake failures still
  fail immediately, and the final error text is unchanged so admin.py's
  failure classifiers keep matching. Tests:
  `tests/test_browser_harness_daemon_handshake.py`.

## 0.2.0 — 2026-05-16

### Breaking changes
- BrowserAutomation now uses a persistent Chromium user-data-dir at
  `~/.local/share/cli-tools/<tool>/authentication_profiles/<profile>/browser-data/chromium-profile/`.
  Cookies, localStorage, IndexedDB, service workers, and cache all persist natively.
- The browser-state snapshot file is deleted. The httpx fast-path
  (`BrowserAuthState.from_config`) now reads cookies live from the
  browser-harness daemon via CDP.
- Users must re-run `<tool> auth login` once on upgrade. Orphaned legacy files
  under `~/Library/Caches/cli-tools-browser/` and old snapshot
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
