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

<principle name="Todo Notes Length Limit">
Things 3's AppleScript interface silently truncated the reproduced ASCII todo
notes after 39,999 characters. The CLI uses a conservative 39,999 UTF-16-code-
unit safety limit and rejects longer `todos create --notes` and `todos update
--notes` inputs before touching Things. Do not bypass this guard or treat an
older CLI's zero exit status as proof of full storage. See
`references/notes-length-limit.md` for evidence and Unicode counting details.
</principle>

<principle name="Someday Is Not The Same As Upcoming">
Things stores the `when` field as `start` plus `start_date`. Read both fields
together; `start` alone does not name a Things list.

| `start` | `start_date` | Things list |
|---------|--------------|-------------|
| 0 | null | Inbox |
| 1 | null | Anytime |
| 1 | today or earlier | Today |
| 2 | null | Someday |
| 2 | a date | Upcoming (scheduled for that date) |

A to-do scheduled for a future date keeps `start: 2`. That is correct, not a
failed write. Do not read `start: 2` as "still in Someday" when `start_date` is
set, and do not re-issue the same `--when <date>` command. `things todos list
--table` prints `Upcoming` for that state; JSON output keeps the raw integer.

`things todos list --when someday` returns only dateless Someday rows. Use
`--when upcoming` for scheduled rows.
</principle>

<principle name="Empty-String Clears And Verified Writes">
`things todos update` and `things projects update` read every requested field
back from the Things database after the write. If Things did not persist a
requested field, the command exits non-zero and names each unpersisted field
plus the current `start`, `start_date`, `deadline`, and `tags`. A zero exit
status from these two commands now proves the change landed. Treat a non-zero
exit as an unapplied or partly applied update; re-read the record before
retrying.

Pass an empty string to clear a field:

| Command | Effect |
|---------|--------|
| `things todos update UUID --tags ""` | Removes every tag |
| `things todos update UUID --deadline ""` | Clears the deadline |
| `things todos update UUID --when ""` | Clears the activation date (moves to Anytime) |
| `things todos update UUID --area ""` | Removes the todo from its area and project |
| `things projects update UUID --tags ""` | Removes every tag |
| `things projects update UUID --deadline ""` | Clears the deadline |
| `things projects update UUID --area ""` | Removes the project from its area |

`--project ""` is not supported; use `--area ""` or `--when inbox`.
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
**`references/notes-length-limit.md`** -- Empirical 39,999 UTF-16-code-unit todo notes limit, pre-mutation CLI guard, and agent handling.
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
can exit 1 with either of these Full Disk Access/TCC errors:
```text
Error: Timed out while accessing the Things database container. macOS privacy/TCC is blocking filesystem access to Things data. Grant Full Disk Access to the Python binary running this CLI (/Users/adam/.local/share/uv/tools/things-cli/bin/python), then retry.
```
```text
Error: Permission denied while accessing the Things database container. macOS privacy/TCC is blocking filesystem access to Things data. Grant Full Disk Access to the Python binary running this CLI (/Users/adam/.local/share/uv/tools/things-cli/bin/python), then retry. Underlying error: [Errno 1] Operation not permitted: '/Users/adam/Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac'
```
Older installs could misreport the immediate `Operation not permitted` form as `Things database not found` because glob returned no matches under the protected container.

**Cause:** Things read commands discover and open the SQLite database under `~/Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac/...`, which is protected by macOS privacy controls. If Full Disk Access is missing for the exact Python executable in the `things` launcher shebang, macOS can block filesystem traversal or return `Operation not permitted`. The CLI hardening in `client.py` converts the old silent hang/misleading no-match into explicit Full Disk Access errors.

**Fix:** This cannot be completed autonomously from an agent shell. A user/admin must grant Full Disk Access to the exact responsible Python executable named in the live error. The CLI resolves `sys.executable` with `os.path.realpath(...)`, so TCC attribution follows the resolved executable rather than the `things` launcher or its shebang symlink. For the current install, that is:
```text
/Users/adam/.local/share/uv/python/cpython-3.11.15-macos-aarch64-none/bin/python3.11
```
Do not grant `/Users/adam/.local/share/uv/tools/things-cli/bin/python`, `pip3`, Terminal, or a different Homebrew/Python bundle as a substitute when the live error names another executable.
Open the pane with:
```bash
open 'x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles'
```
Add/enable that exact Python executable, then rerun a readback smoke test:
```bash
things todos list --limit 1 --exclude-tag WF
```

If the blocked caller is a scheduled Hermes cron run, restart the cron host with `hermes gateway restart` before rerunning the probe.

**Agent rule:** Do not retry the write or create duplicate Things tasks when this error appears. Treat it as a local readback permission blocker, report the Full Disk Access action, and resume verification after the permission is granted.

**Reference:** See `references/macos-tcc-things-readback.md` for diagnostics and the CLI hardening pattern.

### 7. `things todos create --area` AppleScript tries to set an area object to itself

**Symptom:** `things todos create "Title" --area <AREA_UUID>` can exit 1 with `Things3 got an error: Can’t set area id "<AREA_UUID>" to area id "<AREA_UUID>". (-10006)` after the todo has already been created.

**Cause:** `create_todo` used the inline AppleScript assignment `set area of theToDo to area id "<AREA_UUID>"`. In Things3's AppleScript dictionary, using the `area` property and `area id` object selector in the same assignment is parsed as an attempt to set the resolved area object to itself. A tested alternative that put `area:theArea` in the todo creation property bag was accepted but silently ignored when the todo was created at the beginning of a Things list.

**Fix:** Resolve the area object first, then assign the variable in the existing post-create AppleScript:
```applescript
set theToDo to (to do id "<TODO_UUID>")
set theArea to area id "<AREA_UUID>"
set area of theToDo to theArea
```
The focused regression test is `things/tests/test_completion_readback.py::test_create_todo_in_area_resolves_area_before_assignment`.

**Verification:** Create a uniquely titled disposable todo with `--area`, read it back by UUID and verify both `area_uuid` and `area`, then delete it with `things todos delete <UUID> --yes`. If the configured area UUID no longer appears in `things areas list`, do not create against it or create a replacement area implicitly; report the stale mapping and use an explicitly approved current area for live CLI-path verification.

**Recurrence Prevention:** Keep area resolution and property assignment as separate AppleScript statements inside one bounded `osascript` call. Do not inline `area id` on the right side of `set area of ...`, and do not move todo area placement into the creation property bag without a live readback proving Things persisted it.

### 8. A repeating to-do cannot be rescheduled from outside Things

**Symptom:** `things todos update <uuid> --when today` (or `--when anytime`) failed with `AppleScript error: ... Things3 got an error: Cannot move to-do (301)`, and `--when <ISO date>` failed with `Cannot schedule to-do (302)`. The to-do's `start` and `start_date` never changed. The to-do looked like an ordinary dateless Someday row (`start: 2`, `start_date: null`) with no project and no area, which made the missing container look like the cause.

**Cause:** The to-do was a repeating template: `TMTask.rt1_recurrenceRule` was populated and `TMTask.rt1_repeatingTemplate` was null. Things 3 refuses `when` changes on a repeating to-do through every external channel. AppleScript returns 301 for `move` and 302 for `schedule`. The Things URL scheme documents the same restriction for `update`: "This field cannot be updated on repeating to-dos", and a live `things:///update?...&when=today` against a real repeating template produced a byte-identical `TMTask` row. The missing project/area was not the cause: a purpose-created dateless Someday to-do with no project and no area moved to Today, Anytime, and an ISO date without error.

**Fix:** `client.py` `update_todo` now detects a repeating template through `_is_repeating()` before issuing any write and raises a `ClientError` that names the limitation and the manual alternative. No partial write is attempted.

**Verification:**
```bash
things todos update <repeating-todo-uuid> --when today
# Exit 1 with "Things 3 does not allow the `when` field of a repeating to-do..."
things todos get <repeating-todo-uuid> --properties uuid,start,start_date
# Unchanged
```

**Recurrence Prevention:** Do not retry `--when` on a repeating to-do, and do not try the URL scheme as an alternative. Change the repeat schedule in the Things app, or reschedule a generated instance instead of the template. Identify a template with `SELECT rt1_recurrenceRule, rt1_repeatingTemplate FROM TMTask WHERE uuid = '<uuid>'`: a template has a rule and no parent template.

### 9. `things todos/projects update` printed "Updated" for writes Things ignored

**Symptom:** `things todos update <uuid> --when <ISO date>` printed `Updated: <title>` and exited 0 while the requested placement did not change. `things todos update <uuid> --tags ""` printed `Updated: <title>` and exited 0 while the todo kept its tags. In a combined `--title "New" --tags ""` call the title persisted and the tag clear did not, so one command silently applied part of its requested change. `things projects update <uuid> --when today` silently moved the project to Anytime instead of rejecting an unsupported value.

**Cause:** Two separate defects. First, no write path verified its own result: `update_todo` and `update_project` returned a fresh read without comparing it against what the caller asked for, so any write Things accepted and then ignored looked like success. Second, both command modules parsed tags with `[t.strip() for t in tags.split(",")] if tags else None`, so `--tags ""` evaluated to `None` and the tag write was skipped entirely.

**Fix:**
- `client.py` `_verify_persisted_updates()` compares every requested field against the post-write read and raises `UnpersistedUpdateError` (a `ClientError` subclass, exit 1) naming each unpersisted field plus the current `start`, `start_date`, `deadline`, and `tags`. Both `update_todo` and `update_project` call it as their final gate.
- `_expected_when_state()` holds the verified `start`/`start_date` result for every `when` value.
- `commands/todos.py` and `commands/projects.py` now treat `--tags ""` as an explicit clear (`[]`) and only a missing `--tags` as "leave tags alone".
- `update_project` rejects any `when` other than `anytime` or `someday` instead of defaulting to Anytime.

**Verification:** `things/tests/test_update_verification.py` covers Someday to today/anytime/ISO date (with and without an existing start date), unpersisted-write failures, partial-update failures, tag clears, and the option parsing. Live checks: clear tags on a WF-tagged todo, then read back `tags`.

**Recurrence Prevention:** Every new `things` write path must add its requested fields to the `expectations` dict so the shared verification gate covers it. Never report success for a Things write on process exit status alone.

### 10. Things 3 rejects `missing value`, so clears use the Things URL scheme (-1700)

**Symptom:** `things todos update <uuid> --deadline ""` failed with `AppleScript error: ... Things3 got an error: Can't make missing value into type date. (-1700)`, and the deadline stayed set. The same error appeared for `things projects update <uuid> --area ""` (`... into type area`) and for the old `--when ""` path (`... into type date`). The raw object model failed the same way outside the CLI.

**Cause:** In `/Applications/Things3.app/Contents/Resources/Things.sdef` the `due date` and `activation date` properties are typed `date` and the `area` property is typed `area`. None is optional, so Things rejects `missing value` for all three. `activation date` is additionally `access="r"`. There is no AppleScript expression that clears any of them.

**Fix:** Clears go through the Things URL scheme, which documents that "including a parameter with an equals sign but without a value will clear that value". `client.py` `_run_url_scheme()` sends `things:///update` and `things:///update-project` through `open -g` (background, so a CLI write cannot steal focus). The required URL scheme token is read live from `TMSettings.uriSchemeAuthenticationToken` in the same Things database the CLI already reads, so no credential is stored anywhere. AppleScript still handles every non-clear write.

**Verification:**
```bash
things todos update <uuid> --deadline ""   && things todos get <uuid> --properties uuid,deadline
things todos update <uuid> --when ""       && things todos get <uuid> --properties uuid,start,start_date
things todos update <uuid> --area ""       && things todos get <uuid> --properties uuid,area_uuid,project_uuid
things projects update <uuid> --deadline "" && things projects get <uuid> --properties uuid,deadline
things projects update <uuid> --area ""     && things projects get <uuid> --properties uuid,area_uuid
```

**Recurrence Prevention:** Do not retry `set <property> of ... to missing value` in Things AppleScript for `due date`, `activation date`, or `area`; -1700 is a fixed Things limitation, not a transient error. Route new clear operations through `_run_url_scheme` and add the cleared field to the update's `expectations` dict.

`--when tomorrow` and `--when evening` also use the URL scheme: Things has no `Tomorrow` or `Evening` list object, so `move to list "Tomorrow"` fails with 301 and `move to list "Evening"` fails with -1728.

Three production todos (`WWc1WKk5gbpigcAMVdpR7e`, `WUCbHReRa46AmJsNv7UvvS`, `CuTmbBEwc4mCbFkPHp8M2R`) carry a `4001-01-01` sentinel deadline. All three are repeating templates, and Things documents that `deadline` cannot be updated on a repeating to-do, so no supported command can clear them. `--deadline ""` on those three now exits non-zero and names the repeating limitation. Remove those deadlines in the Things app.
