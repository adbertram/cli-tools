---
name: "manus-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute manus operations using the `manus` CLI tool. CLI interface for Manus AI API -- create and manage AI tasks, profiles, and authentication. Triggers: manus, manus cli, manus task, manus ai, create manus task, run manus, manus agent, list manus tasks, manus auth profiles"
---

<objective>
Execute manus operations using the `manus` CLI. All manus interactions should use this CLI.
</objective>

<quick_start>
The `manus` CLI follows this pattern:
```bash
manus <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check auth status | `manus auth status` |
| Create a task | `manus task create "Your prompt here"` |
| Create task (no wait) | `manus task create "Prompt" --no-wait` |
| Send a follow-up | `manus task send TASK_ID "Follow-up"` |
| Get task metadata | `manus task get TASK_ID` |
| List recent tasks | `manus task list --table` |
| List task messages | `manus task messages TASK_ID --limit 20` |
| Check available credits | `manus usage available-credits` |
| Confirm a waiting task | `manus task confirm TASK_ID EVENT_ID` |
| List profiles | `manus auth profiles list --table` |
| Set default profile | `manus auth profiles select PROFILE_NAME` |
| Inspect cache commands | `manus cache --help` |

Auth status output uses the shared profile shape: `{"profiles":[{"name":"default","authenticated":true,"credential_types":{...}}]}`. Read `auth profiles[].authenticated` for per-profile status; do not expect a flat top-level `authenticated` field.

`manus task create` checks `usage.availableCredits` and fails before submission when the authoritative `total_credits` field is present and at or below zero. It does not treat `max_refresh_credits` (the next refresh grant cap) or `pro_monthly_credits` (the plan quota) as current spendable balance. When the live response omits `total_credits`, `task.create` remains the admission authority because Manus does not publish a reliable per-task cost estimate. Only a 429 with `error.code: rate_limited` is retried; `resource_exhausted` credit failures return immediately.
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `manus` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage API authentication (login, logout, status, refresh, test)
- **task** -- Manage Manus API v2 tasks (create, send, continue alias, get, wait, list, messages, update, stop, delete, confirm)
- **auth** -- Authentication commands and nested `auth profiles` management
</principle>

<principle name="Wait Semantics">
`task create`, `task send`, and `task wait` with `--wait` (the default) poll until the task reaches `stopped`, `error`, or a `waiting` status with a confirmable event (`status_update.status_detail.waiting_for_event_id`, for example `messageAskUser`). A `waiting` status without a confirmation event (queued task that has not started running) is non-terminal; the CLI keeps polling. Do not add manual `task get` polling loops around `--wait`. On `--timeout` expiry the command exits non-zero with a timeout error.
</principle>

<principle name="Structured Output Schema Constraints">
`--structured-output-schema` / `--structured-output-schema-file` only accept the restricted JSON Schema subset documented at `https://open.manus.ai/docs/v2/structured-output` (basic `type`, `properties`, `required`, `additionalProperties`, `items`, `enum`, `description`, `anyOf`, `$ref`/`$defs`). Validation-constraint keywords -- `minimum`, `maximum`, `exclusiveMinimum`, `exclusiveMaximum`, `multipleOf`, `pattern`, `format`, `minLength`, `maxLength`, `minItems`, `maxItems`, `uniqueItems`, `minProperties`, `maxProperties`, `allOf`, `oneOf`, `not`, `if`/`then`/`else` -- are rejected by the API with a generic `400 invalid_argument: "unexpected error from node server"` that gives no hint which keyword caused it (confirmed by live repro against the API). The CLI strips these keywords automatically before submission and prints a `Warning:` line naming what it removed; it does not silently change schema shape. If a field needs a bound communicated to the model, put it in that field's `description` (e.g. `"description": "Integer, must be 0 or greater"`) instead of a constraint keyword.
</principle>

<principle name="Preserve Producer Status">
When wrapping `manus task create`, `manus task send`, `manus task wait`, or any other Manus producer command with trailing reporting, raw-output printing, cleanup, or JSON inspection, capture the Manus command status immediately and exit with that status after reporting. Do not let a later successful `printf`, `cat`, `jq`, `rm`, or summary command mask a timeout or API failure.

Use this shape:
```bash
set +e
manus task create --prompt-file "$prompt_file" --agent-profile manus-1.6 --timeout 1200 --poll 5 --title "$title" >"$output_file" 2>"$stderr_file"
manus_rc=$?
set -e

if [ "$manus_rc" -ne 0 ]; then
  printf '%s\n' 'MANUS_COMMAND_FAILED'
  cat "$stderr_file" >&2
fi

exit "$manus_rc"
```
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
