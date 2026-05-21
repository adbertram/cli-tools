---
name: "namecheap-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute namecheap operations using the `namecheap` CLI tool. CLI interface for Namecheap (browser automation). Triggers: namecheap, namecheap cli, namecheap, namecheap cli, namecheap auth, namecheap search, namecheap cache, list items in namecheap, search namecheap, namecheap profiles"
---

<objective>
Execute namecheap operations using the `namecheap` CLI. All namecheap interactions should use this CLI.
</objective>

<quick_start>
The `namecheap` CLI follows this pattern:
```bash
namecheap <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check auth status | `namecheap auth status` |
| Login via browser | `namecheap auth login` |
| Test saved session | `namecheap auth test` |
| List auth profiles | `namecheap auth profiles list --table` |
| List scaffolded items | `namecheap search list --table` |
| Search by query | `namecheap search query "term" --table` |
| Get one item | `namecheap search item ITEM_ID` |
| Clear cache | `namecheap cache clear` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `namecheap` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `namecheap` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **auth** -- Manage browser-based Namecheap authentication, session checks, and profiles
- **cache** -- Inspect or clear cached `namecheap` browser-authenticated responses
- **search** -- Query the scaffolded Namecheap search/list/item commands
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
