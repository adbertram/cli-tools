---
name: "onedrive-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute onedrive operations using the `onedrive` CLI tool. OneDrive for Business CLI via Microsoft Graph API. Triggers: onedrive, onedrive cli, onedrive files, onedrive folders, onedrive drives, list files in onedrive, upload to onedrive, download from onedrive, share onedrive file, onedrive sharing link, my onedrive"
---

<objective>
Execute onedrive operations using the `onedrive` CLI. All onedrive interactions should use this CLI.
</objective>

<quick_start>
The `onedrive` CLI follows this pattern:
```bash
onedrive <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check auth status | `onedrive auth status` |
| List drives | `onedrive drives list --table` |
| List files in folder | `onedrive items list DRIVE_ID /path --table` |
| Get file details | `onedrive items get DRIVE_ID /path/to/file` |
| Upload a file | `onedrive items upload DRIVE_ID ./local.pdf /Remote/path.pdf` |
| Download a file | `onedrive items download DRIVE_ID /Remote/file.pdf ./local.pdf` |
| Create a folder | `onedrive folders create DRIVE_ID "Folder Name"` |
| Share a file | `onedrive link create DRIVE_ID ITEM_ID --scope anonymous` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `onedrive` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage authentication via Azure CLI (login, logout, status)
- **drives** -- Manage OneDrive drives (list, get)
- **folders** -- Manage folders (create, get, create-link, invite)
- **items** -- Manage files and folders (list, get, upload, download, delete)
- **link** -- Manage sharing links (create, list, update, get, delete)
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
