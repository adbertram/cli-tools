---
name: google-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute google operations using the `google` CLI tool.
  CLI interface for Google Workspace APIs -- Gmail, Calendar, Contacts, Drive, Docs, Sheets, Search Console, Analytics (GA4), and Cloud.
  Triggers: google, google cli, google workspace, gmail, google calendar, google contacts, google drive, google docs, google sheets, search console, google analytics, GA4, analytics report, top pages, traffic sources, realtime users, send email with google, list google drive files, read google doc, google cloud
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
| Read a Gmail message body | `google gmail read MESSAGE_ID` |
| Get Gmail metadata with decoded body | `google gmail get MESSAGE_ID --include-body` |
| List Gmail filters | `google gmail filters list --table` |
| Create a Gmail filter | `google gmail filters create --from "news@example.com" --remove-label INBOX` |
| List today's calendar events | `google calendar today --table` |
| List contacts | `google contacts list --table` |
| List Drive files | `google drive list --table` |
| Search Drive | `google drive search "quarterly report" --table` |
| Read a Google Doc | `google docs read DOCUMENT_ID` |
| Read a Google Sheet | `google sheets read SPREADSHEET_ID --range "A1:D10" --table` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `google` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- OAuth2 authentication (login, status, logout)
- **calendar** -- Google Calendar events (list, get, search, today)
- **cloud** -- Google Cloud resources (projects, credentials)
- **contacts** -- Google Contacts through the People API (list, get)
- **docs** -- Google Docs (list, get, read, create, export, update, tables)
- **drive** -- Google Drive files (list, get, search, download)
- **gmail** -- Gmail messages (list, get, read, search, send, archive, draft, reply, reply-all, labels, filters, download-attachment)
- **searchconsole** -- Search Console (index, sites, urls)
- **sheets** -- Google Sheets (list, get, read, create, append, update)
</principle>

<principle name="Sheets Range Selection">
For newly imported workbooks, do not assume the first tab is named `Sheet1`.
Use unqualified A1 ranges such as `A1:D10` for first-sheet reads, or run
`google sheets get SPREADSHEET_ID` and use the exact
`.sheets[].properties.title` value before passing a sheet-qualified range such
as `TabName!A1:D10`.
</principle>

<principle name="Gmail Search Output Contract">
`google gmail search` returns JSON array output by default, including `[]` for
zero results. `--properties` accepts comma-separated or repeated fields from:
`id`, `name`, `from`, `to`, `subject`, `date`, `threadId`, `labelIds`, `attachments`.
Invalid fields fail clearly instead of returning blank objects.
</principle>

<principle name="Gmail Body Reads">
For link inspection, unsubscribe/source-stop work, or any task that needs full
message text, use `google gmail read MESSAGE_ID`. Use
`google gmail get MESSAGE_ID --include-body` only when metadata and decoded body
are both needed. Do not use `--properties` with `google gmail get`; `get`
supports `--table`, `--raw`, `--include-body`, and `--profile`.
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
