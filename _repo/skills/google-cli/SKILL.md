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
| Preview a Gmail email for approval | `google gmail send --to "user@example.com" --subject "Hi" --body "Hello"` |
| Search Gmail | `google gmail search "from:boss subject:urgent" --table` |
| Read a Gmail message body | `google gmail read MESSAGE_ID` |
| Get Gmail metadata with decoded body | `google gmail get MESSAGE_ID --include-body` |
| Create a Gmail draft | `google gmail draft --to "user@example.com" --subject "Hi" --body "Hello"` |
| Inspect a Gmail draft | `google gmail draft-get DRAFT_ID --include-body` |
| Delete a Gmail draft | `google gmail draft-delete DRAFT_ID --confirm` |
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
- **gmail** -- Gmail messages (list, get, read, search, send, archive, trash, draft, draft-get, draft-delete, send-draft, reply, reply-all, labels, filters, download-attachment)
- **searchconsole** -- Search Console (index, sites, urls)
- **sheets** -- Google Sheets (list, get, read, create, append, update)
</principle>

<principle name="Authentication Profile Resolution">
Google profile names are CLI-managed identifiers, not Google account email
addresses. Before passing `--profile`, run `google auth profiles list` and use
an exact existing `.name`; use `google auth status --profile PROFILE` when the
authenticated account must be verified. For normal commands, omit `--profile`
to use the active profile. Never derive a profile name or profile directory
from an email address.
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

<principle name="Gmail Label Reads">
`google gmail labels list MESSAGE_ID` lists labels on one Gmail message; it is
not a global label directory and `MESSAGE_ID` is required. Its JSON root is an
object with `.message_id` and a `.labels` array, so parse `.labels[]` after
verifying `.labels` is an array. Do not pipe that output to `jq '.[] | ...'`.
For a known label id, use `google gmail labels get LABEL_ID`.
</principle>

<principle name="Gmail Draft IDs">
`google gmail draft` returns `id` as the Gmail draft ID (usually beginning with
`r...`) and `message_id` as the underlying message ID. Follow-up draft
inspection, sending, and deletion must use the draft ID with `google gmail
draft-get DRAFT_ID`, `google gmail send-draft DRAFT_ID`, or `google gmail
draft-delete DRAFT_ID`. Do not use `google gmail get MESSAGE_ID` or `google
gmail search` to inspect draft headers; the messages API can omit draft-only
headers such as To and Subject, and deleted/sent drafts can return Gmail 404 for
the old message ID.

Only the draft ID is stable. A draft's underlying `message_id` can change
between reads because Gmail re-materializes the draft's message, so never cache
it or address a draft by it. Delete a draft with `google gmail draft-delete
DRAFT_ID` (`--confirm`/`-y` to skip the prompt), which calls Gmail's
`users.drafts.delete`. Do not use `google gmail trash MESSAGE_ID` on a draft:
that calls `users.messages.modify` on an unstable message ID, returns
intermittent Gmail 404s, and does not remove the draft. Reserve `google gmail
trash` for real (non-draft) messages.
</principle>

<principle name="Gmail Send Approval Guard">
`google gmail send` without `--confirm` is the required preview step. Passing
`--confirm` is the explicit approval boundary and sends the message, including
from non-interactive automation. Workflow: preview without `--confirm` when a
review step is needed, then rerun the same command with `--confirm` after
approval.
</principle>

<principle name="Google Contacts Filters And Properties">
`google contacts list --filter` uses normalized Contacts CLI fields. The
filterable fields are case-sensitive and exact:
`displayName`, `etag`, `familyName`, `givenName`, `organization`,
`primaryEmail`, `primaryPhone`, `resourceName`, `title`. Do not filter on
`name`; use `displayName`, `givenName`, or `familyName`.

`google contacts list --properties` and `google contacts get --properties`
also project normalized output fields, not People API `personFields` groups. Use
fields such as `resourceName`, `displayName`, `givenName`, `familyName`,
`primaryEmail`, `emailAddresses`, `primaryPhone`, `phoneNumbers`,
`organization`, `title`, `organizations`, `addresses`, and `urls`. Do not
request `names`; request the normalized name fields instead.
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
