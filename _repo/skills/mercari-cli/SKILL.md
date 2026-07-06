---
name: mercari-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Mercari operations using the `mercari` CLI tool.
  CLI interface for Mercari.
  Triggers: mercari, mercari cli
---

<objective>
Execute Mercari operations using the `mercari` CLI. All Mercari interactions should use this CLI.
</objective>

<quick_start>
The `mercari` CLI follows this pattern:
```bash
mercari <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Authenticate | `mercari auth login` |
| Check auth | `mercari auth status` |
| Search others' listings | `mercari listings search lego --table --limit 10` |
| Search sold, cheapest first | `mercari listings search lego --status sold --sort price_asc --table` |
| Filter search by condition/price | `mercari listings search lego --condition good --min-price 20 --max-price 100 --table` |
| List active listings | `mercari listings list --status active` |
| List sold listings (table) | `mercari listings list --status complete --table` |
| List inactive listings | `mercari listings list --status inactive --limit 25` |
| Get one listing/item | `mercari listings get m12345678901` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `mercari` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `mercari --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **listings** -- Read and search Mercari listings (read-only):
  - `search <keyword>` -- OTHER sellers' public listings. Options (all validated against the real search API): `--status on_sale|sold`, `--condition new|like_new|good|fair|poor`, `--min-price`/`--max-price` (US dollars), `--sort relevance|price_asc|price_desc`, `--category-id`/`--brand-id` (repeatable), plus `--limit`, `--filter`, `--properties`, `--table`. Each result has `id` + canonical `url`.
  - `list` -- the authenticated seller's OWN listings (by `--status active|inactive|complete`, with `--limit`, `--filter`, `--properties`, `--table`).
  - `get <id>` -- full detail for any listing/item (by id or URL, with `--properties`, `--table`).
- **auth** -- Authentication management (login, logout, status, test) and nested `auth profiles`
- **cache** -- Local response cache management
</principle>

<principle name="Read-Only Scope">
This CLI is read-only. It drives the authenticated Mercari web app and captures its internal GraphQL responses; there are no mutating commands. Login requires an email one-time verification code.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`mercari --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
