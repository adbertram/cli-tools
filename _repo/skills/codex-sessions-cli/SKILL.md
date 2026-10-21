---
name: codex-sessions-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute codex-sessions operations using the `codex-sessions` CLI tool.
  Query and analyze OpenAI Codex session transcripts across the primary Codex home and all named Codex profiles.
  Triggers: codex-sessions, codex-sessions cli, codex session history, Codex transcripts, Codex sessions, list Codex sessions, search Codex sessions, Codex tool calls, Codex subagents, Codex timeline, Codex todos
---

<objective>
Execute codex-sessions operations using the `codex-sessions` CLI across the primary Codex home and all named profile homes. All Codex transcript inspection should use this CLI.
</objective>

<project_overrides>
Before acting on this skill, run:

```bash
~/.agents/skills/skill-expert/scripts/load-skill-overrides.sh codex-sessions-cli
```

Apply any printed instructions alongside this skill's own workflow: they extend it and
never repeal its limits. No output means no project override is in effect. A non-zero
exit means the project's override file is broken -- report it and stop rather than
silently running unmodified.
</project_overrides>

<quick_start>
The `codex-sessions` CLI follows this pattern:
```bash
codex-sessions <command-group> <action> [arguments] [options]
```

Common commands:

| Task | Command |
|---|---|
| Check the discovered Codex roots | `codex-sessions auth status` |
| List Codex projects | `codex-sessions projects list --limit 20` |
| List recent Codex sessions | `codex-sessions sessions list --limit 20` |
| Search transcript content | `codex-sessions sessions search "query" --limit 20` |
| List tool calls | `codex-sessions tool-calls list --session-id <session-id>` |
| List subagent launches | `codex-sessions subagent-activity list --session-id <session-id>` |
| List update-plan items | `codex-sessions todos list --session-id <session-id>` |
| Show a session timeline | `codex-sessions timeline consolidated --session-id <session-id>` |
</quick_start>

<principles>
<principle name="Root Scope">
Every read command searches the primary Codex home plus named profile homes that
contain `sessions` or `archived_sessions`. `CODEX_SESSIONS_CODEX_PROFILE` scopes
to one profile; `CODEX_SESSIONS_CODEX_HOME` scopes to one explicit root and takes
precedence. A profile-valued `CODEX_HOME` still produces the default all-profile
search. The command-group `--profile` option is a CLI-tools auth profile, not a
Codex profile selector.
</principle>

<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `codex-sessions` command.**
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

<principle name="Normalized Transcript Views">
Session, conversation, tool-call, subagent, todo, skill, and timeline views use
the same normalized transcript model. Function calls, custom tool calls,
tool-search calls, legacy message events, response messages, and
`item_completed` messages must not produce format-specific empty views.

Treat `custom_tool_call` input as an object when supplied as one; otherwise
preserve it as `{"input": <raw>}`. Use `tool_search` when a tool-search payload
has no name. Preserve tool-search `arguments` and include its `execution`
surface when present. A call's own status takes precedence over output status.
Outputs without `call_id` are standalone timeline `tool_result` events, not
parse failures. Non-message `item_completed` items do not become generic
timeline events. Conversation summaries, prompt extraction, and skill mentions
skip injected context such as `AGENTS.md` or environment instructions. A
conversation uses its first meaningful user prompt, falling back to the first
assistant update. Session search applies the same filter to user messages
while retaining assistant messages and tool inputs and outputs.
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
