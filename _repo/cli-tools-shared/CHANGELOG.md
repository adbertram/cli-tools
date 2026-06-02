# Changelog

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
