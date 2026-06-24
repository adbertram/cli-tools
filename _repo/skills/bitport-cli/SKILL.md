---
name: bitport-cli
description: >-
  Execute bitport operations using the `bitport` CLI tool.
  CLI interface for Bitport (browser automation)
  Triggers: bitport, bitport cli, bitport, bitport cli, bitport data, my bitport, bitport search, list search in bitport, bitport auth, list auth in bitport, bitport cache, list cache in bitport
---

<objective>
Execute bitport operations using the `bitport` CLI. All bitport interactions should use this CLI.
</objective>

<quick_start>
The `bitport` CLI follows this pattern:
```bash
bitport <command-group> <action> [arguments] [options]
```

| Task | Command |
| --- | --- |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `bitport` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `bitport` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **search** -- Search bitport
- **auth** -- Manage bitport authentication
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
