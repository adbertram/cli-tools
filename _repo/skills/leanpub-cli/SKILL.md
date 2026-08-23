---
name: leanpub-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Leanpub author API operations using the `leanpub` CLI tool.
  Manage Leanpub API auth profiles and retrieve author revenue, royalties, copies sold, and cache data.
  Triggers: leanpub, leanpub cli, leanpub author stats, leanpub revenue, leanpub royalties, leanpub book stats, leanpub copies sold, my leanpub, leanpub auth, leanpub cache
---

<objective>
Execute Leanpub operations using the `leanpub` CLI. All Leanpub author stats, revenue, royalty, cache, and auth interactions should use this CLI.
</objective>

<quick_start>
The `leanpub` CLI follows this pattern:
```bash
leanpub <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Authenticate | `leanpub auth login` |
| Check auth | `leanpub auth status` |
| List per-book author stats | `leanpub author stats list --slug BOOK_SLUG` |
| Aggregate stats across books | `leanpub author stats get --slug BOOK_SLUG --slug OTHER_SLUG` |
| Use configured books | `leanpub author stats list` |
| Show cache status | `leanpub cache status` |
</quick_start>

<usage_reference>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `leanpub` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- `auth` - Manage Leanpub API key credentials and `auth profiles`.
- `author stats` - Retrieve per-book and aggregate revenue, royalty, and copies-sold stats.
- `cache` - Inspect or clear cached Leanpub responses.
</principle>
</usage_reference>

<reference_index>
**`usage.json`** - Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used after checking `usage.json`
</success_criteria>
