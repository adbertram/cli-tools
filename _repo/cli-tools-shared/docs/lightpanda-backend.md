# Lightpanda Browser Backend (Experimental)

## Overview

The Lightpanda browser backend provides an **optional, lightweight alternative** to Chrome/browser-harness for CLI tools that use `BrowserAutomation`. It's designed for efficiency in parallel automation scenarios where memory usage is a primary concern.

**Status**: Experimental spike for LegoScout source worker evaluation.

## Key Characteristics

### Performance Profile (Poshmark DOM scrape benchmark)
- **Chrome/browser-harness**: ~2.6–2.9s / ~1.8GB RAM
- **Lightpanda**: ~3.6–3.9s / ~350MB RAM

### Advantages
- ✓ **Low memory footprint**: ~350MB vs ~1.8GB for Chrome
- ✓ **CDP-compatible**: Works with raw CDP commands via cdp-use
- ✓ **Drop-in backend**: No CLI code changes required
- ✓ **Cookie persistence**: Saves/loads cookies from JSON file

### Limitations
- ✗ **No lifecycle events**: Lightpanda doesn't emit `domcontentloaded`/`load` events; uses raw CDP navigation
- ✗ **No graphical rendering**: Cannot handle sites requiring visual elements
- ✗ **Bot detection risk**: May trigger Cloudflare/Akamai/Imperva on protected sites
- ✗ **No Chromium profile support**: Cannot reuse `user-data-dir` from Chrome
- ⚠️ **Read-only cookies at start**: `--cookie` loads cookies at `serve` startup; mutations saved on close

## Installation

### 1. Install Lightpanda Binary

```bash
# Global install via npm
npm install -g @lightpanda/browser

# Or use npx (no install)
npx @lightpanda/browser serve --help
```

### 2. Verify Installation

```bash
# Check if binary is in PATH
which lightpanda

# Check common npm cache location
ls ~/.cache/lightpanda-node/lightpanda

# Or set custom path
export CLI_TOOLS_LIGHTPANDA_BINARY=/path/to/lightpanda
```

### 3. Dependencies

The Lightpanda backend uses `cdp-use` for raw CDP commands, which is already a dependency of `cli-tools-shared`. No additional installation needed.

## Usage

### Environment Variable Control

Set `CLI_TOOLS_BROWSER_BACKEND=lightpanda` before running any CLI command:

```bash
# Single command
CLI_TOOLS_BROWSER_BACKEND=lightpanda poshmark search "lego"

# Export for session
export CLI_TOOLS_BROWSER_BACKEND=lightpanda
poshmark search "lego"
depop search "vintage"
```

### Supported Backends

- **`lightpanda`** → `LightpandaBrowserService` (this backend)
- **`playwright`** → `PlaywrightBrowserService` (Playwright persistent context)
- **`webwright`** → `WebwrightBrowserService` (Webwright local browser)
- **(default/empty)** → `BrowserHarnessService` (Chrome via browser-harness)

## Architecture

### Service Layer

```
cli_tools_shared/
├── auth.py
│   └── BrowserAutomation._get_service()  ← Backend selection via env var
└── browser/
    ├── driver.py                          ← BrowserHarnessService (default)
    ├── playwright_service.py              ← PlaywrightBrowserService
    ├── webwright.py                       ← WebwrightBrowserService
    └── lightpanda_service.py              ← LightpandaBrowserService (new)
```

### How It Works

1. **Launch**: Spawns `lightpanda serve --host 127.0.0.1 --port <port> --cookie <file>`
2. **Wait**: Polls `/json/version` until CDP endpoint is ready (avoids hang)
3. **Connect**: Uses `cdp-use` to connect via WebSocket and create a target/page
4. **Navigate**: Raw CDP `Page.navigate` (no lifecycle wait; Lightpanda doesn't emit events)
5. **Operate**: Standard operations via CDP (`Runtime.evaluate`, `Network.getAllCookies`, etc.)
6. **Persist**: Saves cookies to `<profile_dir>/cookies.json` on close
7. **Cleanup**: Terminates subprocess, closes CDP connection

### Cookie Persistence

Lightpanda's `--cookie` flag is **read-only at startup**. To persist cookie changes:

- **On close**: `LightpandaBrowserService.browser_close()` saves via `Network.getAllCookies` → JSON
- **On open**: Service loads JSON file and injects via `context.add_cookies()`

## Testing

### Run Smoke Tests

```bash
# Direct service test
cd _repo/cli-tools-shared
uv run python tests/test_lightpanda_smoke.py

# With Lightpanda backend
CLI_TOOLS_BROWSER_BACKEND=lightpanda uv run python tests/test_lightpanda_smoke.py
```

### Manual CLI Test

```bash
# Authenticate (if needed)
CLI_TOOLS_BROWSER_BACKEND=lightpanda poshmark auth login

# Run a command
CLI_TOOLS_BROWSER_BACKEND=lightpanda poshmark search "lego star wars" --limit 5

# Compare memory usage
ps aux | grep -E "(chrome|lightpanda)" | grep -v grep
```

## Known Issues & Workarounds

### Issue: No lifecycle events (domcontentloaded, load)

**Symptom**: Lightpanda doesn't emit the lifecycle events that Playwright/Puppeteer wait on.

**Solution**: We use raw CDP `Page.navigate` + short fixed wait instead of high-level `page.goto()`.

```python
# Internally handled - no CLI changes needed
# Service uses: Page.navigate → sleep(0.5) → verify document.readyState
```

### Issue: Cloudflare/bot detection blocks

**Symptom**: Sites serve challenge pages instead of content.

**Mitigation**: 
- Lightpanda has no stealth mode or user-agent masking (yet)
- For protected sites, fall back to Chrome: unset `CLI_TOOLS_BROWSER_BACKEND`
- **Not a blocker for spike**: Document failures, evaluate later

### Issue: Cannot import Chrome profile

**Symptom**: Existing `user-data-dir` from Chrome won't load.

**Expected**: Lightpanda stores cookies separately. Export cookies from Chrome:

```python
# Export from Chrome session
chrome_cookies = chrome_page.cookie_list()
Path("cookies.json").write_text(json.dumps(chrome_cookies))

# Lightpanda will load on next open
```

## Production Considerations

### When to Use Lightpanda

✓ **Good fit**:
- Parallel scraping (many workers, memory constrained)
- Simple DOM extraction (no JS-heavy SPAs)
- Known-good sites (tested, no bot protection)
- LegoScout deal-run source workers (controlled environment)

✗ **Bad fit**:
- Sites with aggressive bot detection (Cloudflare JS challenge)
- Complex SPAs requiring full JS runtime
- Sites needing visual rendering or canvas
- Untested/exploratory scraping

### Rollout Strategy

1. **Spike phase** (current):
   - Test against Poshmark, Depop, AuctionZip, Mercari
   - Document success/failure per site
   - Measure memory under parallel load

2. **Controlled pilot**:
   - LegoScout: A/B test Chrome vs Lightpanda for one source
   - Monitor failure rates, memory, runtime
   - Collect data for ROI analysis

3. **Gradual expansion**:
   - Add `BROWSER_BACKEND` config per source
   - Default to Chrome, opt-in Lightpanda for validated sources
   - Keep Chrome fallback path

## API Compatibility

`LightpandaBrowserService` implements the same interface as `BrowserHarnessService`:

```python
# All standard methods work
page = service.browser_open(url, persistent_profile_dir=dir)
page.goto(url)
page.evaluate(js)
page.wait_for_selector(selector, state="visible")
page.cookie_list()
page.localstorage_list()
service.browser_close()
```

Unsupported (will raise `LightpandaServiceError`):
- `headed=True` (no graphical mode; silently ignored)
- Full accessibility tree (simplified fallback)

## Future Work

- [ ] Benchmark Lightpanda against Poshmark, Depop, AuctionZip, Mercari
- [ ] Document per-site compatibility matrix
- [ ] Add metrics collection (memory, runtime, errors)
- [ ] Stealth mode investigation (if Lightpanda adds support)
- [ ] Parallel load testing (10+ workers)
- [ ] Cookie migration tool (Chrome → Lightpanda)

## References

- **Lightpanda**: https://github.com/lightpanda-io/browser
- **Spike context**: LegoScout deal-run efficiency (parallel source workers)
- **Benchmark**: Poshmark DOM scrape, Chrome vs Lightpanda
- **Integration**: `cli_tools_shared.auth.BrowserAutomation._get_service()`
