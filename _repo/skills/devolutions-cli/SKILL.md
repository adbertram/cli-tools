---
name: devolutions-cli
description: >-
  MANDATORY: Execute devolutions operations using the `devolutions` CLI. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. Execute devolutions operations using the `devolutions` CLI tool.
  Execute devolutions operations using the `devolutions` CLI. CLI interface for Devolutions (browser automation) Triggers: devolutions, devolutions cli, devolutions search, search in devolutions, devolutions search data, devolutions auth, auth in devolutions, devolutions auth data, devolutions cache, cache in devolutions
  Triggers: devolutions, devolutions cli, devolutions, devolutions cli, devolutions search, search in devolutions, devolutions search data, devolutions auth, auth in devolutions, devolutions auth data, devolutions cache, cache in devolutions
---

<objective>
Execute devolutions operations using the `devolutions` CLI. All devolutions interactions should use this CLI.
</objective>

<quick_start>
The `devolutions` CLI follows this pattern:
```bash
devolutions <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check authentication status | `devolutions auth status` |
| Log in or refresh credentials | `devolutions auth login` |
| List available results | `devolutions search list` |
| Run a text query | `devolutions search query "term"` |
| Get one result | `devolutions search item ITEM_ID` |
| Clear cached responses | `devolutions cache clear` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `devolutions` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `devolutions` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **search** -- Search devolutions
- **auth** -- Manage devolutions authentication
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
