---
name: appy-pie-cli
description: >-
  Execute appy-pie operations using the `appy-pie` CLI tool.
  CLI interface for the AppyPie affiliate program
  Triggers: appy-pie, appy-pie cli, appy-pie program info, appy-pie auth, appy-pie cache, appy-pie affiliate program, appy-pie developer docs, show appy-pie metadata, check appy-pie auth
---

<objective>
Execute appy-pie operations using the `appy-pie` CLI. All appy-pie interactions should use this CLI.
</objective>

<quick_start>
The `appy-pie` CLI follows this pattern:
```bash
appy-pie <command-group> <action> [arguments] [options]
```

| Command | Purpose |
|---|---|
| `appy-pie program info` | Show the verified metadata summary for the tool. |
| `appy-pie auth status` | Inspect authentication state across profiles. |
| `appy-pie auth login` | Configure or refresh credentials or browser session state. |
| `appy-pie auth test` | Run the CLI built-in authentication checks. |
| `appy-pie cache clear` | Remove cached responses for a fresh next read. |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `appy-pie` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `appy-pie` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- `program`: Show the verified metadata for the affiliate program or developer platform behind this CLI.
- `auth`: Configure credentials, check status, run auth tests, and manage profiles.
- `cache`: Clear cached responses when you need fresh reads.
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
