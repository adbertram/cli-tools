---
name: "pinterest-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute Pinterest operations using the `pinterest` CLI tool. CLI interface for Pinterest API — account, boards, pins, auth, and profile management. Triggers: pinterest, pinterest cli, pinterest account, pinterest boards, pinterest pins, list pinterest boards, get pinterest pin, pinterest auth, pinterest profile, pinterest business account"
---

<objective>
Execute Pinterest operations using the `pinterest` CLI. All Pinterest interactions should use this CLI.
</objective>

<quick_start>
The `pinterest` CLI follows this pattern:
```bash
pinterest <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List the authenticated account | `pinterest account list --table` |
| Get account details | `pinterest account get` |
| List boards | `pinterest boards list --table` |
| Get one board | `pinterest boards get BOARD_ID` |
| List pins | `pinterest pins list --limit 10` |
| Get one pin | `pinterest pins get PIN_ID` |
| Check auth status | `pinterest auth status --table` |
| Create a named auth profile | `pinterest auth profiles create sandbox` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `pinterest` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `pinterest` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **account** — View the authenticated Pinterest account in list or single-object form
- **boards** — List boards and fetch a board by ID
- **pins** — List pins and fetch a pin by ID
- **auth** — Log in, check status, refresh OAuth tokens, test credentials
- **auth profiles** — Create, inspect, switch, list, and delete auth profiles
- **cache** — Clear cached Pinterest API responses for the active profile
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
