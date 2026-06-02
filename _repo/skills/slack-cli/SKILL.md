---
name: "slack-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute slack operations using the `slack` CLI tool. CLI interface for Slack API \u2014 messages, channels, DMs, files, notifications, users, canvases, and reminders. Triggers: slack, slack cli, slack messages, slack channels, send slack message, slack DMs, slack files, slack notifications, slack users, slack reminders, slack canvas, read slack, search slack"
---

<objective>
Execute slack operations using the `slack` CLI. All slack interactions should use this CLI.
</objective>

<quick_start>
The `slack` CLI follows this pattern:
```bash
slack <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Send a message | `slack messages send CHANNEL_ID "Hello!"` |
| Reply in thread | `slack messages send CHANNEL_ID "Reply" --thread-ts TS` |
| List channels | `slack channels list --table` |
| Read channel messages | `slack messages list CHANNEL_ID --table` |
| Search messages | `slack messages search "query" --table` |
| Send a DM | `slack dm send @user "Hello!"` |
| Read DMs | `slack dm read @user --table` |
| Check notifications | `slack notifications list --table` |
| Upload a file | `slack files upload file.pdf --channels CHANNEL_ID` |
| List users | `slack users list --table` |
| Set your profile photo | `slack users set-photo avatar.png` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `slack` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** — Manage Slack API authentication (login, logout, status, refresh, test)
- **cache** — Manage CLI response cache
- **canvas** — Manage Slack canvases (list, get content)
- **channels** — Manage channels (list, get, create, archive, join, leave, members)
- **dm** — Direct messages (list, get, send, read history)
- **files** — Manage files (list, upload, get, delete, download)
- **messages** — Messages (send, get, list, search, delete, mentions, threads)
- **notifications** — View notifications (get, counts, list, summary)
- **auth** -- Authentication commands and nested `auth profiles` management
- **users** — Manage users (list, get, set-status, set-photo)
- **reminders** — Reminders and saved items/Later (list, get, complete, new, delete)
</principle>

<principle name="Slack mrkdwn">
Slack uses mrkdwn, not standard markdown. Bold = `*text*` (single asterisk). Links = `<url|text>`. Always use mrkdwn when composing messages.
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

## Known Issues

### 1. Browser Auth Can Stop at Slack CAPTCHA After Clearing a Profile
**Symptom:** `slack auth login --force` opens Slack sign-in, reaches reCAPTCHA, and if the process is interrupted before successful login the target profile can be left with empty `ACCESS_TOKEN` and `REFRESH_TOKEN` values. `slack auth test` then reports missing credentials or `invalid_auth`.

**Cause:** The forced login flow clears saved Slack credentials before launching the browser. Slack may require a human reCAPTCHA, so an interrupted login can leave the profile in the cleared state.

**Fix:** Prefer accepting invites and completing Slack sign-in in a dedicated browser profile first. Then create a dedicated Slack CLI profile, save the authenticated browser session's `xoxc` token and `d` cookie into that profile, and verify it with `slack --profile <profile> --no-cache auth test --table`. If an existing profile was cleared and no saved `d` cookie is available, complete `slack --profile <profile> auth login` through the CAPTCHA flow instead of relying on the access token alone.

**Verification:** Run `slack --profile <profile> --no-cache auth test --table` and confirm the intended team and user show `api_test: passed`.

**Recurrence Prevention:** Before using `--force`, confirm the active profile and avoid interrupting the browser login after credentials have been cleared. For invite flows, use a new profile name so existing workspace profiles are not disturbed.
