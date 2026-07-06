---
name: imessage-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute imessage operations using the `imessage` CLI tool.
  CLI for iMessage on macOS -- read messages, send texts, view conversations, and access contacts.
  Triggers: imessage, imessage cli, send text, send imessage, text message, read messages, my messages, recent texts, imessage conversations, imessage contacts
---

<objective>
Execute imessage operations using the `imessage` CLI. All iMessage interactions should use this CLI.
</objective>

<quick_start>
The `imessage` CLI follows this pattern:
```bash
imessage <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List recent messages | `imessage messages list --table` |
| Messages from a contact | `imessage messages list --contact "+15551234567" --table` |
| Send a text message | `imessage messages send "+15551234567" "Hello!"` |
| List conversations | `imessage conversations list --table` |
| View a conversation | `imessage conversations get CONVERSATION_ID --table` |
| List contacts | `imessage contacts list --table` |
| Check permissions | `imessage auth status --table` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `imessage` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- System permissions check (login, logout, status)
- **contacts** -- macOS Contacts access (list, get)
- **conversations** -- Conversation threads (list, get)
- **messages** -- Read and send messages (list, get, send)
</principle>

<principle name="Sending Requires Interactive Automation Consent">
`imessage messages send` requires macOS Messages **Automation** consent (the
Apple Events / TCC gate, distinct from Full Disk Access). Without it the CLI
fails fast with an actionable error instead of hanging. Sending cannot run under
launchd/cron/headless because there is no automation-consent UI in those
contexts -- use the `google gmail` CLI for unattended notifications.
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
