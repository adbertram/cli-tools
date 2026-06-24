---
name: tenweb-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute tenweb operations using the `tenweb` CLI tool. CLI interface for the 10Web API. Triggers: tenweb, tenweb cli, 10web api, tenweb websites, tenweb website details, tenweb subdomains, tenweb subdomain check, tenweb auth, tenweb cache, 10web websites
---

<objective>
Execute tenweb operations using the `tenweb` CLI. All tenweb interactions should use this CLI.
</objective>

<quick_start>
The `tenweb` CLI follows this pattern:
```bash
tenweb <command-group> <action> [arguments] [options]
```

| Command | Purpose |
|---|---|
| `tenweb websites list` | List websites for the authenticated 10Web account. |
| `tenweb websites get WEBSITE_ID` | Show one 10Web website instance summary by id. |
| `tenweb subdomains check NAME` | Check whether a 10Web subdomain is available. |
| `tenweb auth status` | Inspect authentication state across profiles. |
| `tenweb cache clear` | Remove cached responses for a fresh next read. |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `tenweb` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `tenweb` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- `websites`: List the authenticated 10Web account websites and get one website instance by id.
- `subdomains`: Check whether a candidate 10Web subdomain name is available.
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
