---
name: microworker-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Microworker operations using the `microworker` CLI tool.
  CLI interface for Microworker.
  Triggers: microworker, microworker cli
---

<objective>
Execute Microworker operations using the `microworker` CLI. All Microworker interactions should use this CLI.
</objective>

<quick_start>
The `microworker` CLI follows this pattern:
```bash
microworker <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Run one site's CLI and write its envelope for this run | `microworker discover <SITE>` |
| Merge every site envelope of a run into the task database | `microworker merge <RUN_ID>` |
| Get one site's config.json entry | `microworker sites get <NAME>` |
| List the sites in config.json | `microworker sites list` |
| List merged tasks, most recently seen first | `microworker tasks list` |
| Get one merged task by site and task id | `microworker tasks get <SITE> <TASK_ID>` |
| List recorded merges, most recent first | `microworker runs list` |
| Get one merge with its per-site summaries | `microworker runs get <RUN_ID>` |
| Validate a site envelope against its schema | `microworker validate <FILE>` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `microworker` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `microworker --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **discover** -- Run one site's CLI and write its envelope for this run
- **merge** -- Merge every site envelope of a run into the task database
- **runs** -- Merges recorded in the task database (subcommands: get, list)
- **sites** -- Sites registered in the project's config.json (subcommands: get, list)
- **tasks** -- Tasks merged into the task database (subcommands: get, list)
- **validate** -- Validate a site envelope against its schema
</principle>

<principle name="One Run Id Per Discovery Pass">
Mint one run id (`R=$(date -u +%Y%m%dT%H%M%SZ)`), pass it to every `discover` call, then `merge "$R"`. `merge` requires an envelope for every site in `config.json`, so run `discover` for every name from `microworker sites list --properties name` before merging. Per-run envelopes land under `<project>/agent_workspaces/discovery/<run_id>/` and are disposable.
</principle>

<principle name="The Task Database Is The Durable Output">
`merge` writes no JSON file. It upserts the run's tasks and per-site summaries into `<project>/data/tasks.db` in one transaction, and prints `{"run_id", "db_path", "sites", "task_count", "inserted", "updated"}`. Read the results back with `microworker tasks list|get` and `microworker runs list|get`; do not open the database directly. One row per `(site, task_id)`: re-seeing a task refreshes its fields and `last_seen_at`/`last_seen_run_id` while `first_seen_at`/`first_seen_run_id` stay put. Re-merging the same run id is idempotent.

A query command run before any merge exits 2 naming the database path. That means "nothing has been merged yet", NOT "no tasks are open" -- never report it as an empty result.
</principle>

<principle name="Statuses Are Data, Not Failures">
`discover` exits 0 for every recorded status (`ok`, `auth_failed`, `no_cli`, `no_account`, `error`); read `status` and `error` from its JSON summary or the envelope. Only a `config.json` shape problem or an unknown site exits 2. Never fabricate tasks for a non-`ok` site; the envelope's `tasks` is `[]` by contract.
</principle>

<principle name="Project Root">
The project root is `MICROWORKER_ROOT` when set, else `/Users/adam/Dropbox/GitRepos/Agents/MicroWorker`. Point `MICROWORKER_ROOT` at a scratch directory with its own `config.json` for any rehearsal; do not rehearse against the real project.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`microworker --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
