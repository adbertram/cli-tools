---
name: claude-code-sessions-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute claude-code-sessions operations using the `claude-code-sessions` CLI tool.
  Query and analyze Claude Code session transcripts from ~/.claude.
  Triggers: claude-code-sessions, claude-code-sessions cli, claude session history, Claude transcripts, Claude sessions, list Claude sessions, search Claude sessions, Claude tool calls, Claude subagents, Claude timeline, Claude todos
---

<objective>
Execute claude-code-sessions operations using the `claude-code-sessions` CLI. All Claude transcript inspection should use this CLI.
</objective>

<quick_start>
The `claude-code-sessions` CLI follows this pattern:
```bash
claude-code-sessions <command-group> <action> [arguments] [options]
```

Common commands:

| Task | Command |
|---|---|
| Check local Claude transcript access | `claude-code-sessions auth status` |
| List Claude projects | `claude-code-sessions projects list --limit 20` |
| List recent Claude sessions | `claude-code-sessions sessions list --limit 20` |
| Search transcript content | `claude-code-sessions search run "query" --limit 20` |
| List tool calls | `claude-code-sessions tool-calls list --session-id <session-id> --project <project>` |
| List subagent launches | `claude-code-sessions subagent-activity list --session-id <session-id> --project <project>` |
| List update-plan items | `claude-code-sessions todos list --session-id <session-id> --project <project>` |
| Show a session timeline | `claude-code-sessions timeline consolidated --session-id <session-id> --project <project>` |
</quick_start>

<principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `claude-code-sessions` command.**
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
- `projects` — project directories with Claude session rollouts.
- `sessions` — session summaries and details.
- `search` — cross-session transcript search.
- `conversations` — turn-level summaries inside sessions.
- `tool-calls` — Claude tool invocations and outputs.
- `subagent-activity` — subagent launches captured from Task invocations.
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
