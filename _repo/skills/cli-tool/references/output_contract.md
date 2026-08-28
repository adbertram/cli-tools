# Output Contract

Reusable output contract for agents whose primary domain skill is `cli-tool`.

## Returned Structure

Return the final response with these sections, in this order:

```
## What was accomplished
<one or two sentences naming the CLI tool and the concrete change or finding>

## Files changed
- `<path>` — <what changed>
(or: No files changed.)

## Validation performed
- `<exact command run>` — <actual result>
(Live CLI execution is required. `--help` output and unit tests alone are not sufficient.)

## Issues encountered
<each issue and how it was resolved>
(or: No issues encountered.)

## Unresolved blockers
<exact blocker, the validation that did run, and the specific next action or input needed>
(or: None.)

## Turn-end reflection
- Blockers: <what got in the way, or None>
- Resolution: <how each was cleared>
- Prevention: <what would stop it recurring>
```

## Filled Example

```
## What was accomplished
Added a `--view` filter to `airtable records list` so records can be pulled from a
named Airtable view instead of the whole table.

## Files changed
- `airtable/cli.py` — added `--view` option, passed through to the records request
- `airtable/tests/test_records.py` — added coverage for the view filter and an
  unknown-view error case

## Validation performed
- `airtable records list --table Programs --view Grid --json` — returned 12 records,
  all present in the Grid view
- `airtable records list --table Programs --view NoSuchView` — exited 1 with
  `Unknown view: NoSuchView`, as intended
- `pytest airtable/tests` — 34 passed

## Issues encountered
No issues encountered.

## Unresolved blockers
None.

## Turn-end reflection
- Blockers: None
- Resolution: n/a
- Prevention: n/a
```

## Rules

- Never report success for created, updated, or repaired CLI behavior without a live
  command and its actual output.
- Report every side effect: file writes, venv installs, live command execution, and
  secret-manager writes.
- If authentication or an external service blocks validation, state the exact blocker
  and list the validation that did run rather than omitting the section.
