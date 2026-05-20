---
name: popai-cli
description: >-
  MANDATORY: Execute popai operations using the `popai` CLI. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. Execute popai operations using the `popai` CLI tool.
  Execute popai operations using the `popai` CLI. CLI interface for Popai (browser automation) Triggers: popai, popai cli, popai search, search in popai, popai search data, popai auth, auth in popai, popai auth data, popai cache, cache in popai
  Triggers: popai, popai cli, popai, popai cli, popai search, search in popai, popai search data, popai auth, auth in popai, popai auth data, popai cache, cache in popai
---

<objective>
Execute popai operations using the `popai` CLI. All popai interactions should use this CLI.
</objective>

<quick_start>
The `popai` CLI follows this pattern:
```bash
popai <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check authentication status | `popai auth status` |
| Log in or refresh credentials | `popai auth login` |
| List available results | `popai search list` |
| Run a text query | `popai search query "term"` |
| Get one result | `popai search item ITEM_ID` |
| Clear cached responses | `popai cache clear` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `popai` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `popai` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **search** -- Search popai
- **auth** -- Manage popai authentication
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
