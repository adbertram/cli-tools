# Implementation Plan: Podio CLI Compliance Fixes

## One-line Summary
Fix Podio CLI compliance issues including handle_error function, auth parameters, verb-noun commands, missing standard options, and README documentation.

## Why This Approach
This is the simplest approach that addresses all compliance failures while maintaining backward compatibility through hidden deprecated aliases. Each phase is independent and can be tested in isolation.

## Discovery Summary

### Files Read and Analyzed:
- `output.py` (lines 1-342): Has alias `handle_error = handle_api_error` - needs proper function definition
- `auth.py` (lines 1-398): Has forbidden parameters on login (`--flow`, `--redirect-uri`) and logout (`--yes`)
- `task.py` (lines 1-334): Verb-noun commands need refactoring to noun-verb
- `item.py` (lines 1-326): Has forbidden `filter` command, needs `list` with `--filter`
- `webhook.py` (lines 1-449): Verb-noun field commands need refactoring
- `conversation.py` (lines 1-481): Verb-noun commands, wrong limit default
- `space.py` (lines 1-104): `find-by-url` should be `--url` on `get`
- `org.py` (lines 1-31): Missing standard list options
- `comment.py` (lines 1-229): Missing `--filter`, `--properties` on list
- `webform.py` (lines 1-232): Missing `--limit`, `--properties` on list
- `README.md` (lines 1-1013): Missing documentation for several commands

### Tools/APIs Tested:
- `podio --help` - CLI loads correctly
- `podio auth login --help` - Current params: `--flow/-f`, `--redirect-uri/-r` (forbidden)
- `podio auth logout --help` - Current params: `--yes/-y` (should be `--force/-F`)
- Podio API: `client.Item.filter()` uses API-level filtering (confirmed at item.py:89)

---

## Phase 1: Core Infrastructure

### Step 1: Fix handle_error in output.py
**File**: `<cli-tools-root>/podio/podio_cli/output.py`
**Action**: Replace line 341 alias with proper function definition

```python
def handle_error(error: Exception) -> int:
    """
    Handle errors and return appropriate exit code.

    Alias for handle_api_error for CLI standards compliance.

    Args:
        error: Exception from API call

    Returns:
        int: Exit code (1 for general errors, 2 for auth errors)
    """
    return handle_api_error(error)
```

**Verify**: `grep "def handle_error" podio_cli/output.py`

---

## Phase 2: Auth Command Fixes

### Step 2: Fix auth login parameters
**File**: `<cli-tools-root>/podio/podio_cli/commands/auth.py`
**Lines**: 115-199
**Action**:
- Rename `--flow/-f` to `--type/-t`
- Remove `--redirect-uri/-r` (use env var instead)

### Step 3: Fix auth logout parameters
**File**: `<cli-tools-root>/podio/podio_cli/commands/auth.py`
**Lines**: 202-243
**Action**: Rename `--yes/-y` to `--force/-F`

───────────────────────────
### Checkpoint: Phase 2
- Run: `podio auth login --help` - should show `--type/-t`, NOT `--flow/-f`
- Run: `podio auth logout --help` - should show `--force/-F`, NOT `--yes/-y`
───────────────────────────

---

## Phase 3: Command Pattern Fixes

### Step 4: Create item list command with --filter
**File**: `<cli-tools-root>/podio/podio_cli/commands/item.py`
**Action**:
- Create new `list` command with `--filter/-f`, `--limit/-l`, `--properties/-p`
- Keep `filter` as hidden deprecated alias with warning

### Step 5: Add --external-id to item get
**File**: `<cli-tools-root>/podio/podio_cli/commands/item.py`
**Action**:
- Add `--external-id` and `--app-id` options to `get` command
- Keep `get-by-external-id` as hidden deprecated alias

### Step 6: Create task label subcommand group
**File**: `<cli-tools-root>/podio/podio_cli/commands/task.py`
**Action**:
- Create `label_app = typer.Typer()` subgroup
- Move `list-labels` → `label list`
- Move `create-label` → `label create`
- Move `update-labels` → `label update`
- Move `delete-label` → `label delete`
- Keep old commands as hidden deprecated aliases

### Step 7: Create webhook field subcommand group
**File**: `<cli-tools-root>/podio/podio_cli/commands/webhook.py`
**Action**:
- Create `field_app = typer.Typer()` subgroup
- Move `create-field` → `field create`
- Move `list-field` → `field list`
- Move `update-field` → `field update`
- Keep old commands as hidden deprecated aliases

### Step 8: Add --url option to space get
**File**: `<cli-tools-root>/podio/podio_cli/commands/space.py`
**Action**:
- Add `--url/-u` option to `get` command
- Keep `find-by-url` as hidden deprecated alias

───────────────────────────
### Checkpoint: Phase 3
- Run: `podio item list --help` - should show `--filter/-f`, `--limit/-l`, `--properties/-p`
- Run: `podio item filter --help` - should show deprecation warning
- Run: `podio task label list --help` - should work
- Run: `podio webhook field create --help` - should work
- Run: `podio space get --help` - should show `--url/-u`
───────────────────────────

---

## Phase 4: Missing Standard Options

### Step 9: Add options to org list
**File**: `<cli-tools-root>/podio/podio_cli/commands/org.py`
**Add**: `--limit/-l` (default 100), `--filter/-f`, `--properties/-p`

### Step 10: Add options to space list
**File**: `<cli-tools-root>/podio/podio_cli/commands/space.py`
**Add**: `--limit/-l` (default 100), `--filter/-f`, `--properties/-p`

### Step 11: Add options to comment list
**File**: `<cli-tools-root>/podio/podio_cli/commands/comment.py`
**Add**: `--filter/-f`, `--properties/-p` (already has `--limit`)

### Step 12: Add options to webhook list
**File**: `<cli-tools-root>/podio/podio_cli/commands/webhook.py`
**Add**: `--limit/-l` (default 100), `--filter/-f`, `--properties/-p`

### Step 13: Add options to webform list
**File**: `<cli-tools-root>/podio/podio_cli/commands/webform.py`
**Add**: `--limit/-l` (default 100), `--properties/-p`

### Step 14: Fix conversation list options
**File**: `<cli-tools-root>/podio/podio_cli/commands/conversation.py`
**Action**: Change default limit from 10 to 100, add `--filter/-f`, `--properties/-p`

### Step 15: Add options to app list
**File**: `<cli-tools-root>/podio/podio_cli/commands/app.py`
**Add**: `--limit/-l` (default 100), `--properties/-p`

───────────────────────────
### Checkpoint: Phase 4
- Run: `podio org list --help` - should show `--limit`, `--filter`, `--properties`
- Run: `podio space list --help` - should show options
- Run: `podio conversation list --help` - default limit should be 100
───────────────────────────

---

## Phase 5: Conversation Pattern Fixes

### Step 16: Create conversation participant subcommand
**File**: `<cli-tools-root>/podio/podio_cli/commands/conversation.py`
**Action**:
- Create `participant_app = typer.Typer()` subgroup
- Move `add-participants` → `participant add`
- Keep old command as hidden deprecated alias

### Step 17: Add ref options to conversation create
**File**: `<cli-tools-root>/podio/podio_cli/commands/conversation.py`
**Action**:
- Add `--ref-type` and `--ref-id` options to `create` command
- Keep `create-on-object` as hidden deprecated alias

───────────────────────────
### Checkpoint: Phase 5
- Run: `podio conversation participant add --help` - should work
- Run: `podio conversation create --help` - should show `--ref-type`, `--ref-id`
───────────────────────────

---

## Phase 6: README Documentation

### Step 18: Update README.md
**File**: `<cli-tools-root>/podio/README.md`
**Action**: Document all new command structures and updated parameters:
- Update auth examples with `--type/-t` and `--force/-F`
- Add `item list` with `--filter` examples
- Add `task label` subcommand examples
- Add `webhook field` subcommand examples
- Add `space get --url` examples
- Document standard options on all list commands

───────────────────────────
### Final Checkpoint
- Run: `<cli-tools-root>/_repo/skills/cli-tool/scripts/test-cli-tool.sh podio`
- All tests should pass (or only have acceptable notes/warnings)
───────────────────────────

---

## What's NOT Included

- **No git init**: Parent directory is already a git repo
- **No breaking removal of old commands**: All deprecated commands kept as hidden aliases
- **No API changes**: Only CLI interface changes, API calls remain the same
- **No new dependencies**: Uses existing Typer patterns

---

## Files Modified

| File | Changes |
|------|---------|
| `output.py` | Replace alias with function |
| `auth.py` | Rename parameters |
| `item.py` | Add list command, extend get command |
| `task.py` | Add label subcommand group |
| `webhook.py` | Add field subcommand group |
| `space.py` | Extend get with --url, add list options |
| `org.py` | Add list options |
| `comment.py` | Add list options |
| `webform.py` | Add list options |
| `conversation.py` | Add participant subcommand, extend create, fix limit |
| `app.py` | Add list options |
| `README.md` | Document all changes |
