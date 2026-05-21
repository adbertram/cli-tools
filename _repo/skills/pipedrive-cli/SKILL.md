---
name: "pipedrive-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute pipedrive operations using the `pipedrive` CLI tool. CLI interface for Pipedrive (browser automation). Triggers: pipedrive, pipedrive cli, pipedrive, pipedrive cli, pipedrive auth, pipedrive search, pipedrive cache, list items in pipedrive, search pipedrive, pipedrive profiles"
---

<objective>
Execute pipedrive operations using the `pipedrive` CLI. All pipedrive interactions should use this CLI.
</objective>

<quick_start>
The `pipedrive` CLI follows this pattern:
```bash
pipedrive <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check auth status | `pipedrive auth status` |
| Login via browser | `pipedrive auth login` |
| Test saved session | `pipedrive auth test` |
| List auth profiles | `pipedrive auth profiles list --table` |
| List scaffolded items | `pipedrive search list --table` |
| Search by query | `pipedrive search query "term" --table` |
| Get one item | `pipedrive search item ITEM_ID` |
| Clear cache | `pipedrive cache clear` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `pipedrive` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `pipedrive` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **auth** -- Manage browser-based Pipedrive authentication, session checks, and profiles
- **cache** -- Inspect or clear cached `pipedrive` browser-authenticated responses
- **search** -- Query the scaffolded Pipedrive search/list/item commands
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
