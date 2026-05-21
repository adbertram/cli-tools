---
name: "facebook-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute facebook operations using the `facebook` CLI tool. Facebook CLI via Playwright browser automation -- Marketplace search, Messenger conversations, Groups posts, and caching. Triggers: facebook, facebook cli, facebook marketplace, facebook messenger, facebook groups, search facebook marketplace, facebook messages, send facebook message, facebook message requests, facebook group posts, read facebook group, list facebook groups"
---

<objective>
Execute facebook operations using the `facebook` CLI. All facebook interactions should use this CLI.
</objective>

<quick_start>
The `facebook` CLI follows this pattern:
```bash
facebook <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Search Marketplace | `facebook marketplace list --query "LEGO" --table` |
| Browse Today's picks | `facebook marketplace list --table` |
| Get listing details | `facebook marketplace get ITEM_ID` |
| List group posts | `facebook groups list GROUP_ID --table` |
| Get a group post | `facebook groups get GROUP_ID/posts/POST_ID` |
| List conversations | `facebook messenger list --table` |
| Read messages | `facebook messenger get CONVERSATION_ID` |
| Send message | `facebook messenger send CONVERSATION_ID --text "Hello"` |
| Check auth status | `facebook auth status` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `facebook` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **groups** — Read posts from Facebook Groups (list, get)
- **marketplace** — Search and browse Facebook Marketplace (list, get with price/location filters)
- **messenger** — Messenger conversations (list, get, send, requests)
- **auth** — Manage authentication via headed browser (login, logout, status, test)
- **auth** -- Authentication commands and nested `auth profiles` management
- **cache** — Manage response cache (clear)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<principle name="Group Comment Verification">
`facebook groups posts comment` and `facebook groups posts reply` perform multi-stage verification after submitting (composer-cleared → comment-count delta → markdown-stripped text-on-page) and return:

- `verification`: `"confirmed"` (any stage fired) or `"render-timeout-likely-success"` (stage 1 fired, stages 2-3 inconclusive — treat as success).
- `verificationDetails.signal`: which stage confirmed (`composer-cleared`, `count-delta`, `text-appeared`, or `composer-cleared-but-no-other-evidence`).
- `verificationDetails.commentCountBefore` / `commentCountAfter`: `[role="article"]` count delta inside the post.

A non-zero exit ONLY happens when all three verification signals fail (true submit failure). Never retry on `render-timeout-likely-success` — duplicate comments are worse than missed verification.

Facebook strips Markdown (`**bold**`, `[label](url)`) when rendering comments — never use raw substring matching against submitted text to verify a comment landed.
</principle>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
