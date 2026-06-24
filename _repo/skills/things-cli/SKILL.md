---
name: "things-cli"
description: "MANDATORY: Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. Execute things operations using the `things` CLI tool. CLI interface for Things 3 task management. Triggers: things, things cli, things todos, things tasks, my tasks, my todos, task list, things projects, things areas, things tags, create todo, complete task, today tasks"
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
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `things` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Usage JSON Shape">
Things `usage.json` is a root object whose `.commands` field is an object.
Each command group, such as `todos`, is also an object with a nested `commands`
object. Do not inspect it with `.commands[0]`, `.commands | map(.name)`, or
`.commands.<group>.subcommands`.

Use this schema-safe probe before selecting a command leaf:
```bash
jq '
  .commands
  | if type != "object" then error("expected .commands object")
    else to_entries | map({
      group: .key,
      group_keys: (if (.value | type) == "object" then (.value | keys) else [] end),
      commands_type: (if (.value | type) == "object" then (.value.commands | type) else null end),
      command_names: (
        if (.value | type) == "object" and (.value.commands | type) == "object"
        then (.value.commands | keys)
        else []
        end
      )
    })
    end
' /Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills/things-cli/usage.json
```

After the probe identifies the group and action, select leaves through
`.commands.<group>.commands.<action>`.

When checking command options, do not assume a leaf's `options` field is an
object. Current Things `usage.json` uses option lists for some leaves. Normalize
both shapes before testing for a flag:
```bash
jq --arg group todos --arg action list '
  def option_names:
    if . == null then []
    elif type == "object" then keys
    elif type == "array" then map(.name // .long // .option // empty)
    else error("expected options object, array, or null")
    end;

  .commands[$group].commands[$action]
  | if type != "object" then error("expected command leaf object")
    else {
      leaf_keys: keys,
      options_type: (.options | type),
      option_names: (.options | option_names)
    }
    end
' /Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills/things-cli/usage.json
```
</principle>

<principle name="Read Projection Flags">
`--properties`/`-p` is a read projection flag. Use it only on read commands
whose `usage.json` entry exposes that option, such as `list`, `get`, or
`search`. Do not append `--properties` or `-p` to write commands such as
`things todos create`; create the record first, then verify with a separate
read command if a narrow readback is needed.
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
**`references/macos-tcc-things-readback.md`** -- Diagnosing Things CLI/SQLite readback failures caused by macOS TCC Full Disk Access blocking the Python process.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>

## Known Issues

### 1. `things projects create --area` hangs / times out and creates orphan project in Inbox

**Symptom:** `things projects create "Title" --area <UUID> -n "..."` (and the `~/.claude/hooks/things/create-project.sh` wrapper) appears to hang for 60+ seconds with no output. One observed failure surfaced `AppleScript error: 74:501: execution error: Things3 got an error: AppleEvent timed out. (-1712)`. After the hang the project may actually exist but with `area: null` — the AppleScript created the project, then hung on a separate `set area of newProject to area id "..."` statement, leaving an orphan in the Inbox. Running the command again creates more duplicates. Read commands (`things projects list`, `things areas list`) work fine throughout. First observed on a freshly App-Store-installed Things 3 (3.22.11) on macOS Tahoe (Darwin 25.3.0).

**Cause:** Two compounding bugs in the `things` CLI's `create_project` AppleScript path:
1. `make new project` and `set area` were two sequential statements. If Things3 hung between them (common right after first launch / during initial Things Cloud sync warmup), the project was committed without an area and `osascript` blocked indefinitely on the area assignment.
2. `_run_applescript` ran `osascript` with no `timeout=` on the subprocess, so any AppleEvent hang produced an indefinite block instead of a clear error.

**Fix:** Patched `/Users/adam/Dropbox/GitRepos/cli-tools/things/things_cli/client.py`:
- `create_project` now resolves the area first and passes it inside the `make new project` property bag (`{name:..., notes:..., area:theArea}`), so creation + area assignment is one atomic AppleScript operation. No more orphaned projects on hang.
- `_run_applescript` now accepts `timeout=` (default 30s) and raises a typed `AppleScriptTimeoutError` with actionable next steps when `osascript` exceeds it.
- `create_project` now catches create-timeout failures and performs SQLite read-back by requested title, notes, and area. If exactly one matching incomplete project exists, the CLI returns that durable project instead of forcing a duplicate-prone retry. If no match or multiple matches are found, the error explicitly says whether retry is safe. If `--when someday` was requested and the create committed before the follow-up move, the error reports the existing project UUID and says not to retry creation.

Reinstall after editing the editable source:
```bash
/Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills/cli-tool/scripts/install-cli-tool.sh things
```

**Verification:**
```bash
time things projects create "smoke test" --area <AREA_UUID> -n "test notes"
# Expect: returns in well under 30s with area_uuid populated, area name resolved
things projects delete <returned-uuid> --yes
```

**Recurrence Prevention:** Atomic property-bag creation removes the orphan-project failure mode. The subprocess timeout converts Things3 hangs (e.g., first-launch scenario, Things Cloud auth modal, or revoked Automation permission) into bounded errors. Project creation also performs post-timeout read-back, so a timeout after commit returns the unique durable project or tells the caller not to blindly retry when state is absent, ambiguous, or only partially moved.

**General rule:** When a CLI wraps an external GUI app via AppleScript, every `subprocess.run(['osascript', ...])` call must have a bounded `timeout=`, and multi-step writes that mutate one record must be expressed as a single AppleScript invocation so a hang cannot leave partially-committed state.

**Agent diagnostic rule:** When probing Things3 directly with `osascript` for a suspected hang (for example `tell application "Things3" to count of to dos`), do not rely only on the Hermes/Codex terminal timeout. Wrap `osascript` in an inner watchdog (for example Python `subprocess.run(..., timeout=20)`) and set the terminal timeout higher than that inner timeout. Catch the inner timeout, print an explicit marker such as `APPLESCRIPT_HANG_TIMEOUT_AFTER_20S`, and exit 0 for the expected diagnostic result. A terminal-level `[Command timed out after 40s]` / exit 124 means the diagnostic command was shaped incorrectly and should not be surfaced as the Things finding.

### 2. `things projects delete` requires `--yes` for non-interactive use

**Symptom:** `things projects delete <uuid>` in a non-interactive shell prints `Delete project 'X'? [y/N]:` and then `Error:` and exits non-zero.

**Cause:** `typer.confirm()` prompt has no stdin in agent shells; the empty read is treated as "No" and the command aborts.

**Fix:** Always pass `--yes` (or `-y`) when deleting from automation: `things projects delete <uuid> --yes`. Same flag exists on `things todos delete`.

**Verification:** `things projects delete <uuid> --yes` returns JSON with `"deleted": true` and exit code 0.

**Recurrence Prevention:** Document `--yes` here so future agents do not retry interactive deletes.

### 3. `things todos create/update --deadline` and `--when` appear to silently no-op (deadline/start_date come back null)

**Symptom:** `things todos create "X" --deadline 2026-05-02` (and the same flag on `update`, and `--when <ISO date>` or `--when today`) exits 0, prints `Created todo: <uuid>`, but the returned JSON shows `"deadline": null` and/or `"start_date": null`. Opening Things 3 visually shows the date IS set on the todo, so the write succeeded but the CLI response says it didn't. This breaks any automation that conditions on the JSON response.

**Cause:** `_date_int_to_iso()` in `/Users/adam/Dropbox/GitRepos/cli-tools/things/things_cli/client.py` decoded `TMTask.startDate` and `TMTask.deadline` as "days since 2001-01-01" (Core Data NSDate semantics). Things 3 actually stores those columns as a packed integer: `(year << 16) | (month << 12) | (day << 7)`. With the wrong decoder, a real packed value like `132798336` (= 2026-05-15) was interpreted as ~363,557 days since 2001-01-01, which overflowed `datetime` and the `except (ValueError, OverflowError)` returned `None`. The AppleScript write path was always working; only the read-back was broken. Verified by comparing `osascript ... due date of theToDo` (correct date) against `SELECT deadline FROM TMTask` (packed int) for the same UUID.

**Fix:** Rewrote `_date_int_to_iso` to decode the packed format and `_iso_to_date_int` to encode it (the inverse helper is currently unused but kept for parity). After editing the editable source, reinstall:
```bash
/Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills/cli-tool/scripts/install-cli-tool.sh things
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

**Fix:** Added `--project` and `--area` flags to `things todos update` (mutually exclusive). Editable install at `/Users/adam/Dropbox/GitRepos/cli-tools/things/things_cli/`:
- `client.py` `update_todo()` accepts `project: Optional[str]` and `area: Optional[str]`. Each emits an `updates.append(...)` AppleScript fragment inside the existing `tell application "Things3" / set theToDo to to do id "<uuid>" / ...` block. Raises `ValueError` if both are passed.
- `commands/todos.py` `todos_update` exposes `--project PROJECT_UUID` and `--area AREA_UUID`. CLI-level guard exits 2 with stderr message if both passed.

After editing the editable source, reinstall is not required (it's an editable install — changes are live), but a sanity reinstall is safe:
```bash
/Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills/cli-tool/scripts/install-cli-tool.sh things
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

### 5. `things todos update` / `uncomplete` AppleScript timeout can hide partial writes

**Symptom:** A multi-field `things todos update <uuid> --title ... --notes ... --area ...` timed out with `AppleScript timed out after 30s`. SQLite read-back showed the todo had unexpectedly become completed (`status: 3`) while the requested title/notes/area fields were unchanged. A follow-up `things todos uncomplete <uuid>` also timed out and read-back still showed `status: 3`.

**Cause:** AppleScript writes go through the GUI app. If `osascript` is killed by the subprocess timeout while Things3 is unresponsive/syncing/modal-blocked, the AppleEvent may already have partially committed or Things3 may commit a side effect before the CLI receives an error. A generic timeout error is insufficient because it does not tell the caller whether the task changed.

**Fix:** Patched `/Users/adam/Dropbox/GitRepos/cli-tools/things/things_cli/client.py`:
- `_run_applescript` now raises `AppleScriptTimeoutError`, a typed subclass of `ClientError`, for subprocess timeouts.
- `complete_todo` and `uncomplete_todo` perform immediate SQLite read-back on AppleScript timeout. If the intended status is already durable, the command returns success; otherwise the error includes the durable status observed after the timeout.
- `update_todo` captures a pre-write snapshot and, on AppleScript timeout, reads the task again and reports a field-level before/after diff. If status changed unexpectedly, the error explicitly says not to blindly retry the same update and to use the smallest status-only recovery command only after confirming current read-back.

**Verification:** Unit coverage in `things/tests/test_completion_readback.py` exercises committed completion after timeout, failed uncomplete timeout read-back, and update timeout partial-status reporting.

**Recurrence Prevention:** Any future timeout during todo update/status writes now carries durable read-back evidence instead of a generic GUI-state error. This does not make Things3 AppleScript atomic; it prevents hidden partial writes and gives agents a safe recovery decision point.

### 6. Things readback fails with macOS TCC / Full Disk Access error

**Symptom:** Things writes may dispatch via URL or AppleScript, but readback commands fail before emitting JSON. The observed Progress-project command:
```bash
things projects search "Progress" --properties uuid,title,notes,tags,area_uuid,status,deadline,start_date
```
exited 1 with:
```text
Error: Timed out while accessing the Things database container. macOS privacy/TCC is blocking filesystem access to Things data. Grant Full Disk Access to the Python binary running this CLI (/Users/adam/.local/share/uv/tools/things-cli/bin/python), then retry.
```

**Cause:** Things read commands discover and open the SQLite database under `~/Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac/...`, which is protected by macOS privacy controls. If Full Disk Access is missing for the exact Python executable in the `things` launcher shebang, macOS can block filesystem traversal. The CLI hardening in `client.py` converts the old silent hang into the explicit timeout error above.

**Fix:** This cannot be completed autonomously from an agent shell. A user/admin must grant Full Disk Access to the exact Python named in the error. For the current install, that is:
```text
/Users/adam/.local/share/uv/tools/things-cli/bin/python
```
If System Settings shows that path as a greyed-out alias/symlink, grant Full Disk Access to the Homebrew Python app bundle instead:
```text
/opt/homebrew/Frameworks/Python.framework/Versions/3.14/Resources/Python.app
```
Do not grant `pip3` as a substitute. `pip3` may be selectable because it is a script with a shebang into the same Python install, but the Things CLI runs as Python, not pip.
Open the pane with:
```bash
open 'x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles'
```
Add/enable the Python binary or Python.app bundle, then rerun a readback smoke test:
```bash
things todos list --limit 1 --exclude-tag WF
```

**Agent rule:** Do not retry the write or create duplicate Things tasks when this error appears. Treat it as a local readback permission blocker, report the Full Disk Access action, and resume verification after the permission is granted.

**Reference:** See `references/macos-tcc-things-readback.md` for diagnostics and the CLI hardening pattern.
