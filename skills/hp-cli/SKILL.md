---
name: hp-cli
description: >-
  MANDATORY: Execute hp operations using the `hp` CLI. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. Execute hp operations using the `hp` CLI tool.
  Execute hp operations using the `hp` CLI. CLI interface for Hp (browser automation) Triggers: hp, hp cli, hp search, search in hp, hp search data, hp auth, auth in hp, hp auth data, hp cache, cache in hp
  Triggers: hp, hp cli, hp, hp cli, hp search, search in hp, hp search data, hp auth, auth in hp, hp auth data, hp cache, cache in hp
---

<objective>
Execute hp operations using the `hp` CLI. All hp interactions should use this CLI.
</objective>

<quick_start>
The `hp` CLI follows this pattern:
```bash
hp <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check authentication status | `hp auth status` |
| Log in or refresh credentials | `hp auth login` |
| List available results | `hp search list` |
| Run a text query | `hp search query "term"` |
| Get one result | `hp search item ITEM_ID` |
| Clear cached responses | `hp cache clear` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `hp` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `hp` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **search** -- Search hp
- **auth** -- Manage hp authentication
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
