---
name: x-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute x operations using the `x` CLI tool.
  CLI interface for X API -- post and manage tweets.
  Triggers: x, x cli, twitter, tweet, post tweet, my tweets, x api, send tweet, delete tweet, x timeline
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
| Delete a tweet | `x tweet delete TWEET_ID` |
| Check auth status | `x auth status` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `x` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage X API OAuth 1.0a authentication (login, logout, status)
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
