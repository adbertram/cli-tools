---
name: twopages-cli
description: >-
  MANDATORY: Execute twopages operations using the `twopages` CLI. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. Execute twopages operations using the `twopages` CLI tool.
  Execute twopages operations using the `twopages` CLI. CLI interface for Twopages (browser automation) Triggers: twopages, twopages cli, twopages search, search in twopages, twopages search data, twopages auth, auth in twopages, twopages auth data, twopages cache, cache in twopages
  Triggers: twopages, twopages cli, twopages, twopages cli, twopages search, search in twopages, twopages search data, twopages auth, auth in twopages, twopages auth data, twopages cache, cache in twopages
---

<objective>
Execute twopages operations using the `twopages` CLI. All twopages interactions should use this CLI.
</objective>

<quick_start>
The `twopages` CLI follows this pattern:
```bash
twopages <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check authentication status | `twopages auth status` |
| Log in or refresh credentials | `twopages auth login` |
| List available results | `twopages search list` |
| Run a text query | `twopages search query "term"` |
| Get one result | `twopages search item ITEM_ID` |
| Clear cached responses | `twopages cache clear` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `twopages` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `twopages` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **search** -- Search twopages
- **auth** -- Manage twopages authentication
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
