# Fix CLI Compliance Issues - Kick CLI

## One-line Summary
Fix 9 CLI compliance failures and 1 warning by adding missing command options and documentation.

## Why This Approach
This is the simplest solution: direct edits to 4 existing files with no new files or abstractions needed.

## Discovery Summary

### Files Read
- `README.md` - Current documentation, missing 3 command sections
- `kick_cli/commands/auth.py` - Has --no-browser parameter (lines 129-132)
- `kick_cli/commands/rule_groups.py` - Missing --limit and --properties on list (lines 16-22)
- `kick_cli/commands/clients.py` - Missing --properties, wrong default limit (lines 12-18)
- `kick_cli/commands/integrations.py` - Missing --limit and --filter on list (lines 22-26)
- `kick_cli/commands/transactions.py` - Has undocumented search command (lines 114-214)
- `kick_cli/commands/categories.py` - Reference for --limit/--properties patterns
- `kick_cli/filters.py` - Reference for apply_filters usage

### Integration Points
- `apply_filters()` from filters.py used for client-side filtering
- All list commands follow same pattern: table option, limit, filter, properties

## Issues Summary

| Issue | Type | File | Description |
|-------|------|------|-------------|
| 1 | Doc | README.md | transactions search not documented |
| 2 | Doc | README.md | rule-groups command missing |
| 3 | Doc | README.md | integrations command missing |
| 4 | Option | rule_groups.py | list missing --limit/-l |
| 5 | Option | rule_groups.py | list missing --properties/-p |
| 6 | Option | clients.py | list missing --properties/-p |
| 7 | Option | integrations.py | list missing --limit/-l |
| 8 | Option | integrations.py | list missing --filter/-f |
| 9 | Auth | auth.py | --no-browser forbidden (investigate) |
| 10 | Warning | clients.py | --limit default is 50, should be 100 |

## Implementation Plan

### Step 1: Fix clients.py

**File:** `kick_cli/commands/clients.py`

1. Line 15: Change limit default from 50 to 100
   ```python
   limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of clients to return"),
   ```

2. Add after line 17 (after filter option):
   ```python
   properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of properties to display"),
   ```

### Step 2: Fix rule_groups.py

**File:** `kick_cli/commands/rule_groups.py`

1. Add after line 21 (after include_rules option):
   ```python
   limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of rule groups to return"),
   properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of properties to display"),
   ```

2. Around line 45, after apply_filters call, add:
   ```python
   rule_groups = rule_groups[:limit]
   ```

### Step 3: Fix integrations.py

**File:** `kick_cli/commands/integrations.py`

1. Line 3: Add List to import
   ```python
   from typing import Optional, List
   ```

2. Line 6: Add apply_filters import
   ```python
   from ..filters import apply_filters
   ```

3. Add after line 25 (after provider option):
   ```python
   limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of integrations to return"),
   filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
   ```

4. Around line 44, after provider filtering, add:
   ```python
   # Apply client-side filtering
   if filter:
       integrations = apply_filters(integrations, filter)

   # Apply limit
   integrations = integrations[:limit]
   ```

### Step 4: Update README.md

**File:** `README.md`

1. **After line 89** (after transactions update section): Add transactions search docs
2. **After line 165** (after Statistics section): Add rule-groups section
3. **After rule-groups**: Add integrations section

### Step 5: Handle auth login --no-browser

The `--no-browser` parameter is a legitimate feature for OAuth CLIs:
- Documented in README (line 39)
- Supports headless/SSH environments
- Standard practice for OAuth flows

**Recommendation:** Keep as-is unless CLI standards explicitly forbid it. This may be a false positive in the test.

---

## Test Checkpoints

### After Step 3 (Code Changes)
```bash
# Verify commands have new options
kick clients list --help | grep -E "\-\-limit|\-\-properties"
kick rule-groups list --help | grep -E "\-\-limit|\-\-properties"
kick integrations list --help | grep -E "\-\-limit|\-\-filter"

# Test functionality
kick clients list --limit 5
kick rule-groups list --limit 5
kick integrations list --limit 5
```

### After Step 4 (Documentation)
```bash
# Verify documentation exists
grep -c "transactions search" README.md  # Should be > 0
grep -c "rule-groups" README.md          # Should be > 0
grep -c "integrations" README.md         # Should be > 0
```

### Final Verification
```bash
# Re-run compliance test
<cli-tools-root>/_repo/skills/cli-tool/scripts/test-cli-tool.sh kick
```

---

## Complexity Avoided

- No new files created
- No abstractions or helpers
- No changes to API client
- Minimal code changes per file
- Following existing patterns exactly

## Files Modified

1. `kick_cli/commands/clients.py` - 2 line changes
2. `kick_cli/commands/rule_groups.py` - 3 line changes
3. `kick_cli/commands/integrations.py` - 5 line changes
4. `README.md` - Add 3 documentation sections
