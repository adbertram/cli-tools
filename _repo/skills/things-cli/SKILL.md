---
name: "things-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute things operations using the `things` CLI tool. CLI interface for Things 3 task management. Triggers: things, things cli, things todos, things tasks, my tasks, my todos, task list, things projects, things areas, things tags, create todo, complete task, today tasks"
---

<objective>
Execute things operations using the `things` CLI. All Things 3 interactions should use this CLI.
</objective>

<quick_start>
The `things` CLI follows this pattern:
```bash
things <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List today's todos | `things todos list --when today` |
| Create a todo | `things todos create "Title" -n "Notes" -w someday` |
| Complete a todo | `things todos complete UUID` |
| Search todos | `things todos search "query"` |
| List projects | `things projects list` |
| List areas | `things areas list` |
| List tags | `things tags list` |
| Check database access | `things todos list --limit 1` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `things` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **todos** -- Manage todos (list, get, create, complete, uncomplete, delete, update, search)
- **projects** -- Manage projects (list, get, create, complete, delete, update, search)
- **areas** -- Manage areas (list, get, create, delete, update, search)
- **tags** -- Manage tags (list, get, search)
</principle>

<principle name="WF Tag Exclusion">
Exclude WF-tagged items by default when listing todos: pipe output through `jq '[.[] | select((.tags // []) | index("WF") | not)]'`.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>

## Known Issues

### 1. `things projects create --area` hangs / times out and creates orphan project in Inbox

**Symptom:** `things projects create "Title" --area <UUID> -n "..."` appears to hang for 60+ seconds with no output. One observed failure surfaced `AppleScript error: 74:501: execution error: Things3 got an error: AppleEvent timed out. (-1712)`. After the hang the project may actually exist but with `area: null` — the AppleScript created the project, then hung on a separate `set area of newProject to area id "..."` statement, leaving an orphan in the Inbox. Running the command again creates more duplicates. Read commands (`things projects list`, `things areas list`) work fine throughout. First observed on a freshly App-Store-installed Things 3 (3.22.11) on macOS Tahoe (Darwin 25.3.0).

**Cause:** Two compounding bugs in the `things` CLI's `create_project` AppleScript path:
1. `make new project` and `set area` were two sequential statements. If Things3 hung between them (common right after first launch / during initial Things Cloud sync warmup), the project was committed without an area and `osascript` blocked indefinitely on the area assignment.
2. `_run_applescript` ran `osascript` with no `timeout=` on the subprocess, so any AppleEvent hang produced an indefinite block instead of a clear error.

**Fix:** Patched `<repo-root>/things/things_cli/client.py`:
- `create_project` now resolves the area first and passes it inside the `make new project` property bag (`{name:..., notes:..., area:theArea}`), so creation + area assignment is one atomic AppleScript operation. No more orphaned projects on hang.
- `_run_applescript` now accepts `timeout=` (default 30s) and raises a `ClientError` with actionable next steps when `osascript` exceeds it.

Reinstall after editing the editable source:
```bash
_repo/skills/cli-tool/scripts/install-cli-tool.sh things
```

**Verification:**
```bash
time things projects create "smoke test" --area <AREA_UUID> -n "test notes"
# Expect: returns in well under 30s with area_uuid populated, area name resolved
things projects delete <returned-uuid> --yes
```

**Recurrence Prevention:** Atomic property-bag creation removes the orphan-project failure mode entirely. The subprocess timeout converts any remaining Things3 hang (e.g., a future first-launch scenario, Things Cloud auth modal, or revoked Automation permission) into an immediate, actionable error instead of a 60s+ block. If the timeout fires, the error message itself directs the user to: foreground Things3, dismiss any modal dialogs, and verify Automation permission in System Settings > Privacy & Security > Automation.

**General rule:** When a CLI wraps an external GUI app via AppleScript, every `subprocess.run(['osascript', ...])` call must have a bounded `timeout=`, and multi-step writes that mutate one record must be expressed as a single AppleScript invocation so a hang cannot leave partially-committed state.

### 2. `things projects delete` requires `--yes` for non-interactive use

**Symptom:** `things projects delete <uuid>` in a non-interactive shell prints `Delete project 'X'? [y/N]:` and then `Error:` and exits non-zero.

**Cause:** `typer.confirm()` prompt has no stdin in agent shells; the empty read is treated as "No" and the command aborts.

**Fix:** Always pass `--yes` (or `-y`) when deleting from automation: `things projects delete <uuid> --yes`. Same flag exists on `things todos delete`.

**Verification:** `things projects delete <uuid> --yes` returns JSON with `"deleted": true` and exit code 0.

**Recurrence Prevention:** Document `--yes` here so future agents do not retry interactive deletes.

### 3. `things todos create/update --deadline` and `--when` appear to silently no-op (deadline/start_date come back null)

**Symptom:** `things todos create "X" --deadline 2026-05-02` (and the same flag on `update`, and `--when <ISO date>` or `--when today`) exits 0, prints `Created todo: <uuid>`, but the returned JSON shows `"deadline": null` and/or `"start_date": null`. Opening Things 3 visually shows the date IS set on the todo, so the write succeeded but the CLI response says it didn't. This breaks any automation that conditions on the JSON response.

**Cause:** `_date_int_to_iso()` in `<repo-root>/things/things_cli/client.py` decoded `TMTask.startDate` and `TMTask.deadline` as "days since 2001-01-01" (Core Data NSDate semantics). Things 3 actually stores those columns as a packed integer: `(year << 16) | (month << 12) | (day << 7)`. With the wrong decoder, a real packed value like `132798336` (= 2026-05-15) was interpreted as ~363,557 days since 2001-01-01, which overflowed `datetime` and the `except (ValueError, OverflowError)` returned `None`. The AppleScript write path was always working; only the read-back was broken. Verified by comparing `osascript ... due date of theToDo` (correct date) against `SELECT deadline FROM TMTask` (packed int) for the same UUID.

**Fix:** Rewrote `_date_int_to_iso` to decode the packed format and `_iso_to_date_int` to encode it (the inverse helper is currently unused but kept for parity). After editing the editable source, reinstall:
```bash
_repo/skills/cli-tool/scripts/install-cli-tool.sh things
```

**Verification:**
```bash
things todos create "Verify deadline" --area <AREA_UUID> --deadline "2026-05-15"
# JSON response must include "deadline": "2026-05-15"
things todos create "Verify when ISO" --area <AREA_UUID> --when "2026-05-20"
# JSON response must include "start_date": "2026-05-20"
things todos create "Verify when today" --area <AREA_UUID> --when today
# JSON response must include "start_date": "<today ISO date>"
```
Clean up with `things todos delete <uuid> --yes` for each.

**Recurrence Prevention:** The decoder now uses the correct bit layout, so any future date-bearing column read from `TMTask` will return real ISO dates. If Things 3 ever changes its internal date encoding (unlikely; this format is stable across major versions), the symptom will be wrong dates rather than silent nulls, which is much more visible. There are no unit tests covering this conversion — add one if `_date_int_to_iso` is touched again.

**General rule:** When a CLI both writes through one channel (AppleScript) and reads back through another (direct SQLite), every shared field must have a round-trip test that proves write-then-read returns the original value. Silent decoder failures look identical to write failures and waste hours of diagnosis time.

### 4. `things todos update` missing `--project` and `--area` for cross-project reassignment

**Symptom:** Need to move an existing todo from one project to another (e.g., re-parent an audit-cluster bug after the original project closes). `things todos update <uuid> --project <new-project-uuid>` returns `Error: No such option: --project` and exits 2. Same for `--area`. The update command only exposed `--title --notes --when --deadline --tags`. No `things todos move` command exists either.

**Cause:** Feature gap. `client.py:update_todo` did not accept `project` / `area` kwargs and `commands/todos.py:todos_update` did not surface the CLI flags. Things 3 AppleScript fully supports `set project of theToDo to project id "<uuid>"` and `set area of theToDo to area id "<uuid>"`, so the underlying capability existed — just not wired up.

**Fix:** Added `--project` and `--area` flags to `things todos update` (mutually exclusive). Editable install at `<repo-root>/things/things_cli/`:
- `client.py` `update_todo()` accepts `project: Optional[str]` and `area: Optional[str]`. Each emits an `updates.append(...)` AppleScript fragment inside the existing `tell application "Things3" / set theToDo to to do id "<uuid>" / ...` block. Raises `ValueError` if both are passed.
- `commands/todos.py` `todos_update` exposes `--project PROJECT_UUID` and `--area AREA_UUID`. CLI-level guard exits 2 with stderr message if both passed.

After editing the editable source, reinstall is not required (it's an editable install — changes are live), but a sanity reinstall is safe:
```bash
_repo/skills/cli-tool/scripts/install-cli-tool.sh things
```

**Verification:**
```bash
things todos update --help  # should list --project and --area
things todos update <todo-uuid> --project <project-uuid>
things todos get <todo-uuid>  # project_uuid should match the new project
things todos update <todo-uuid> --project X --area Y  # should exit 2 with "Pass only one of --project or --area, not both."
```

**Recurrence Prevention:** Feature now exists in the editable install. If the editable mapping is ever broken or someone reinstalls from PyPI/origin without this patch, the symptom will be the same `No such option: --project` error and the same fix applies. If/when the upstream things-cli repo accepts a PR with this change, this Known Issue can be downgraded to a Domain Knowledge entry documenting the flags.

**General rule:** When a CLI command requires moving a record across containers (project ↔ project, area ↔ area, project ↔ area), expose those moves on the `update` command rather than a separate `move` command. The single-update surface keeps the mental model "every property of a record is mutable via update" and avoids the cliff where some properties have flags and others require a different verb.

### 5. Recurring backing todos are not the same row as visible Today instances

**Symptom:** A recurring todo is visible in Things Today, but `things todos complete <uuid>` against the recurring backing row times out or leaves the visible Today task incomplete. `things todos list --when today` can also miss overdue generated instances if it exact-matches `startDate`.

**Cause:** Things stores repeating todos as a backing/template row plus generated instance rows. The backing row contains recurrence metadata (`rt1_recurrenceRule`), while actionable Today instances point back through `rt1_repeatingTemplate`. Completing the backing row does not complete the visible generated instance. Things date columns are packed date integers, and the Today view includes generated instances with `startDate <= today`, not only exact today.

**Fix:** Patched `<repo-root>/things/things_cli/client.py`:
- `list_todos(when="today")` now uses Things packed dates and includes overdue generated instances with `startDate <= today`.
- `complete_todo()` resolves recurring backing rows to the latest open generated instance due today or earlier, then completes that instance.

**Verification:**
```bash
uv run --with pytest python -m pytest
things todos list --when today --status incomplete --exclude-tag WF --properties uuid,title,status,deadline,start_date,when
things todos complete <recurring-backing-uuid>
```

**General rule:** For recurring Things todos, automate against generated instance rows for user-visible actions, and treat backing rows as recurrence definitions.
