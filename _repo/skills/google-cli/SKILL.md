---
name: google-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute google operations using the `google` CLI tool.
  CLI interface for Google Workspace APIs -- Gmail, Calendar, Drive, Docs, Sheets, Search Console, Analytics (GA4), and Cloud.
  Triggers: google, google cli, google workspace, gmail, google calendar, google drive, google docs, google sheets, search console, google analytics, GA4, analytics report, top pages, traffic sources, realtime users, send email with google, list google drive files, read google doc, google cloud
---

<objective>
Execute google operations using the `google` CLI. All Google Workspace interactions should use this CLI.
</objective>

<quick_start>
The `google` CLI follows this pattern:
```bash
google <service> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List Gmail inbox | `google gmail list --table` |
| Send an email | `google gmail send --to "user@example.com" --subject "Hi" --body "Hello"` |
| Search Gmail | `google gmail search "from:boss subject:urgent" --table` |
| List today's calendar events | `google calendar today --table` |
| List Drive files | `google drive list --table` |
| Search Drive | `google drive search "quarterly report" --table` |
| Read a Google Doc | `google docs read DOCUMENT_ID` |
| Read a Google Sheet | `google sheets read SPREADSHEET_ID --range "Sheet1!A1:D10" --table` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `google` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- OAuth2 authentication (login, status, logout)
- **calendar** -- Google Calendar events (list, get, search, today)
- **cloud** -- Google Cloud resources (projects, credentials)
- **docs** -- Google Docs (list, get, read, create, export, update, tables)
- **drive** -- Google Drive files (list, get, search, download)
- **gmail** -- Gmail messages (list, get, read, search, send, archive, draft, reply, reply-all, labels, download-attachment)
- **searchconsole** -- Search Console (index, sites, urls)
- **sheets** -- Google Sheets (list, get, read, create, append, update)
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
