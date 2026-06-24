---
name: progress-servicenow-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute progress-servicenow operations using the `progress-servicenow` CLI tool.
  CLI interface for Progress ServiceNow Employee Center (browser automation).
  Triggers: progress-servicenow, progress-servicenow cli, servicenow tickets, list servicenow tickets, servicenow catalog, search servicenow catalog, servicenow RITM, check servicenow ticket, create servicenow ticket, close servicenow ticket, product list, list products, category list, list categories, draft ticket, create ticket from template
---

<objective>
Execute progress-servicenow operations using the `progress-servicenow` CLI. All progress-servicenow interactions should use this CLI.
</objective>

<quick_start>
The `progress-servicenow` CLI follows this pattern:
```bash
progress-servicenow <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List open tickets | `progress-servicenow ticket list --view open --table` |
| List watchlist tickets | `progress-servicenow ticket list --table` |
| Get ticket details | `progress-servicenow ticket get RITM0352332 --table` |
| Get ticket with comments | `progress-servicenow ticket get RITM0352332 --comments` |
| Comment on ticket | `progress-servicenow ticket comment RITM0352332 "message"` |
| Close a ticket | `progress-servicenow ticket close RITM0352332` |
| Search catalog | `progress-servicenow catalog search "vpn" --table` |
| List IT catalog items | `progress-servicenow catalog list --category it --table` |
| Create ticket (programmatic) | `progress-servicenow ticket create -T development_cloud_issue -F product=Azure -F impact=Low` |
| Create draft ticket | `progress-servicenow ticket create -T development_cloud_issue -F product=Azure --draft` |
| Dry-run validation | `progress-servicenow ticket create -T development_cloud_issue -F product=Azure --dry-run` |
| List product options | `progress-servicenow ticket product list --table` |
| List ticket templates | `progress-servicenow ticket template list --table` |
| Get template fields | `progress-servicenow ticket template fields development_cloud_issue --table` |
| Required fields only | `progress-servicenow ticket template fields purchase_request --required --table` |
| Inspect live form fields | `progress-servicenow ticket form inspect -T request_application_assistance --table` |
| Inspect form by URL | `progress-servicenow ticket form inspect --url "https://progress1.service-now.com/esc?id=sc_cat_item&sys_id=..."` |
| Search Select2 lookup | `progress-servicenow ticket form lookup -T request_application_assistance -f "Please select the application from the list" -s "Copilot"` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `progress-servicenow` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **ticket** -- Manage ServiceNow tickets (list, get, comment, close, create)
- **ticket create** -- Create tickets programmatically with `--template`/`--field`/`--draft`/`--dry-run`
- **ticket product** -- List available Product dropdown options (AJAX-loaded, requires browser)
- **ticket template** -- Ticket form templates, offline, no auth (list, get, fields). **Use BEFORE creating tickets.**
- **catalog** -- Browse the ServiceNow catalog (list, get, search)
- **auth** -- Manage browser-session authentication (login, logout, status, refresh, test)
- **auth** -- Authentication commands and nested `auth profiles` management
- **cache** -- Manage response cache (clear)
</principle>

<principle name="Troubleshooting">
When troubleshooting, ALWAYS run with `DEBUG=1 progress-servicenow ...` for verbose browser-automation output. After any form-interaction failure, capture the page snapshot BEFORE modifying code.
</principle>

<principle name="Ticket Creation Workflow">
Before creating a ticket: (1) list templates to find the right category, (2) check template fields, (3) list product options if the form has a Product dropdown, (4) present options to the user for selection — never assume which category or product is correct.
</principle>

<principle name="Template Selection by Subject">
Pick the template that matches the *subject* of the request, not just any IT form. Key routing rules:

- **Progress-owned products** (Chef, Corticon, OpenEdge, Sitefinity, ShareFile, MarkLogic, Kendo, Telerik, WhatsUp Gold, MOVEit, etc.) — use `development_cloud_issue`, `other_development_request`, `development_machine_issue`, or `development_database_issue` depending on the resource type, and select the Progress product from the `product` dropdown.
- **Non-Progress applications** (Microsoft 365, Microsoft 365 Copilot Studio, Azure, Power Platform, Power BI, GitHub, third-party SaaS, etc.) — use **`request_application_assistance`**. Its `application` field is a Select2 lookup that already contains entries for common non-Progress applications (search it with `ticket form lookup` to find the exact value).
- **No Progress product and no matching application entry** — use `other_development_request` with `product=-- None --` as a last resort, and describe the subject in the Description field.

The `product` dropdown on development templates lists **only Progress-owned products**. It does not include Microsoft, cloud platforms, or third-party apps. Never force-fit an unrelated Progress product (e.g., "Sitefinity") just to satisfy the required field — IT routes tickets partly on the Product value and misrouting delays resolution. When in doubt between `request_application_assistance` and a development template, prefer `request_application_assistance` for anything not developed by Progress.
</principle>

<principle name="Live Field Discovery">
`ticket_template.json` is a static snapshot and may be incomplete — some catalog items have empty `fields: {}` blocks, and live forms can include conditional sections that the offline template doesn't capture. When a template's fields look thin or a ticket needs a lookup value you don't know, use the dedicated subcommands:

```bash
# See the real form fields for a template (or any catalog item URL)
progress-servicenow ticket form inspect -T request_application_assistance --table
progress-servicenow ticket form inspect --url "https://progress1.service-now.com/esc?id=sc_cat_item&sys_id=..."

# Search a Select2/reference field to find valid values
progress-servicenow ticket form lookup \
  -T request_application_assistance \
  -f "Please select the application from the list" \
  -s "Copilot"
```

These commands reuse the existing authenticated browser session — no separate login. `inspect` returns every form field with label, type, required flag, and a snake_case key suggestion; `lookup` returns the Select2 options matching a search term. When discovery reveals fields missing from `ticket_template.json`, update the JSON so future runs don't need to rediscover.
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
