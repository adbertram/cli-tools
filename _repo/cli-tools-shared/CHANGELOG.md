# Changelog

## Unreleased

### Fixes
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
