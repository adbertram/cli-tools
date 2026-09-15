# Lightpanda Browser Backend Spike - Implementation Summary

## What Was Done

### 1. Core Implementation

**New Files:**
- `cli_tools_shared/browser/lightpanda_service.py` (~700 lines)
  - `LightpandaBrowserService` class implementing the browser service interface
  - Launches `lightpanda serve` subprocess
  - Connects via Playwright's CDP client
  - Cookie persistence via JSON file
  - Full compatibility with `BrowserHarnessService` API

**Modified Files:**
- `cli_tools_shared/auth.py`
  - Updated `BrowserAutomation._get_service()` to support backend selection
  - Reads `CLI_TOOLS_BROWSER_BACKEND` environment variable
  - Supports: `lightpanda`, `playwright`, `webwright`, or default (Chrome)

- `cli_tools_shared/browser/__init__.py`
  - Added lazy-loaded exports for `LightpandaBrowserService` and `LightpandaServiceError`

### 2. Documentation

**Created:**
- `docs/lightpanda-backend.md` - Comprehensive guide covering:
  - Performance comparison (Chrome vs Lightpanda)
  - Installation instructions
  - Usage examples
  - Architecture explanation
  - Known issues and workarounds
  - Production considerations
  - Future work

### 3. Testing & Examples

**Test Files:**
- `tests/test_lightpanda_smoke.py` - Smoke tests for:
  - Direct `LightpandaBrowserService` usage
  - `BrowserAutomation` integration with env var
  - Cookie persistence
  - Basic DOM operations

**Examples:**
- `examples/lightpanda_example.py` - Simple demo showing:
  - How to use with `BrowserAutomation`
  - Backend comparison
  - Basic page operations (navigate, evaluate, cookies)

## How It Works

### Backend Selection Flow

```
BrowserAutomation._get_service()
├─ Check CLI_TOOLS_BROWSER_BACKEND env var
├─ "lightpanda" → LightpandaBrowserService
├─ "playwright" → PlaywrightBrowserService
├─ "webwright" → WebwrightBrowserService
└─ default → BrowserHarnessService (Chrome)
```

### Lightpanda Lifecycle

1. **Launch**: `lightpanda serve --host 127.0.0.1 --port <port> --cookie <file>`
2. **Connect**: Playwright CDP client → Lightpanda WebSocket
3. **Operate**: Standard page operations (navigate, evaluate, selectors, etc.)
4. **Persist**: Save cookies to JSON on close via `Network.getAllCookies`
5. **Cleanup**: Terminate subprocess, close CDP connection

### Cookie Persistence Strategy

Lightpanda's `--cookie` flag is read-only at startup, so we:
- **On open**: Load `<profile_dir>/cookies.json` → `context.add_cookies()`
- **On close**: Fetch via CDP → save to `cookies.json`

This matches the Chrome profile behavior but uses explicit JSON instead of SQLite.

## Usage

### Quick Start

```bash
# Install Lightpanda
npm install -g @lightpanda/browser

# Install Playwright (required for CDP connection)
cd <cli-tool>
uv add playwright

# Use with any browser-backed CLI
CLI_TOOLS_BROWSER_BACKEND=lightpanda poshmark search "lego"
```

### Testing Locally

```bash
# Run smoke tests
cd _repo/cli-tools-shared
CLI_TOOLS_BROWSER_BACKEND=lightpanda uv run python tests/test_lightpanda_smoke.py

# Run example
CLI_TOOLS_BROWSER_BACKEND=lightpanda uv run python examples/lightpanda_example.py
```

### Integration Example

```python
from cli_tools_shared.auth import BrowserAutomation

# No code changes needed! Just set env var before running
# os.environ["CLI_TOOLS_BROWSER_BACKEND"] = "lightpanda"

browser = BrowserAutomation(config)
page = browser.get_page("https://example.com")
title = page.evaluate("() => document.title")
cookies = browser.live_cookies()
browser.close()
```

## Performance Characteristics

### Poshmark DOM Scrape Benchmark

| Metric | Chrome/browser-harness | Lightpanda | Diff |
|--------|------------------------|------------|------|
| Runtime | ~2.6–2.9s | ~3.6–3.9s | +1s (~38% slower) |
| Memory | ~1.8GB | ~350MB | -1.45GB (~81% reduction) |

**Conclusion**: Lightpanda trades ~1s runtime for ~1.5GB memory savings per worker.

For LegoScout parallel source workers (memory-constrained), this is a net win.

## Known Limitations

### Critical Issues

1. **No graphical rendering** - Sites requiring visual elements will fail
2. **Bot detection risk** - Cloudflare/Akamai may block Lightpanda
3. **No Chrome profile import** - Cannot reuse `user-data-dir` from Chrome
4. **Evaluate quirk** - String `"() => ..."` may return `{}`; use function form

### Workarounds

- **Bot detection**: Fall back to Chrome for protected sites (unset env var)
- **Profile import**: Export cookies from Chrome → JSON → Lightpanda loads
- **Evaluate**: Service handles automatically (wraps in function call)

## Success Criteria (from Spike Goals)

- ✅ Default behavior unchanged (Chrome/browser-harness)
- ✅ Env-flagged Lightpanda backend exists in `cli-tools-shared`
- ✅ Smoke test that opens page and runs evaluate successfully
- ✅ README/docs note: install, flag, limitations
- ✅ PR opened explaining LegoScout A/B migration path

## Next Steps (Post-Spike)

### Immediate (Before Merge)
- [ ] Review: Adam validates approach and design
- [ ] Confirm: Lightpanda install process (npm vs manual binary)
- [ ] Decide: Merge to main or keep as experimental branch?

### Short-Term (LegoScout Pilot)
- [ ] Benchmark against real LegoScout sources:
  - Poshmark (already measured)
  - Depop
  - AuctionZip
  - Mercari
  - Facebook Marketplace
- [ ] Document per-site compatibility matrix
- [ ] Add metrics collection (memory, runtime, errors)
- [ ] Parallel load test (10+ workers)

### Long-Term (Production)
- [ ] Add `BROWSER_BACKEND` config per CLI tool (not just env var)
- [ ] Add per-source backend config in LegoScout
- [ ] Implement Chrome → Lightpanda cookie migration tool
- [ ] Monitor failure rates in production
- [ ] Investigate Lightpanda stealth mode (if/when available)

## Migration Path for LegoScout

### Phase 1: Controlled Testing (Now)
```bash
# Test one source at a time
CLI_TOOLS_BROWSER_BACKEND=lightpanda poshmark search "lego"
# Compare: memory, runtime, success rate
```

### Phase 2: A/B Testing (After Validation)
```python
# In LegoScout source worker config
sources:
  - name: poshmark
    browser_backend: lightpanda  # ← New config field
  - name: depop
    browser_backend: chrome      # ← Fallback to Chrome if flaky
```

### Phase 3: Default for Validated Sources (Production)
- Lightpanda: Poshmark, Depop, AuctionZip (validated, no bot protection)
- Chrome: eBay, Facebook (Cloudflare, complex JS)
- Metric-driven: Switch back to Chrome if failure rate > 5%

## Files Changed

```
_repo/cli-tools-shared/
├── cli_tools_shared/
│   ├── auth.py                          (modified - backend selection)
│   └── browser/
│       ├── __init__.py                  (modified - exports)
│       └── lightpanda_service.py        (new - service implementation)
├── docs/
│   └── lightpanda-backend.md            (new - comprehensive guide)
├── examples/
│   └── lightpanda_example.py            (new - usage demo)
└── tests/
    └── test_lightpanda_smoke.py         (new - smoke tests)
```

## References

- **Lightpanda**: https://github.com/lightpanda-io/browser
- **Original spike context**: Poshmark scrape benchmark (Chrome vs Lightpanda)
- **Use case**: LegoScout parallel source workers (memory efficiency)
- **Integration point**: `cli_tools_shared.auth.BrowserAutomation`
