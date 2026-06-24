---
name: measureup-cli
description: >-
  Execute measureup operations using the `measureup` CLI tool.
  CLI interface for the MeasureUp affiliate program
  Triggers: measureup, measureup cli, measureup program info, measureup auth, measureup cache, measureup affiliate program, measureup developer docs, show measureup metadata, check measureup auth
---

<objective>
Execute measureup operations using the `measureup` CLI. All measureup interactions should use this CLI.
</objective>

<quick_start>
The `measureup` CLI follows this pattern:
```bash
measureup <command-group> <action> [arguments] [options]
```

| Command | Purpose |
|---|---|
| `measureup program info` | Show the verified metadata summary for the tool. |
| `measureup auth status` | Inspect authentication state across profiles. |
| `measureup auth login` | Configure or refresh credentials or browser session state. |
| `measureup auth test` | Run the CLI built-in authentication checks. |
| `measureup cache clear` | Remove cached responses for a fresh next read. |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `measureup` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `measureup` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
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
