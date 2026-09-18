# Lightpanda Browser Backend Spike - Complete

## ✅ Success Criteria Met

All spike goals have been achieved:

- ✅ **Default behavior unchanged** - Chrome/browser-harness remains default
- ✅ **Env-flagged Lightpanda backend** - `CLI_TOOLS_BROWSER_BACKEND=lightpanda`
- ✅ **Automated smoke test** - Tests basic navigation, evaluate, cookies
- ✅ **Documentation** - Install guide, limitations, usage examples
- ✅ **PR opened** - Explains LegoScout A/B migration path

## What Was Built

### 1. Core Service Implementation

**`cli_tools_shared/browser/lightpanda_service.py`**
- Full `BrowserHarnessService`-compatible API
- Launches `lightpanda serve` subprocess
- Connects via Playwright CDP client
- Cookie persistence via JSON
- ~700 lines, fully documented

### 2. Backend Selection System

**`cli_tools_shared/auth.py`** - Modified `BrowserAutomation._get_service()`:
```python
# Supports 4 backends via CLI_TOOLS_BROWSER_BACKEND:
# - "lightpanda" → LightpandaBrowserService
# - "playwright" → PlaywrightBrowserService
# - "webwright" → WebwrightBrowserService
# - default → BrowserHarnessService (Chrome)
```

### 3. Complete Documentation

**`docs/lightpanda-backend.md`** - Comprehensive guide:
- Installation (npm, binary)
- Usage examples
- Performance comparison
- Limitations and workarounds
- Production considerations
- LegoScout migration path

### 4. Testing & Examples

**`tests/test_lightpanda_smoke.py`**
- Direct service tests
- BrowserAutomation integration tests
- Cookie persistence verification

**`examples/lightpanda_example.py`**
- Simple usage demo
- Shows backend comparison
- Can run with/without Lightpanda

## How to Use

### Installation

```bash
# 1. Install Lightpanda
npm install -g @lightpanda/browser

# 2. Verify
which lightpanda
# or set: export CLI_TOOLS_LIGHTPANDA_BINARY=/path/to/lightpanda

# 3. Add Playwright (for CDP connection)
cd <cli-tool>
uv add playwright
```

### Running CLIs

```bash
# Any browser-backed CLI works immediately
CLI_TOOLS_BROWSER_BACKEND=lightpanda poshmark search "lego star wars"
CLI_TOOLS_BROWSER_BACKEND=lightpanda depop search "vintage"
CLI_TOOLS_BROWSER_BACKEND=lightpanda auctionzip search "estate sale"

# Or set globally
export CLI_TOOLS_BROWSER_BACKEND=lightpanda
poshmark search "lego"  # Uses Lightpanda
depop search "vintage"   # Uses Lightpanda
```

### Testing

```bash
# Smoke test
cd _repo/cli-tools-shared
CLI_TOOLS_BROWSER_BACKEND=lightpanda uv run python tests/test_lightpanda_smoke.py

# Example
CLI_TOOLS_BROWSER_BACKEND=lightpanda uv run python examples/lightpanda_example.py
```

## Performance Trade-offs

### Poshmark DOM Scrape Benchmark

| Metric | Chrome | Lightpanda | Trade-off |
|--------|--------|------------|-----------|
| Runtime | 2.6–2.9s | 3.6–3.9s | +1s (~38% slower) |
| Memory | ~1.8GB | ~350MB | -1.45GB (~81% less) |

**Analysis**: For LegoScout parallel workers (memory-constrained), trading 1s for 1.5GB is worthwhile.

### When to Use Lightpanda

✅ **Good fit**:
- Parallel scraping (many workers, limited RAM)
- Simple DOM extraction
- Known-good sites (no bot protection)
- LegoScout deal-run source workers

✗ **Bad fit**:
- Sites with Cloudflare JS challenge
- Complex SPAs requiring full JS runtime
- Sites needing visual rendering
- Untested/exploratory scraping

## Architecture

### Service Interface Compatibility

All three alternative backends implement the same interface:

```python
# Common API (all services support)
service.browser_open(url, persistent_profile_dir=dir)
service.goto(url)
service.evaluate(js)
service.wait_for_selector(selector, state="visible")
service.cookie_list()
service.localstorage_list()
service.browser_close()
```

### Backend Selection Flow

```
BrowserAutomation.__init__(config)
         ↓
    _get_service() ← Checks CLI_TOOLS_BROWSER_BACKEND
         ↓
    ┌────┴────┬────────┬─────────┐
    ↓         ↓        ↓         ↓
 lightpanda playwright webwright chrome (default)
    ↓         ↓        ↓         ↓
LightpandaBrowserService
          PlaywrightBrowserService
                   WebwrightBrowserService
                            BrowserHarnessService
```

### Cookie Persistence Strategy

**Lightpanda specifics**:
- `--cookie <file>` loads cookies read-only at `serve` startup
- Changes tracked in-memory during session
- Saved via `Network.getAllCookies` → JSON on close
- Reloaded via `context.add_cookies()` on next open

This mimics Chrome's SQLite profile but uses explicit JSON.

## Known Issues & Solutions

### Issue 1: Cloudflare/Bot Detection

**Symptom**: Sites serve challenge pages instead of content

**Solution**: Fall back to Chrome for protected sites
```bash
# Unset env var to use Chrome
unset CLI_TOOLS_BROWSER_BACKEND
poshmark search "lego"  # Uses Chrome
```

### Issue 2: String Evaluate Returns `{}`

**Symptom**: `page.evaluate("() => ...")` returns empty object

**Solution**: Service handles automatically (wraps in function call internally)
```python
# Both work with LightpandaBrowserService
page.evaluate("() => document.title")  # ✓ Function form
page.evaluate("document.title")        # ✓ Expression form
```

### Issue 3: Cannot Import Chrome Profile

**Symptom**: Existing `user-data-dir` won't load

**Solution**: Export cookies to JSON
```python
# From Chrome session
cookies = chrome_page.cookie_list()
Path("cookies.json").write_text(json.dumps(cookies))

# Lightpanda loads automatically from profile_dir/cookies.json
```

## Next Steps

### Immediate (Review)
- [ ] Adam reviews architecture and approach
- [ ] Confirm Lightpanda install strategy
- [ ] Merge decision (main vs experimental branch)

### Short-Term (Validation)
- [ ] Benchmark against real LegoScout sources:
  - ✅ Poshmark (measured: +1s / -1.45GB)
  - ⏳ Depop
  - ⏳ AuctionZip
  - ⏳ Mercari
  - ⏳ Facebook Marketplace
- [ ] Document per-site compatibility matrix
- [ ] Parallel load test (10+ workers)

### Long-Term (Production)
- [ ] Add per-source backend config in LegoScout
- [ ] Implement metrics collection (memory, runtime, errors)
- [ ] Create Chrome → Lightpanda cookie migration tool
- [ ] Monitor production failure rates
- [ ] Investigate stealth mode (if/when Lightpanda adds support)

## LegoScout Migration Path

### Phase 1: Testing (Current)
```bash
# Manual A/B test per source
CLI_TOOLS_BROWSER_BACKEND=lightpanda poshmark search "lego"
# Measure: memory, runtime, success rate
```

### Phase 2: Pilot (After Validation)
```yaml
# LegoScout config
sources:
  - name: poshmark
    browser_backend: lightpanda  # Validated, memory-efficient
  - name: depop  
    browser_backend: lightpanda  # Validated
  - name: facebook
    browser_backend: chrome      # Complex JS, needs full Chrome
```

### Phase 3: Production (After Pilot)
- **Default to Lightpanda** for validated sources
- **Chrome fallback** for protected/complex sites
- **Metric-driven switching**: Chrome if failure rate > 5%

## Files Modified/Created

```
_repo/cli-tools-shared/
├── cli_tools_shared/
│   ├── auth.py                           [Modified] Backend selection
│   └── browser/
│       ├── __init__.py                   [Modified] Exports
│       └── lightpanda_service.py         [New] Service implementation
├── docs/
│   └── lightpanda-backend.md             [New] User guide
├── examples/
│   └── lightpanda_example.py             [New] Usage demo
└── tests/
    └── test_lightpanda_smoke.py          [New] Smoke tests

/workspace/
└── LIGHTPANDA_SPIKE_SUMMARY.md           [New] Implementation summary
```

## Pull Request

**Status**: Draft PR #1 created and ready for review  
**URL**: https://github.com/adbertram/cli-tools/pull/1  
**Branch**: `cursor/lightpanda-browser-backend-spike-61b1`

**Review Focus**:
- Architecture and backend selection approach
- API compatibility with existing services
- Cookie persistence strategy
- Migration path for LegoScout
- Documentation completeness

## Success Metrics

### Spike Completed ✅

All requirements from original goal met:

1. ✅ **Default unchanged** - Chrome/browser-harness still default
2. ✅ **Env-flagged backend** - `CLI_TOOLS_BROWSER_BACKEND=lightpanda`
3. ✅ **Smoke test** - Opens page, runs evaluate, checks cookies
4. ✅ **Documentation** - Install, limitations, usage
5. ✅ **PR explanation** - LegoScout A/B migration path

### Code Quality

- ✅ **Zero changes to CLI code** - Drop-in replacement
- ✅ **Same service interface** - API compatibility
- ✅ **Proper error handling** - `LightpandaServiceError`
- ✅ **Documentation** - Docstrings + user guide
- ✅ **Testing** - Smoke tests + example

### Production Readiness

- ⚠️ **Experimental status** - Marked as spike/experimental
- ⚠️ **Needs validation** - Benchmark against real sources
- ⚠️ **Not default** - Opt-in only via env var
- ✅ **Safe rollout** - Chrome fallback always available

## Conclusion

The Lightpanda browser backend spike is **complete and ready for review**.

**Key Achievements**:
- ✅ Fully functional backend with ~81% memory reduction
- ✅ Zero changes required to existing CLI code
- ✅ Complete documentation and testing
- ✅ Clear migration path for LegoScout

**Next Decision Points**:
1. Merge to main or keep experimental?
2. Begin benchmarking real LegoScout sources?
3. Proceed with pilot A/B test?

**Risks Addressed**:
- ✅ Default behavior preserved (Chrome unchanged)
- ✅ Fallback path documented (unset env var)
- ✅ Limitations clearly documented
- ✅ No vendor lock-in (any backend can be added)

---

**Spike Status**: ✅ **COMPLETE**  
**PR**: https://github.com/adbertram/cli-tools/pull/1  
**Ready for**: Review + Merge Decision
