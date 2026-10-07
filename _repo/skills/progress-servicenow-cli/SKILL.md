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
| Create ticket (programmatic) | `progress-servicenow ticket create -T other_development_request -F product=Sitefinity -F req_impact=Low -F description="..."` |
| Create draft ticket | `progress-servicenow ticket create -T other_development_request -F product=Sitefinity -F req_impact=Low -F description="..." --draft` |
| Dry-run validation | `progress-servicenow ticket create -T other_development_request -F product=Sitefinity -F req_impact=Low -F description="..." --dry-run` |
| List product options (live) | `progress-servicenow ticket product list --table` |
| List ticket templates | `progress-servicenow ticket template list --table` |
| Get template fields | `progress-servicenow ticket template fields other_development_request --table` |
| Required fields only | `progress-servicenow ticket template fields purchase_request --required --table` |
| Refresh template registry from live catalog | `progress-servicenow ticket template refresh --table` |
| Inspect live form fields | `progress-servicenow ticket form inspect -T application_assistance_issue_reporting --table` |
| Inspect form by URL | `progress-servicenow ticket form inspect --url "https://progress1.service-now.com/esc?id=sc_cat_item&sys_id=..."` |
| Search Select2 lookup | `progress-servicenow ticket form lookup -T application_assistance_issue_reporting -f "Please select the application from the list" -s "Copilot"` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `progress-servicenow` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **ticket** -- Manage ServiceNow tickets (list, get, comment, close, create)
- **ticket create** -- Create tickets programmatically with `--template`/`--field`/`--draft`/`--dry-run`
- **ticket product** -- List available Product dropdown options from the live catalog item via the authenticated Service Catalog API (requires browser session; fails loudly instead of returning an empty list)
- **ticket template** -- Ticket form templates from the packaged registry (list, get, fields are offline, no auth). **Use BEFORE creating tickets.** `template refresh` re-resolves every registry entry against the live catalog (requires browser session) and must be re-run whenever a catalog item is renamed, retired, or a template's fields look stale/thin.
- **catalog** -- Browse the ServiceNow catalog (list, get, search)
- **auth** -- Manage browser-session authentication (login, logout, status, test) plus nested `auth profiles` management
- **cache** -- Manage response cache (clear)
</principle>

<principle name="Expired Session Recovery">
ServiceNow here sits behind Progress Entra SSO, so a stale browser session makes
every ServiceNow URL redirect to `login.microsoftonline.com`. Every ticket and
catalog command detects that and **fails with a non-zero exit** and the message
`Not authenticated: ServiceNow redirected to the SSO login page ...`. It never
returns an empty list and never reports sign-in page text as ticket data — treat
any such error as "refresh the session", not "no results".

Recover it with `progress-servicenow auth login` (add `--force` to discard the
profile and sign in from scratch). That is fully non-interactive: the password
comes from the managed `lastpass` CLI and the MFA code from the `imessage` CLI
when Entra asks for Authenticator approval. Do not ask Adam for the password, do
not open a browser by hand, and do not run `playwright-cli` against this site —
the CLI owns the session. Only escalate when the CLI itself reports that Entra
offered no code-based factor.
</principle>

<principle name="Troubleshooting">
When troubleshooting, ALWAYS run with `DEBUG=1 progress-servicenow ...` for verbose browser-automation output. After any form-interaction failure, capture the page snapshot BEFORE modifying code.
</principle>

<principle name="Ticket Creation Workflow">
Before creating a ticket: (1) list templates to find the right category, (2) check template fields, (3) list product options if the form has a Product dropdown, (4) present options to the user for selection — never assume which category or product is correct.
</principle>

<principle name="Template Selection by Subject">
Pick the template that matches the *subject* of the request, not just any IT form. Registry keys are derived from the live catalog item's display name (run `ticket template list --table` for the current, authoritative set — do not assume a key from memory or from an older session, since ServiceNow renames or retires catalog items and `ticket template refresh` regenerates keys to match). Key routing rules, current as of the last `ticket template refresh`:

- **Progress-owned products** (Chef, Corticon, OpenEdge, Sitefinity, ShareFile, MarkLogic, Kendo, Telerik, WhatsUp Gold, MOVEit, etc.) — use `other_development_request` (general dev requests; select the Progress product from the `product` dropdown) or `development_database_request` (new/reconfigured dev database or client installs).
- **Non-Progress applications** (Microsoft 365, Microsoft 365 Copilot Studio, Azure, Power Platform, Power BI, GitHub, third-party SaaS, etc.) — use **`application_assistance_issue_reporting`**. Its `cmdb_ci` field ("Please select the application from the list") is a reference lookup that already contains entries for common non-Progress applications (search it with `ticket form lookup` to find the exact value).
- **No Progress product and no matching application entry** — use `other_development_request` with `product=-- None --` as a last resort, and describe the subject in the Description field.

The `product` dropdown on `other_development_request` lists **only Progress-owned products** (confirm the current list with `ticket product list --table`, which reads it live). It does not include Microsoft, cloud platforms, or third-party apps. Never force-fit an unrelated Progress product (e.g., "Sitefinity") just to satisfy the required field — IT routes tickets partly on the Product value and misrouting delays resolution. When in doubt between `application_assistance_issue_reporting` and a development template, prefer `application_assistance_issue_reporting` for anything not developed by Progress.
</principle>

<principle name="Live Field Discovery">
`ticket_template.json` is a registry rebuilt from the live Service Catalog API (`ticket template refresh`), but it can still go stale between refreshes if ServiceNow changes a form. When a template's fields look thin or a ticket needs a lookup value you don't know, use the dedicated subcommands instead of guessing:

```bash
# See the real form fields for a template (or any catalog item URL)
progress-servicenow ticket form inspect -T application_assistance_issue_reporting --table
progress-servicenow ticket form inspect --url "https://progress1.service-now.com/esc?id=sc_cat_item&sys_id=..."

# Search a Select2/reference field to find valid values
progress-servicenow ticket form lookup \
  -T application_assistance_issue_reporting \
  -f "Please select the application from the list" \
  -s "Copilot"
```

Both commands resolve the catalog item through its registered `sys_id` (or, when a template has none, through an exact live-name match against the Service Catalog API) — never by scraping the Employee Center search page, whose results render inside shadow DOM and are invisible to DOM locators. These commands reuse the existing authenticated browser session — no separate login. `inspect` returns every form field with label, type, required flag, and a snake_case key suggestion; `lookup` returns the Select2 options matching a search term. When discovery reveals fields missing from `ticket_template.json`, run `ticket template refresh` (or hand-add the field) so future runs don't need to rediscover.
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
