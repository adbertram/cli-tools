---
name: outlier-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Outlier operations using the `outlier` CLI tool.
  Browser-automation CLI for the Outlier AI worker portal (app.outlier.ai): list queued gig work assignments, inspect one assignment, and read why the queue is empty.
  Triggers: outlier, outlier cli, outlier ai, outlier tasks, outlier queue, outlier gig work, app.outlier.ai
---

<objective>
Execute Outlier operations using the `outlier` CLI. All Outlier interactions should use this CLI.
</objective>

<quick_start>
The `outlier` CLI follows this pattern:
```bash
outlier <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Configure authentication credentials | `outlier auth login` |
| Clear stored credentials and browser sessions | `outlier auth logout` |
| Create a new profile from .env.example template | `outlier auth profiles create <NAME>` |
| Delete a profile and its data | `outlier auth profiles delete <NAME>` |
| Get details for a specific profile | `outlier auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `outlier auth profiles list` |
| Delete a profile and its data | `outlier auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `outlier auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `outlier auth profiles select <NAME>` |
| Check authentication status across profiles | `outlier auth status` |
| Test authentication by verifying credentials work across profiles | `outlier auth test` |
| Remove all cached responses | `outlier cache clear` |
| Show queue state, including why the queue is empty when it is | `outlier queue status` |
| Get full detail for a single queued assignment | `outlier tasks get <TASK_ID>` |
| List the work assignments currently queued for this Outlier account | `outlier tasks list` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `outlier` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `outlier --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage outlier authentication (subcommands: login, logout, profiles, status, test)
- **cache** -- Manage response cache (subcommands: clear)
- **queue** -- Inspect the Outlier task queue itself (subcommands: status)
- **tasks** -- Inspect queued Outlier work assignments (subcommands: get, list)
</principle>

<principle name="Passwordless Login Is Automatic">
Outlier has NO password, API key, or token — sign-in is a one-time link emailed
to the account. `outlier auth login` runs that whole flow headlessly with no
terminal prompt and no visible browser: it submits `ACCOUNT_EMAIL`, reads the
fresh link back through the repo-owned `google` CLI, and opens it.

Do NOT ask Adam for an Outlier password, look for one in LastPass, or create a
secret-manager entry for Outlier — none exists. Do NOT drive a separate browser
surface to log in; the CLI's own persistent profile is the session of record.

`auth login` needs two things: `ACCOUNT_EMAIL` in
`~/.local/share/cli-tools/outlier/.env`, and an authenticated `google` CLI for
that mailbox.
</principle>

<principle name="An Empty Task List Is Data, Not A Failure">
`outlier tasks list` returning `[]` usually means the account's queue is
genuinely empty, not that a parser broke. Run `outlier queue status` to get
Outlier's own reason in `empty_queue_reason` (its
`preAssignmentEmptyQueueReason`), and report that reason rather than retrying.

Observed values include `KYCInfoCollection`, `PaySetup`, `TaxSetup`
(all rendered by Outlier as "please complete the required pay setup"),
`AccountVerification`, `PausedProject`, `NoTasks`, and
`NoTasksMatchingSpecializations`.

As of 2026-09-02 this account reports `KYCInfoCollection`: the queue stays
empty until a human completes identity/pay setup, which needs government ID,
tax, and payout details. Never automate that step.
</principle>

<principle name="No Apply Command Exists">
This CLI is read-only. It cannot accept, claim, or submit an Outlier task, and
must not be extended to do so without Adam's explicit per-task approval.
</principle>

</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`outlier --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
