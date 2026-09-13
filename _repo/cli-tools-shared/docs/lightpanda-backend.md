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
- ✓ **Automatic CF fallback**: Detects Cloudflare blocks and switches to Chrome

### Limitations
- ✗ **No lifecycle events**: Lightpanda doesn't emit `domcontentloaded`/`load` events; uses raw CDP navigation
- ✗ **No graphical rendering**: Cannot handle sites requiring visual elements
- ✗ **Cannot impersonate Chrome**: Lightpanda intentionally forbids Mozilla user-agent strings
- ✗ **Cloudflare Bot Management**: Cannot beat CF by UA spoofing; automatic Chrome fallback is the solution
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

Set `CLI_TOOLS_BROWSER_BACKEND` to control backend selection:

#### Manual Mode: Always Lightpanda

```bash
# Single command
CLI_TOOLS_BROWSER_BACKEND=lightpanda poshmark search "lego"

# Export for session
export CLI_TOOLS_BROWSER_BACKEND=lightpanda
poshmark search "lego"
depop search "vintage"
```

#### Auto Mode: Intelligent Backend Selection (Recommended for LegoScout)

`auto` mode selects Lightpanda **only** for SESSION_NAMEs verified to work on pure Lightpanda. Non-allowlisted tools get Chrome directly (no Lightpanda startup overhead):

```bash
# Enable auto mode
export CLI_TOOLS_BROWSER_BACKEND=auto

# Allowlisted tools use Lightpanda (lower RAM)
poshmark search "lego"     # → Lightpanda (~350MB)
offerup search "lego"      # → Lightpanda (~350MB)

# Non-allowlisted tools use Chrome (skip Lightpanda entirely)
mercari search "lego"      # → Chrome (~1.8GB, no Lightpanda fallback)
depop search "lego"        # → Chrome (~1.8GB, CF-protected)
```

**Default allowlist** (built-in): `poshmark`, `offerup`

**Custom allowlist** (replaces default):
```bash
# Override with comma-separated SESSION_NAMEs
export CLI_TOOLS_LIGHTPANDA_SESSIONS="poshmark,offerup,customtool"
export CLI_TOOLS_BROWSER_BACKEND=auto
poshmark search "lego"     # → Lightpanda
mercari search "lego"      # → Chrome (not in custom list)
```

**Why auto mode?**
- **Memory efficiency**: Run many parallel workers on allowlisted tools with Lightpanda's 5× RAM savings
- **Zero per-CLI changes**: SESSION_NAME-based selection; CLI code unchanged
- **No fallback overhead**: Non-allowlisted tools skip Lightpanda entirely
- **Safe expansion**: Add to allowlist after verifying pure Lightpanda works

### Optional Configuration

#### Custom User Agent (Non-Mozilla Only)

Lightpanda **intentionally forbids** Mozilla-based user-agent strings. You can set a custom bot identity:

```bash
# Custom identity (e.g. bot name)
export CLI_TOOLS_LIGHTPANDA_USER_AGENT="MyBot/1.0"

# Or append to default Lightpanda/1.0
export CLI_TOOLS_LIGHTPANDA_UA_SUFFIX="MyCompany/2.0"

# ❌ This will FAIL (contains Mozilla):
# export CLI_TOOLS_LIGHTPANDA_USER_AGENT="Mozilla/5.0 Chrome/120.0"
```

#### Cloudflare Fallback Control

Chrome fallback is **enabled by default**. Disable to see raw CF errors:

```bash
# Disable automatic Chrome fallback (for debugging)
export CLI_TOOLS_LIGHTPANDA_CF_FALLBACK=0
poshmark search "lego"  # Will fail if CF-protected
```

#### Web Bot Auth (Verified Bots)

For sites that verify Cloudflare Verified Bots:

```bash
export CLI_TOOLS_LIGHTPANDA_WEB_BOT_AUTH_KEY_FILE=/path/to/private-key.pem
export CLI_TOOLS_LIGHTPANDA_WEB_BOT_AUTH_KEYID=your-key-id
export CLI_TOOLS_LIGHTPANDA_WEB_BOT_AUTH_DOMAIN=your-bot-domain.com
```

**Note**: Most sites don't verify Web Bot Auth. **Automatic Chrome fallback is the recommended approach.**

### Supported Backends

- **`auto`** → Lightpanda for allowlisted SESSION_NAMEs, Chrome otherwise (recommended for LegoScout)
- **`lightpanda`** → `LightpandaBrowserService` (always, with CF fallback)
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

### Issue: Cloudflare Bot Management (HARD LIMIT)

**Symptom**: Sites protected by Cloudflare serve 403 Forbidden or "Just a moment" challenge page.

**Root Cause**: Lightpanda **intentionally forbids Chrome impersonation**:
- `--user-agent` rejects any string containing `Mozilla`
- CDP `Network.setUserAgentOverride` does not stick (navigator stays `Lightpanda/1.0`)
- Cookie seeding with `cf_clearance` alone is insufficient (bound to IP+UA+TLS fingerprint)

**Official Guidance from Lightpanda**:
- Use **Web Bot Auth** for CF Verified Bots program (see below)
- Use a **classic browser** (Chrome) for fingerprint-sensitive sites
- Do NOT attempt UA spoofing - it will not work

**Automatic Solution**: Cloudflare fallback is **enabled by default**:

```python
# BrowserAutomation automatically detects CF blocks and falls back to Chrome
page = browser.get_page("https://cf-protected-site.com")
# → Opens with Lightpanda
# → Detects "Just a moment" / 403
# → Closes Lightpanda, reopens with Chrome
# → Returns Chrome page (transparent to caller)
```

**Disable fallback** (to see raw CF error):
```bash
CLI_TOOLS_LIGHTPANDA_CF_FALLBACK=0 poshmark search "lego"
```

**Local Proof** (from Adam's Mac):
- **With fallback=1** (default): Depop/AuctionZip/Mercari all returned 8 results
- **With fallback=0**: Depop still HTTP 403 on Lightpanda

### Issue: Web Bot Auth (Optional for Verified Bots)

**What it is**: Cloudflare's Verified Bots program allows legitimate bots to identify themselves cryptographically.

**Setup**:
1. Register with Cloudflare Verified Bots program
2. Get private key, key ID, and authorized domain
3. Set env vars:
   ```bash
   export CLI_TOOLS_LIGHTPANDA_WEB_BOT_AUTH_KEY_FILE=/path/to/private-key.pem
   export CLI_TOOLS_LIGHTPANDA_WEB_BOT_AUTH_KEYID=your-key-id
   export CLI_TOOLS_LIGHTPANDA_WEB_BOT_AUTH_DOMAIN=your-bot-domain.com
   ```

**Note**: This only works for sites that verify Web Bot Auth. Most sites just use CF Bot Management without verification. **Automatic Chrome fallback is the recommended path.**

### Issue: No lifecycle events (domcontentloaded, load)

**Symptom**: Lightpanda doesn't emit the lifecycle events that Playwright/Puppeteer wait on.

**Solution**: We use raw CDP `Page.navigate` + `readyState` polling instead of high-level `page.goto()`.

```python
# Internally handled - no CLI changes needed
# Service uses: Page.navigate → sleep(0.5) → verify document.readyState
```

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
- Sites with **automatic CF fallback enabled** (default)
- LegoScout deal-run source workers (controlled environment)

✗ **Bad fit**:
- Sites requiring visual rendering or canvas
- Complex SPAs requiring full JS runtime
- Untested/exploratory scraping

⚠️ **Cloudflare-protected sites**: 
- **Works with default settings** - automatic Chrome fallback
- Verified: Depop, AuctionZip, Mercari all work (return results after CF fallback)
- Transparent to caller - `get_page()` returns Chrome page when CF detected
- Disable with `CLI_TOOLS_LIGHTPANDA_CF_FALLBACK=0` to see raw CF errors

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
