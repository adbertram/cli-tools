---
name: "freshbooks-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute freshbooks operations using the `freshbooks` CLI tool. CLI interface for FreshBooks accounting API -- manage invoices and customers. Triggers: freshbooks, freshbooks cli, freshbooks invoices, freshbooks customers, create invoice, send invoice, freshbooks billing, unpaid invoices, freshbooks accounting"
---

<objective>
Execute freshbooks operations using the `freshbooks` CLI. All freshbooks interactions should use this CLI.
</objective>

<quick_start>
The `freshbooks` CLI follows this pattern:
```bash
freshbooks <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List invoices | `freshbooks invoice list --table` |
| List unpaid invoices | `freshbooks invoice list --unpaid --table` |
| Create invoice | `freshbooks invoice create -c CUSTOMER_ID -d "Consulting" -a 500.00` |
| Send invoice | `freshbooks invoice send INVOICE_ID` |
| Download PDF | `freshbooks invoice download INVOICE_ID` |
| Mark paid | `freshbooks invoice mark-paid INVOICE_ID -a 500.00` |
| List customers | `freshbooks customer list --table` |
| Find customer | `freshbooks customer find email@example.com` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `freshbooks` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Domain-Agnostic Wrapper">
**This skill does NOT contain per-client invoicing knowledge** (PO requirements, payment terms, line-item grouping rules, billing addresses, product-to-group mappings).

Per-client behavior belongs to the project that owns that customer relationship — not here. Callers translate their per-client rules into `freshbooks` CLI args before invocation. Keep this skill a thin, domain-agnostic CLI wrapper.
</principle>

<principle name="Command Groups">
- **auth** — Manage authentication via OAuth2 (login, logout, status)
- **invoice** — Full invoice lifecycle (list, get, create, send, update, mark-paid, delete, download)
- **customer** — Manage customers/clients (list, get, find, create, update)
- **auth** -- Authentication commands and nested `auth profiles` management
</principle>

<principle name="Approval Before Sending">
**NEVER send invoices without explicit human approval. This is ABSOLUTE.**

Workflow for any invoice:
1. **CREATE** as draft (`freshbooks invoice create …`)
2. **PRESENT** the draft (customer, line items, total, due date, any client-specific fields like PO / terms)
3. **ASK** explicitly: "Would you like me to send this invoice?"
4. **WAIT** for unambiguous approval ("yes, send it" / "approved" / "send the invoice" / "proceed with sending")
5. **SEND** only after approval (`freshbooks invoice send INVOICE_ID`)

NOT approval: "create and send an invoice" (only approves creation), "handle the invoicing", "invoice the client", "looks good", or any ambiguous response.

Never use `-F` / force-send flags. Never batch-send multiple invoices on one approval — each invoice needs its own.
</principle>
</essential_principles>

<reference_index>
- **`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
- No invoice sent without explicit approval
</success_criteria>
