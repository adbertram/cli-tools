---
name: kick-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute kick operations using the `kick` CLI tool.
  CLI interface for Kick accounting/invoicing API -- transactions, categories, workspaces, entities, clients, rule groups, integrations, and statistics.
  Triggers: kick, kick cli, kick transactions, kick accounting, kick invoicing, list kick transactions, kick categories, kick clients, kick statistics, kick rule groups
---

<objective>
Execute kick operations using the `kick` CLI. All Kick accounting/invoicing interactions should use this CLI.
</objective>

<quick_start>
The `kick` CLI follows this pattern:
```bash
kick <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List transactions | `kick transactions list --table` |
| Search transactions | `kick transactions search "invoice" --table` |
| Get transaction details | `kick transactions get TRANSACTION_ID --table` |
| List categories | `kick categories list --table` |
| List clients | `kick clients list --table` |
| Get statistics | `kick statistics get --table` |
| List rule groups | `kick rule-groups list --table` |
| Check auth status | `kick auth status --table` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `kick` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Automate OAuth Before Adam Escalation">
If `kick auth status --profile default` or a read-only command reports
`authenticated: false`, `No refresh token available`, or says to run
`kick auth login`, do not immediately ask Adam to re-authenticate. First load
the `browser-automation` skill and repair the CLI session through the actual Kick
OAuth flow when a non-interrupting browser surface is available.

Before starting OAuth, run `kick auth login --help` and use only the options
shown by the live CLI. Current Kick installs expose `--profile/-p` on
`auth login`, so the default-profile refresh command is
`kick auth login --profile default --force`. If a stale install does not list
`--profile`, select the profile first with `kick auth profiles select default`
and then run `kick auth login --force`; do not pass an unsupported login flag.

Run the selected login command in a PTY/background process with `BROWSER` set to
a task-workspace wrapper that records the URL passed to Python `webbrowser.open`
and exits. Open that captured Auth0 URL with Playwright or the browser surface
selected by `browser-automation`, complete login using the documented
credential/MFA procedures, then submit the full `https://use.kick.co/?code=...`
callback URL to the waiting CLI process. Verify with
`kick auth status --profile default` and
`kick categories list --profile default --limit 1` before continuing.

Do not reconstruct the Auth0 URL in a separate process; PKCE verifier/state must
match the waiting CLI process. Escalate only for a proven CAPTCHA, passkey,
device-push, hardware-key, biometric gate, or an unavailable non-interrupting
browser runtime.
</principle>

<principle name="Command Groups">
- **auth** -- OAuth2 authentication (login, refresh, logout, status)
- **transactions** -- Financial transactions (list, search, get, update)
- **categories** -- Transaction categories (list, get)
- **workspaces** -- Workspace management (list, get)
- **entities** -- Companies/organizations (list, get)
- **statistics** -- Transaction statistics (get)
- **rule-groups** -- Auto-categorization rules (list, get, add, delete, rules)
- **clients** -- Client management (list, get, create)
- **integrations** -- External service integrations (list, get)
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
