---
name: ebay-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute ebay operations using the `ebay` CLI tool.
  eBay CLI -- seller tools, marketplace categories, and account management.
  Triggers: ebay, ebay cli, ebay orders, ebay inventory, ebay listings, list ebay orders, create ebay listing, ebay shipping, ebay messages, ebay seller, ebay categories, ebay policies
---

<objective>
Execute ebay operations using the `ebay` CLI. All ebay interactions should use this CLI.
</objective>

<quick_start>
The `ebay` CLI follows this pattern:
```bash
ebay <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check current user | `ebay whoami --table` |
| List orders | `ebay seller orders list --table` |
| Get order details | `ebay seller orders get ORDER_ID` |
| List inventory | `ebay seller inventory list --table` |
| Create listing | `ebay seller listings create --sku SKU ...` |
| Publish listing | `ebay seller listings publish OFFER_ID` |
| Upload image | `ebay seller images upload FILE_PATH` |
| List messages | `ebay seller messages list --table` |
| Search categories | `ebay categories list "keyword"` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `ebay` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Structure">
Top-level (admin/agnostic):
- **whoami** — Display current user details and scopes
- **auth** — Manage eBay API authentication (OAuth)
- **auth** -- Authentication commands and nested `auth profiles` management
- **categories** — Search and browse marketplace categories

Under `ebay seller`:
- **orders** — View orders and fulfillment details
- **shipping-labels** — Create, void, and download shipping labels
- **shipping-quote** — Get shipping rate quotes
- **inventory** — Manage inventory items (SKUs)
- **listings** — Manage listings lifecycle (create, publish, unpublish, delete)
- **templates** — Manage listing templates
- **policies** — Manage fulfillment (shipping) policies
- **payment-policies** — View payment policies
- **return-policies** — View return policies
- **images** — Upload and manage listing images
- **locations** — Manage merchant/inventory locations
- **messages** — Manage seller messages and buyer inquiries
- **store** — Manage eBay store settings
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
