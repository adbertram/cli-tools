---
name: dev-to-cli
description: >-
  MANDATORY: Execute dev_to operations using the `dev_to` CLI tool.
  Publish, inspect, and unpublish DEV Community posts through the official
  Forem article API.
  Do not use raw curl or ad hoc HTTP calls when this CLI covers the task.
  Triggers: dev_to, dev_to cli, dev_to posts, dev.to posts, publish to dev.to,
  post to dev.to, create dev.to article, list dev.to posts, get dev.to post,
  unpublish dev.to post, dev.to auth, my dev.to posts
---

<objective>
Execute dev_to operations using the `dev_to` CLI. All dev_to interactions should use this CLI.
</objective>

<quick_start>
The `dev_to` CLI follows this pattern:
```bash
dev_to <command-group> <action> [arguments] [options]
```

| Command | Purpose |
| --- | --- |
| `dev_to posts list --limit 10` | List your DEV articles |
| `dev_to posts get 123456` | Fetch one DEV article by ID |
| `dev_to posts create --title "..." --body-file post.md` | Create a new DEV article |
| `dev_to posts unpublish 123456` | Unpublish a DEV article and return it to draft |
| `dev_to auth status` | Check whether an API key is configured and valid |
| `dev_to auth profiles list` | Inspect saved auth profiles |
| `dev_to cache clear` | Remove cached list/get responses |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `dev_to` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `dev_to` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- `posts` — list, inspect, create, and unpublish DEV Community articles.
- `auth` — login, logout, status checks, tests, and profile management for the API key workflow.
- `cache` — clear cached GET/list responses when you need fresh data.
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
