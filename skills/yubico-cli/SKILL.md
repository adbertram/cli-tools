---
name: yubico-cli
description: >-
  Execute yubico operations using the `yubico` CLI tool.
  CLI interface for Yubico (browser automation)
  Triggers: yubico, yubico cli, yubico, yubico cli, yubico data, my yubico, yubico search, list search in yubico, yubico auth, list auth in yubico, yubico cache, list cache in yubico
---

<objective>
Execute yubico operations using the `yubico` CLI. All yubico interactions should use this CLI.
</objective>

<quick_start>
The `yubico` CLI follows this pattern:
```bash
yubico <command-group> <action> [arguments] [options]
```

| Task | Command |
| --- | --- |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `yubico` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `yubico` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **search** -- Search yubico
- **auth** -- Manage yubico authentication
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
