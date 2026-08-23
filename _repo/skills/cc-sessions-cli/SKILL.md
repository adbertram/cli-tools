---
name: cc-sessions-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute claude-code-sessions operations using the `claude-code-sessions` CLI tool.
  Query and analyze session data from ~/.claude -- projects, sessions, conversations, tool calls, subagents, todos, skills, and timeline.
  Triggers: claude-code-sessions, cc-sessions, session history, tool call history, session data, code session activity, session timeline, subagent history
---

<objective>
Execute claude-code-sessions operations using the `claude-code-sessions` CLI. All session data queries should use this CLI.
</objective>

<quick_start>
The `claude-code-sessions` CLI follows this pattern:
```bash
claude-code-sessions <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List projects | `claude-code-sessions projects list` |
| List sessions | `claude-code-sessions sessions list` |
| Search sessions | `claude-code-sessions sessions search <query>` |
| List tool calls | `claude-code-sessions tool-calls list` |
| View timeline | `claude-code-sessions timeline list` |
| List subagent activity | `claude-code-sessions subagent-activity list` |
| List skill invocations | `claude-code-sessions skills list` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `claude-code-sessions` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Authentication status (login, logout, test, status)
- **projects** -- List and query projects (list, get)
- **sessions** -- List, get, and search sessions (list, get, search)
- **conversations** -- List and view conversations (list, get)
- **subagent-activity** -- Query subagent invocations (list, get)
- **tool-calls** -- Query tool call history (list, get)
- **todos** -- Query todo items (list, get)
- **skills** -- Query skill invocations (list, get)
- **timeline** -- View activity timeline (list, consolidated, get)
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
