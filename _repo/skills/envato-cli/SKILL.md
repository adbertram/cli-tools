---
name: envato-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Envato Market operations using the `envato` CLI tool.
  Read-only Envato Market API client -- search CodeCanyon, ThemeForest, and other Envato sites and read item sales counts, ratings, prices, and update dates.
  Triggers: envato, envato cli, codecanyon, themeforest, envato market, codecanyon sales, codecanyon search
---

<objective>
Execute Envato Market operations using the `envato` CLI. All Envato interactions should use this CLI.
</objective>

<quick_start>
The `envato` CLI follows this pattern:
```bash
envato <command> [arguments] [options]
envato <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Configure authentication credentials | `envato auth login` |
| Clear stored credentials | `envato auth logout` |
| Create a new profile from .env.example template | `envato auth profiles create <NAME>` |
| Delete a profile and its data | `envato auth profiles delete <NAME>` |
| Get details for a specific profile | `envato auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `envato auth profiles list` |
| Delete a profile and its data | `envato auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `envato auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `envato auth profiles select <NAME>` |
| Check authentication status across profiles | `envato auth status` |
| Test authentication by verifying credentials work across profiles | `envato auth test` |
| Remove all cached responses | `envato cache clear` |
| Get a single Envato marketplace item by ID | `envato item <ITEM_ID>` |
| Search Envato marketplace items by keyword (CodeCanyon, newest first) | `envato search "<TERM>"` |
| Best sellers for a keyword | `envato search "<TERM>" --sort sales --desc --limit 50` |
| Search another Envato site | `envato search "<TERM>" --site themeforest` |
| Next page of results | `envato search "<TERM>" --page 2` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `envato` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `envato --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage envato authentication (subcommands: login, logout, profiles, status, test)
- **cache** -- Manage response cache (subcommands: clear)
- **item** -- Top-level command (not a group). Gets one Envato marketplace item by numeric ID and prints one JSON object. An unknown ID exits 1 with `HTTP 404: Item not found with that ID`.
- **search** -- Top-level command (not a group). Searches one Envato site by keyword and prints a JSON array. `--site`, `--sort`/`--desc`, `--page`, and `--limit` are sent to Envato's search API; `--filter`/`--properties`/`--table` apply to the returned page.
</principle>

<principle name="Envato output and option values">
- `search` and `item` return the same record shape: `id`, `title`, `url`, `price` (US dollars), `number_of_sales`, `rating` (0.0 when unrated), `rating_count`, `published_at`, `updated_at`, `site`.
- `--site`: `codecanyon` (default), `themeforest`, `videohive`, `audiojungle`, `graphicriver`, `photodune`, `3docean`, or the `.net` domain form.
- `--sort`: `newest` (default), `updated`, `price`, `sales`, `rating`, `relevance`. `newest`/`updated` are newest-first; `price`/`sales`/`rating` are low-to-high; `--desc` reverses the direction and is rejected with `relevance`. For demand research, use `--sort sales --desc`.
- `--limit` is the API page size (1-100, default 20); `--page` is 1-60. To read more than 100 results, request further pages.
- Auth uses the personal token stored in the CLI-tools secret manager as `envato-api-token`. `envato auth status` reports the account `username` from a live API call.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`envato --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
