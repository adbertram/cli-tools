---
name: "photos-app-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute photos-app operations using the `photos-app` CLI tool. Query and export photos from macOS Photos library. Triggers: photos-app, photos-app cli, photos app, list photos, download photos, export photos, photo albums, my photos, photos library, enhance photos, add photos to album"
---

<objective>
Execute photos-app operations using the `photos-app` CLI. All macOS Photos library interactions should use this CLI.
</objective>

<quick_start>
The `photos-app` CLI follows this pattern:
```bash
photos-app <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List recent photos | `photos-app photos list --limit 10 --table` |
| List photos by date | `photos-app photos list --from 2024-01-01 --to 2024-12-31` |
| List photos in album | `photos-app photos list --album "Vacation"` |
| Download photos | `photos-app photos download ~/Desktop/export --album "Album"` |
| Count photos | `photos-app photos count` |
| List albums | `photos-app albums list --table` |
| Create album | `photos-app albums create "New Album"` |
| Auto-enhance album | `photos-app albums enhance "Album Name"` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `photos-app` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **photos** -- List and download photos (list, get, download, count)
- **albums** -- List and create albums (open, list, get, create, delete, move, enhance, add-photos)
- **auth** -- Manage authentication (login, logout, status, refresh, test)
- **auth** -- Authentication commands and nested `auth profiles` management
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
