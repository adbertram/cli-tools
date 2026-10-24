---
name: dataforseo-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute DataForSEO operations using the `dataforseo` CLI tool.
  Keyword research via the DataForSEO API: Google monthly search volume, keyword difficulty, related keyword ideas with volume/difficulty/CPC/intent, and account balance.
  Triggers: dataforseo, dataforseo cli, keyword research, keyword search volume, keyword difficulty, keyword ideas, related keywords, dataforseo balance, dataforseo cost
---

<objective>
Execute DataForSEO operations using the `dataforseo` CLI. All DataForSEO interactions should use this CLI.
</objective>

<quick_start>
The `dataforseo` CLI follows this pattern:
```bash
dataforseo <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Remaining account funds (free call) | `dataforseo account balance` |
| Configure authentication credentials | `dataforseo auth login` |
| Clear stored credentials | `dataforseo auth logout` |
| Create a new profile from .env.example template | `dataforseo auth profiles create <NAME>` |
| Delete a profile and its data | `dataforseo auth profiles delete <NAME>` |
| Get details for a specific profile | `dataforseo auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `dataforseo auth profiles list` |
| Delete a profile and its data | `dataforseo auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `dataforseo auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `dataforseo auth profiles select <NAME>` |
| Check authentication status across profiles | `dataforseo auth status` |
| Test authentication by verifying credentials work across profiles | `dataforseo auth test` |
| Remove all cached responses | `dataforseo cache clear` |
| Keyword difficulty, 0-100 (DataForSEO Labs bulk keyword difficulty, live) | `dataforseo keywords difficulty <KEYWORDS>` |
| Related keyword ideas with volume, difficulty, CPC and search intent (DataForSEO Labs, live) | `dataforseo keywords ideas <SEEDS>` |
| Monthly Google search volume, competition, CPC and monthly trend (Google Ads, live) | `dataforseo keywords volume <KEYWORDS>` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `dataforseo` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `dataforseo --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Cost And Budget">
Paid commands spend account funds on every call. The per-call cost is printed to stderr as `cost: $<usd>`. Check funds first with the free `dataforseo account balance`.
- `keywords volume`: about $0.09 per request (up to 1000 keywords).
- `keywords difficulty` and `keywords ideas`: $0.012 per request plus $0.00012 per returned result.
- `keywords ideas --limit 1 <keyword>` returns that keyword's own volume, difficulty, CPC and intent for about $0.012, so prefer it over `volume` when one keyword is scored.
Batch many keywords into one call instead of one call per keyword. Results are cached for an hour (`cost: $0 (cached result)`); use `--no-cache` before the subcommand to force a fresh paid call.
</principle>

<principle name="Defaults And Output">
- Location defaults to United States (`--location-code 2840`), language to English (`--language-code en`).
- JSON on stdout is the full API record. Select fields with `--properties`, using dot-notation for nested fields, for example `keyword,keyword_info.search_volume,keyword_properties.keyword_difficulty,keyword_info.cpc,search_intent_info.main_intent`.
- `keywords ideas --filter` uses API field paths (`keyword_info.search_volume:gte:100,keyword_properties.keyword_difficulty:lt:40`); commas are AND, and a second `--filter` flag is rejected.
- Any non-20000 DataForSEO status fails with the API status message. Status 40104 means the account is not verified yet (paid calls blocked); only the account owner can fix it in the DataForSEO user panel.
</principle>

<principle name="Command Groups">
- **account** -- DataForSEO account balance and limits (subcommands: balance)
- **auth** -- Manage dataforseo authentication (subcommands: login, logout, profiles, status, test)
- **cache** -- Manage response cache (subcommands: clear)
- **keywords** -- Keyword research: search volume, difficulty, ideas (subcommands: difficulty, ideas, volume)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`dataforseo --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
