---
name: easyship-cli
description: >-
  MANDATORY: Execute easyship operations using the `easyship` CLI. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. Execute easyship operations using the `easyship` CLI tool.
  Execute easyship operations using the `easyship` CLI. CLI interface for Easyship API Triggers: easyship, easyship cli, easyship account, account in easyship, easyship account data, easyship couriers, couriers in easyship, easyship couriers data, easyship auth, auth in easyship
  Triggers: easyship, easyship cli, easyship, easyship cli, easyship account, account in easyship, easyship account data, easyship couriers, couriers in easyship, easyship couriers data, easyship auth, auth in easyship
---

<objective>
Execute easyship operations using the `easyship` CLI. All easyship interactions should use this CLI.
</objective>

<quick_start>
The `easyship` CLI follows this pattern:
```bash
easyship <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check authentication status | `easyship auth status` |
| Log in or refresh credentials | `easyship auth login` |
| List couriers | `easyship couriers list` |
| Get a courier | `easyship couriers get COURIER_ID` |
| List the authenticated account | `easyship account list` |
| Get the authenticated account | `easyship account get` |
| Clear cached responses | `easyship cache clear` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `easyship` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `easyship` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **account** -- Inspect the authenticated Easyship account
- **couriers** -- List and inspect active couriers
- **auth** -- Manage easyship authentication
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
