---
name: invoicedesk-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Invoicedesk operations using the `invoicedesk` CLI tool.
  CLI interface for Invoicedesk.
  Triggers: invoicedesk, invoicedesk cli
---

<objective>
Execute Invoicedesk operations using the `invoicedesk` CLI. All Invoicedesk interactions should use this CLI.
</objective>

<quick_start>
The `invoicedesk` CLI follows this pattern:
```bash
invoicedesk <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Configure authentication credentials | `invoicedesk auth login` |
| Clear stored credentials | `invoicedesk auth logout` |
| Create a new profile from .env.example template | `invoicedesk auth profiles create <NAME>` |
| Delete a profile and its data | `invoicedesk auth profiles delete <NAME>` |
| Get details for a specific profile | `invoicedesk auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `invoicedesk auth profiles list` |
| Delete a profile and its data | `invoicedesk auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `invoicedesk auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `invoicedesk auth profiles select <NAME>` |
| Check authentication status across profiles | `invoicedesk auth status` |
| Test authentication by verifying credentials work across profiles | `invoicedesk auth test` |
| Remove all cached responses | `invoicedesk cache clear` |
| Create a new customer | `invoicedesk customer create` |
| Find a customer by email address | `invoicedesk customer find <EMAIL>` |
| Get details for a specific customer | `invoicedesk customer get <CUSTOMER_ID>` |
| List all customers/clients | `invoicedesk customer list` |
| Update an existing customer | `invoicedesk customer update <CUSTOMER_ID>` |
| Archive raw pages, details, PDFs and a coverage manifest for every business | `invoicedesk export run` |
| Create a new invoice | `invoicedesk invoice create` |
| Delete/void an invoice | `invoicedesk invoice delete <INVOICE_ID>` |
| Download an invoice as a PDF | `invoicedesk invoice download <INVOICE_ID>` |
| Get details for a specific invoice | `invoicedesk invoice get <INVOICE_ID>` |
| List all invoices | `invoicedesk invoice list` |
| Mark an invoice as paid | `invoicedesk invoice mark-paid <INVOICE_ID>` |
| Record external invoice delivery | `invoicedesk invoice mark-sent <INVOICE_ID>` |
| Update an existing invoice. --line-amount LINEID=AMOUNT sets that line's unit_cost (quantity unchanged) | `invoicedesk invoice update <INVOICE_ID>` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `invoicedesk` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `invoicedesk --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage authentication (subcommands: login, logout, profiles, status, test)
- **cache** -- Manage CLI cache (subcommands: clear)
- **customer** -- Manage customers/clients (subcommands: create, find, get, list, update)
- **export** -- Archive InvoiceDesk data (subcommands: run)
- **invoice** -- Manage invoices (subcommands: create, delete, download, get, list, mark-paid, mark-sent, update)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`invoicedesk --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
