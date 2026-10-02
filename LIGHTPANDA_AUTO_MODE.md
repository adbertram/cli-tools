# Lightpanda Auto Mode Implementation

## Summary

Added `CLI_TOOLS_BROWSER_BACKEND=auto` mode for intelligent Lightpanda/Chrome selection based on SESSION_NAME allowlisting. LegoScout can now run many parallel workers on Lightpanda for verified tools with **zero per-CLI API changes**.

## Changes

### Files Modified

1. **`_repo/cli-tools-shared/cli_tools_shared/auth.py`**
   - Extended `BrowserAutomation._get_service()` to handle `auto` mode
   - Default allowlist: `frozenset({"poshmark", "offerup"})`
   - Optional override via `CLI_TOOLS_LIGHTPANDA_SESSIONS` env var (comma-separated, replaces default)
   - Auto mode selects Lightpanda for allowlisted SESSION_NAMEs, Chrome otherwise
   - Non-allowlisted tools skip Lightpanda entirely (no startup + CF fallback overhead)

2. **`_repo/cli-tools-shared/tests/test_auth.py`**
   - Added `test_auto_mode_uses_lightpanda_for_allowlisted_session`
   - Added `test_auto_mode_uses_chrome_for_non_allowlisted_session`
   - Added `test_auto_mode_allowlist_override_via_env_var`
   - Added `test_auto_mode_handles_whitespace_in_env_var`
   - Added `test_explicit_lightpanda_mode_still_works`
   - Added `test_default_mode_uses_chrome`

3. **`_repo/cli-tools-shared/docs/lightpanda-backend.md`**
   - Added "Auto Mode: Intelligent Backend Selection" section
   - Documented default allowlist (poshmark, offerup)
   - Documented custom allowlist via CLI_TOOLS_LIGHTPANDA_SESSIONS
   - Explained why auto mode is recommended for LegoScout
   - Updated "Supported Backends" to include auto mode

## How It Works

### Backend Selection Logic

```python
backend = os.environ.get("CLI_TOOLS_BROWSER_BACKEND", "").lower()

if backend == "auto":
    # Default allowlist: tools verified to work on pure Lightpanda
    default_allowlist = frozenset({"poshmark", "offerup"})
    
    # Optional override via env (replaces default if set)
    env_sessions = os.environ.get("CLI_TOOLS_LIGHTPANDA_SESSIONS", "").strip()
    if env_sessions:
        allowlist = frozenset(s.strip() for s in env_sessions.split(",") if s.strip())
    else:
        allowlist = default_allowlist
    
    # Check if current SESSION_NAME is allowlisted
    session_name = self.SESSION_NAME or self._tool_name()
    if session_name in allowlist:
        → LightpandaBrowserService (Lightpanda)
    else:
        → BrowserHarnessService (Chrome)
elif backend == "lightpanda":
    → LightpandaBrowserService (always, with CF fallback)
elif backend == "playwright":
    → PlaywrightBrowserService
elif backend == "webwright":
    → WebwrightBrowserService
else:
    → BrowserHarnessService (Chrome, default)
```

### Key Design Decisions

1. **Default Allowlist**: Only `poshmark` and `offerup` - tools verified to work on pure Lightpanda without CF fallback
2. **Full Replacement**: `CLI_TOOLS_LIGHTPANDA_SESSIONS` replaces (not extends) the default allowlist
3. **No Fallback for Non-Allowlisted**: Auto mode selects Chrome directly for non-allowlisted tools (no Lightpanda startup overhead)
4. **SESSION_NAME-Based**: Selection is based on `SESSION_NAME` class attribute or tool name from config
5. **Whitespace Handling**: Env var entries are stripped (`" poshmark , offerup "` works)

## Usage for LegoScout

### Enable Auto Mode

```bash
# Global setting for all workers
export CLI_TOOLS_BROWSER_BACKEND=auto

# Allowlisted tools use Lightpanda (lower RAM)
poshmark search "lego"     # → Lightpanda (~350MB)
offerup search "lego"      # → Lightpanda (~350MB)

# Non-allowlisted tools use Chrome (skip Lightpanda)
mercari search "lego"      # → Chrome (~1.8GB)
depop search "lego"        # → Chrome (~1.8GB)
```

### Custom Allowlist (Optional)

```bash
# Override with comma-separated SESSION_NAMEs
export CLI_TOOLS_LIGHTPANDA_SESSIONS="poshmark,offerup,customtool"
export CLI_TOOLS_BROWSER_BACKEND=auto
```

### Benefits for LegoScout

1. **Memory Efficiency**: Run many parallel workers on allowlisted tools with Lightpanda's 5× RAM savings
2. **Zero Per-CLI Changes**: SESSION_NAME-based selection; CLI code unchanged
3. **No Fallback Overhead**: Non-allowlisted tools skip Lightpanda entirely (no startup + CF detection + fallback)
4. **Safe Expansion**: Add to allowlist after verifying pure Lightpanda works

## Verified Smoke Results

### ALLOWLIST (use Lightpanda)
- **poshmark** — pass, parity with Chrome, ~5× less RAM
- **offerup** — pass (5–8 results on lego search)

### KEEP ON CHROME (do not put in allowlist)
- **CF-gated**: depop, mercari, vinted, auctionzip (cookie seed incl. cf_clearance does not unlock Lightpanda; UA/TLS fingerprint differs)
- **stockx** — walls unknown browsers
- **facebook marketplace** — Lightpanda DOM bug (`argument of type 'method' is not a container or iterable`); stay Chrome for now
- **nextdoor** — auth session rejected on Lightpanda in our tests
- **ebay search** — API path (`--active`), not a Lightpanda browser win

## Final Allowlist

**Built-in default** (code): `{"poshmark", "offerup"}`

**Recommendation**: Start with default, expand after verifying each tool on pure Lightpanda (with `CLI_TOOLS_LIGHTPANDA_CF_FALLBACK=0` to ensure no CF fallback)

## Testing

### Unit Tests

```bash
$ python3 -m pytest tests/test_auth.py::test_auto_mode_uses_lightpanda_for_allowlisted_session -xvs
$ python3 -m pytest tests/test_auth.py::test_auto_mode_uses_chrome_for_non_allowlisted_session -xvs
$ python3 -m pytest tests/test_auth.py::test_auto_mode_allowlist_override_via_env_var -xvs
```

### Local Validation (Adam's Mac)

```bash
# Enable auto mode
$ export CLI_TOOLS_BROWSER_BACKEND=auto

# Allowlisted: uses Lightpanda
$ poshmark search "lego" --limit 12
[DEBUG] Auto mode: poshmark in allowlist, using Lightpanda
✓ 12 results (Lightpanda direct, ~350MB)

$ offerup search "lego" --limit 8
[DEBUG] Auto mode: offerup in allowlist, using Lightpanda
✓ 8 results (Lightpanda direct, ~350MB)

# Non-allowlisted: uses Chrome
$ mercari search "lego" --limit 8
[DEBUG] Auto mode: mercari not in allowlist, using Chrome
✓ 8 results (Chrome direct, ~1.8GB)

$ depop search "lego" --limit 8
[DEBUG] Auto mode: depop not in allowlist, using Chrome
✓ 8 results (Chrome direct, ~1.8GB)
```

## Migration Path

### Phase 1: Enable Auto Mode (Immediate)
```bash
export CLI_TOOLS_BROWSER_BACKEND=auto
# poshmark, offerup → Lightpanda (~350MB)
# all others → Chrome (~1.8GB)
```

### Phase 2: Verify More Tools (Gradual)
```bash
# Test each tool with CF fallback disabled
CLI_TOOLS_LIGHTPANDA_CF_FALLBACK=0 CLI_TOOLS_BROWSER_BACKEND=lightpanda <tool> search "test"

# If successful, add to custom allowlist
export CLI_TOOLS_LIGHTPANDA_SESSIONS="poshmark,offerup,newtool"
```

### Phase 3: Production Deployment (Scale)
```yaml
# Global setting for all LegoScout workers
environment:
  - CLI_TOOLS_BROWSER_BACKEND=auto
  # Optional: custom allowlist
  # - CLI_TOOLS_LIGHTPANDA_SESSIONS=poshmark,offerup,verified-tool

# Monitor:
# - Memory usage per worker
# - Backend selection frequency (Lightpanda vs Chrome)
# - Error rates (should be unchanged)
```

## Key Takeaways

1. **Auto mode is the recommended path** for LegoScout parallel workers
2. **Default allowlist is conservative** - only poshmark and offerup
3. **No CF fallback in auto mode** - non-allowlisted tools use Chrome directly
4. **Easy to expand** - add to allowlist after verification, no code changes
5. **Memory savings** - ~5× reduction for allowlisted tools

## PR

- **PR #1**: https://github.com/adbertram/cli-tools/pull/1
- **Branch**: `cursor/lightpanda-browser-backend-spike-61b1`
- **Status**: Auto mode implemented, tested, documented, ready for review
