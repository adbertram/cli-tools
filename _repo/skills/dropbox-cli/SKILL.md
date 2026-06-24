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
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `dropbox` command.**
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

<principle name="Auth Smoke Probes">
Use `dropbox auth status --table` or `dropbox auth test` to verify Dropbox auth.
Do not use `dropbox files info /` as an auth or API smoke probe: Dropbox
`files/get_metadata` does not support root folder metadata. For root content
reachability, use `dropbox files ls /` instead.
</principle>

<principle name="Local Dropbox Folder Files">
For classic local Dropbox paths under `/Users/adam/Dropbox/...`, do not use
macOS `fileproviderctl`; those paths are not File Provider URLs and can return
`NSFileProviderErrorDomain Code=-1005` with `No item for URL`. If a local
Dropbox file is missing, placeholder-only, or needs to be materialized, map the
local path to its Dropbox API path by stripping `/Users/adam/Dropbox`, then use
the Dropbox CLI surface from `usage.json`, typically
`dropbox files get <dropbox_path> <local_path>`.
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
