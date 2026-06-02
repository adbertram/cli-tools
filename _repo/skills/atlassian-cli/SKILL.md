---
name: "atlassian-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute atlassian operations using the `atlassian` CLI tool. CLI interface for Atlassian (browser automation). Triggers: atlassian, atlassian cli, atlassian, atlassian cli, atlassian auth, atlassian search, atlassian cache, list items in atlassian, search atlassian, atlassian profiles"
---

<objective>
Execute atlassian operations using the `atlassian` CLI. All atlassian interactions should use this CLI.
</objective>

<quick_start>
The `atlassian` CLI follows this pattern:
```bash
atlassian <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check auth status | `atlassian auth status` |
| Login via browser | `atlassian auth login` |
| Test saved session | `atlassian auth test` |
| List auth profiles | `atlassian auth profiles list --table` |
| List scaffolded items | `atlassian search list --table` |
| Search by query | `atlassian search query "term" --table` |
| Get one item | `atlassian search item ITEM_ID` |
| Clear cache | `atlassian cache clear` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `atlassian` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `atlassian` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **auth** -- Manage browser-based Atlassian authentication, session checks, and profiles
- **cache** -- Inspect or clear cached `atlassian` browser-authenticated responses
- **search** -- Query the scaffolded Atlassian search/list/item commands
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
