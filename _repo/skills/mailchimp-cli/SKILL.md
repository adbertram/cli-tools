---
name: "mailchimp-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute mailchimp operations using the `mailchimp` CLI tool. CLI interface for Mailchimp API -- manage audiences, subscribers, campaigns, templates, and sponsor-domain detection. Triggers: mailchimp, mailchimp cli, mailchimp campaign, mailchimp subscribers, mailchimp audience, list mailchimp campaigns, send mailchimp email, mailchimp members, mailchimp templates, search mailchimp subscribers"
---

<objective>
Execute mailchimp operations using the `mailchimp` CLI. All mailchimp interactions should use this CLI.
</objective>

<quick_start>
The `mailchimp` CLI follows this pattern:
```bash
mailchimp <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check auth status | `mailchimp auth status` |
| List audiences | `mailchimp audiences list --table` |
| List subscribers | `mailchimp members list LIST_ID --table` |
| Search subscriber | `mailchimp members search user@example.com` |
| Add subscriber | `mailchimp members add LIST_ID --email user@example.com` |
| List campaigns | `mailchimp campaigns list --table` |
| Get campaign report | `mailchimp campaigns report CAMPAIGN_ID --table` |
| Detect sponsor domain | `mailchimp campaigns report CAMPAIGN_ID --sponsor-domain specopssoft.com` |
| Pause RSS campaign | `mailchimp campaigns pause CAMPAIGN_ID` |
| Resume RSS campaign | `mailchimp campaigns resume CAMPAIGN_ID` |
| List templates | `mailchimp templates list --table` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `mailchimp` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage Mailchimp API authentication (login, logout, status)
- **audiences** -- Manage audiences/lists (list, get, create)
- **members** -- Manage subscribers (list, get, add, update, remove, search)
- **campaigns** -- Manage email campaigns (list, get, create, send, pause, resume, report, content, children)
- **templates** -- Manage email templates (list, get)
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
