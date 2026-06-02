---
name: techsmith-cli
description: >-
  Execute techsmith operations using the `techsmith` CLI tool.
  CLI interface for Techsmith (browser automation)
  Triggers: techsmith, techsmith cli, techsmith, techsmith cli, techsmith data, my techsmith, techsmith search, list search in techsmith, techsmith auth, list auth in techsmith, techsmith cache, list cache in techsmith
---

<objective>
Execute techsmith operations using the `techsmith` CLI. All techsmith interactions should use this CLI.
</objective>

<quick_start>
The `techsmith` CLI follows this pattern:
```bash
techsmith <command-group> <action> [arguments] [options]
```

| Task | Command |
| --- | --- |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `techsmith` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `techsmith` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **search** -- Search techsmith
- **auth** -- Manage techsmith authentication
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
