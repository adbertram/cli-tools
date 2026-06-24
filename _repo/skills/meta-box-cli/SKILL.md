---
name: meta-box-cli
description: >-
  Execute meta-box operations using the `meta-box` CLI tool.
  CLI interface for MetaBox (browser automation)
  Triggers: meta-box, meta-box cli, meta-box, meta-box cli, meta-box data, my meta-box, meta-box search, list search in meta-box, meta-box auth, list auth in meta-box, meta-box cache, list cache in meta-box
---

<objective>
Execute meta-box operations using the `meta-box` CLI. All meta-box interactions should use this CLI.
</objective>

<quick_start>
The `meta-box` CLI follows this pattern:
```bash
meta-box <command-group> <action> [arguments] [options]
```

| Task | Command |
| --- | --- |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `meta-box` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `meta-box` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **search** -- Search meta-box
- **auth** -- Manage meta-box authentication
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
