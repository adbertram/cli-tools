---
name: "clickbank-cli"
description: "MANDATORY: Use this skill for ALL ClickBank service operations. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. Execute clickbank operations using the `clickbank` CLI tool. CLI interface for ClickBank: REST API (orders, products, quickstats) plus the public affiliate marketplace (search and discover products to promote). Triggers: clickbank, clickbank cli, clickbank orders, clickbank products, clickbank quickstats, clickbank marketplace, clickbank search marketplace, find clickbank products to promote, clickbank affiliate products, clickbank gravity, clickbank hoplink, clickbank vendor, list clickbank orders, get clickbank receipt, create clickbank product, delete clickbank product, clickbank auth, clickbank affiliate"
---

<objective>
Execute clickbank operations using the `clickbank` CLI. All ClickBank interactions -- both the REST API surface (orders, products, quickstats) and the affiliate marketplace surface -- should use this CLI.
</objective>

<quick_start>
The `clickbank` CLI follows this pattern:
```bash
clickbank <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List recent orders | `clickbank orders list --limit 10 --table` |
| Fetch one receipt | `clickbank orders get 6X5W8DF2` |
| Count sale transactions | `clickbank orders count --filter "type:eq:SALE"` |
| List products for a site | `clickbank products list --site mysite --table` |
| Create a product | `clickbank products create ABC123 --param site=mysite --param currency=USD --param language=EN --param price=49.95 --param title=Example --param digital=true --param categories=EBOOK --param pitchPage=https://example.com/pitch --param thankYouPage=https://example.com/thanks` |
| List quickstats | `clickbank quickstats list --filter "account:eq:mysite" --table` |
| Browse marketplace categories | `clickbank marketplace categories --flat --table` |
| Find products to promote | `clickbank marketplace search --category 'Health & Fitness' --recurring --sort gravity --table` |
| Keyword-search the marketplace | `clickbank marketplace search --query keto --min-gravity 20 --table` |
| Look up one marketplace product | `clickbank marketplace product BRAINSONGX --table` |
| Build an affiliate hoplink offline | `clickbank marketplace hoplink BRAINSONGX` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `clickbank` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `clickbank` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of treating it as ordinary data output.
</principle>

<principle name="Marketplace Browser Session">
The `marketplace` command group talks to ClickBank's private GraphQL endpoint via a persistent Playwright session. Before the first `marketplace` call in a fresh environment, run `clickbank auth login --credential-type browser_session` to boot the session (the marketplace is public, so you do not have to sign in; dismiss any cookie banner and press Enter when prompted). The `hoplink` subcommand is offline and works without the session.
</principle>

<principle name="Command Groups">
- **orders** -- order lookup, reporting, counts, and upsell inspection (REST API)
- **products** -- product lookup, listing, creation, and deletion of YOUR ClickBank products (REST API)
- **quickstats** -- account quickstats lists, single-account reads, and totals (REST API)
- **marketplace** -- search the public affiliate marketplace to discover products to promote (browser-driven GraphQL)
- **auth** -- API key login, browser-session login, status, logout, tests, and profile management
- **cache** -- cached response maintenance
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
