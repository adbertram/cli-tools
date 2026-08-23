---
name: x-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute x operations using the `x` CLI tool.
  CLI interface for X API and Developer Console workflows -- post tweets and manage X API credit workflows.
  Triggers: x, x cli, twitter, tweet, post tweet, my tweets, x api, x credits, add credits, send tweet, delete tweet, x timeline
---

<objective>
Execute x operations using the `x` CLI. All X (Twitter) interactions should use this CLI.
</objective>

<quick_start>
The `x` CLI follows this pattern:
```bash
x <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Post a tweet | `x tweet post "Hello World!"` |
| Reply to a tweet | `x tweet post "reply text" --reply-to TWEET_ID` |
| Quote a tweet | `x tweet post "quote text" --quote TWEET_ID` |
| List your tweets | `x tweet list` |
| Get a tweet by ID | `x tweet get TWEET_ID` |
| Delete a tweet | `x tweet delete TWEET_ID` (plain-text success message, not JSON) |
| Preview the current credits purchase | `x credits add 25.00 --dry-run` |
| Purchase credits with the saved browser session | `x credits add 25.00 --profile browser --yes` |
| Check auth status | `x auth status` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `x` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage X authentication profiles. Tweet commands use `AUTH_TYPE=custom`; Developer Console commands use `AUTH_TYPE=browser_session`.
- **credits** -- Purchases X API credits through the saved X Developer Console browser-session profile. Do not switch to Codex's in-app browser, Computer Use, or another visible browser after `x auth login --profile browser --credential-type browser_session`; the saved CLI browser profile is the auth source of truth. Report completion only when `x credits add` returns explicit purchase-success evidence from X. If Stripe checkout requires a new payment card, use the CLI's configured `X_CREDIT_CARD_LASTPASS_ITEM_ID` and billing fields; do not ask Adam for card details until those configured sources are missing or fail.
- **tweet** -- Manage tweets (list, post, get, delete)
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
