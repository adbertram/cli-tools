---
name: dropbox-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute Dropbox operations using the `dropbox` CLI tool.
  CLI interface for Dropbox API — manage files, folders, sharing, and account info.
  Triggers: dropbox, dropbox cli, dropbox files, dropbox folders, dropbox sharing,
  list files in dropbox, dropbox search, dropbox download, dropbox upload, files in dropbox
---

<objective>
Execute Dropbox operations using the `dropbox` CLI. All Dropbox interactions should use this CLI.
</objective>

<quick_start>
The `dropbox` CLI follows this pattern:
```bash
dropbox <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List files in a directory | `dropbox files ls /Documents` |
| List with details | `dropbox files ls -l /Photos` |
| Search for files | `dropbox files search "report"` |
| Download a file | `dropbox files get /path/to/file.pdf` |
| Upload a file | `dropbox files put ./local.pdf /Dropbox/path.pdf` |
| Check recent changes | `dropbox files changes --after yesterday` |
| View file history | `dropbox files history /path/to/file` |
| Check storage usage | `dropbox account usage` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `dropbox` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** — Login, logout, check status, refresh tokens, test credentials
- **auth** -- Authentication commands and nested `auth profiles` management
- **files** — List, upload, download, move, copy, delete, search, history, restore
- **folders** — Restore deleted folders and contents
- **account** — View account info and storage usage
- **sharing** — Inspect, list, and download shared links/folders
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
