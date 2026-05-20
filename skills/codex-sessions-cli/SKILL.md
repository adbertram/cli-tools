---
name: codex-sessions-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute codex-sessions operations using the `codex-sessions` CLI tool.
  Query and analyze OpenAI Codex session transcripts from ~/.codex.
  Triggers: codex-sessions, codex-sessions cli, codex session history, Codex transcripts, Codex sessions, list Codex sessions, search Codex sessions, Codex tool calls, Codex subagents, Codex timeline, Codex todos
---

<objective>
Execute codex-sessions operations using the `codex-sessions` CLI. All Codex transcript inspection should use this CLI.
</objective>

<quick_start>
The `codex-sessions` CLI follows this pattern:
```bash
codex-sessions <command-group> <action> [arguments] [options]
```

Common commands:

| Task | Command |
|---|---|
| Check local Codex transcript access | `codex-sessions auth status` |
| List Codex projects | `codex-sessions projects list --limit 20` |
| List recent Codex sessions | `codex-sessions sessions list --limit 20` |
| Search transcript content | `codex-sessions sessions search "query" --limit 20` |
| List tool calls | `codex-sessions tool-calls list --session-id <session-id>` |
| List subagent launches | `codex-sessions subagent-activity list --session-id <session-id>` |
| List update-plan items | `codex-sessions todos list --session-id <session-id>` |
| Show a session timeline | `codex-sessions timeline consolidated --session-id <session-id>` |
</quick_start>

<principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `codex-sessions` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Output">
Use JSON output by default for automation. Add `--table`/`-t` only when the user asks for a readable table.
</principle>

<principle name="Filtering">
List commands use `--filter`/`-f` with `field:op:value` syntax and `--properties` for field projection. Prefer `--project`, `--project-path`, `--session-id`/`-S`, and `--since`/`-s` before broad scans when the user gives scope.
</principle>

<principle name="Command Groups">
- `auth` — local transcript access checks; no real login is required.
- `projects` — project directories with Codex session rollouts.
- `sessions` — session summaries, details, and transcript search.
- `conversations` — turn-level summaries inside sessions.
- `tool-calls` — Codex tool invocations and outputs.
- `subagent-activity` — subagent launches captured from `spawn_agent`/`Task`.
- `todos` — `update_plan` items captured in transcripts.
- `skills` — `$skill` or `@agent` mentions in user prompts.
- `timeline` — chronological event streams for one or more sessions.
</principle>
</principles>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against `usage.json`
</success_criteria>
