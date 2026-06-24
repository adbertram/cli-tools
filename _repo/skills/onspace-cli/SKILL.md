---
name: onspace-cli
description: >-
  MANDATORY: Execute onspace operations using the `onspace` CLI. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. Execute onspace operations using the `onspace` CLI tool.
  Execute onspace operations using the `onspace` CLI. CLI interface for Onspace (browser automation) Triggers: onspace, onspace cli, onspace search, search in onspace, onspace search data, onspace auth, auth in onspace, onspace auth data, onspace cache, cache in onspace
  Triggers: onspace, onspace cli, onspace, onspace cli, onspace search, search in onspace, onspace search data, onspace auth, auth in onspace, onspace auth data, onspace cache, cache in onspace
---

<objective>
Execute onspace operations using the `onspace` CLI. All onspace interactions should use this CLI.
</objective>

<quick_start>
The `onspace` CLI follows this pattern:
```bash
onspace <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check authentication status | `onspace auth status` |
| Log in or refresh credentials | `onspace auth login` |
| List available results | `onspace search list` |
| Run a text query | `onspace search query "term"` |
| Get one result | `onspace search item ITEM_ID` |
| Clear cached responses | `onspace cache clear` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `onspace` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `onspace` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **search** -- Search onspace
- **auth** -- Manage onspace authentication
- **cache** -- Manage response cache
</principle>
</essential_principles>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
