---
name: tutorials-dojo-cli
description: >-
  Execute tutorials-dojo operations using the `tutorials-dojo` CLI tool.
  CLI interface for TutorialsDojo (browser automation)
  Triggers: tutorials-dojo, tutorials-dojo cli, tutorials-dojo auth, tutorials-dojo search, tutorials-dojo cache, list data in tutorials-dojo, check tutorials-dojo auth, tutorials-dojo profiles
---

<objective>
Execute tutorials-dojo operations using the `tutorials-dojo` CLI. All tutorials-dojo interactions should use this CLI.
</objective>

<quick_start>
The `tutorials-dojo` CLI follows this pattern:
```bash
tutorials-dojo <command-group> <action> [arguments] [options]
```

| Command | Purpose |
|---|---|
| `tutorials-dojo search query` | Search for items on TutorialsDojo |
| `tutorials-dojo search item` | Get details for a specific item |
| `tutorials-dojo search list` | List items from TutorialsDojo |
| `tutorials-dojo search wildcard` | Search items with wildcard pattern matching |
| `tutorials-dojo auth login` | Configure authentication credentials |
| `tutorials-dojo auth logout` | Clear stored credentials and browser sessions |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `tutorials-dojo` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `tutorials-dojo` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **`search`** — Search tutorials-dojo.
- **`auth`** — Manage tutorials-dojo authentication.
- **`cache`** — Manage response cache.
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
