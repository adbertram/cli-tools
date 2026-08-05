---
name: offerup-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute OfferUp operations using the `offerup` CLI tool.
  Read-only access to the OfferUp local marketplace: search public listings by
  keyword, browse the local feed, and read one listing's full detail record.
  Triggers: offerup, offerup cli, offerup search, offerup listing, offerup local marketplace
---

<objective>
Execute OfferUp operations using the `offerup` CLI. All OfferUp interactions should use this CLI.
</objective>

<quick_start>
The `offerup` CLI follows this pattern:
```bash
offerup <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Configure authentication credentials | `offerup auth login` |
| Clear stored credentials and browser sessions | `offerup auth logout` |
| Create a new profile from .env.example template | `offerup auth profiles create <NAME>` |
| Delete a profile and its data | `offerup auth profiles delete <NAME>` |
| Get details for a specific profile | `offerup auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `offerup auth profiles list` |
| Delete a profile and its data | `offerup auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `offerup auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `offerup auth profiles select <NAME>` |
| Check authentication status across profiles | `offerup auth status` |
| Test authentication by verifying credentials work across profiles | `offerup auth test` |
| Remove all cached responses | `offerup cache clear` |
| Get the full detail record for one listing | `offerup listings get <ITEM>` |
| List the local OfferUp feed with no keyword | `offerup listings list` |
| Search public OfferUp listings by keyword | `offerup listings search <QUERY>` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `offerup` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `offerup --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage offerup authentication (subcommands: login, logout, profiles, status, test)
- **cache** -- Manage response cache (subcommands: clear)
- **listings** -- Search and read OfferUp listings (subcommands: get, list, search)
</principle>
<principle name="No OfferUp Account Is Needed For Reads">
`listings search`, `listings list`, and `listings get` all work on a cold
profile with no OfferUp account; the marketplace feed is public. Do not run
`offerup auth login` or report an auth blocker before a read command has
actually failed. `auth login` exists only to save a signed-in session for
account-scoped work.
</principle>

<principle name="Never Invent A Filter Value">
OfferUp silently ignores an unknown search parameter or an unknown value and
returns the unfiltered baseline instead of an error. The CLI validates every
option against the vocabulary OfferUp publishes and exits non-zero on anything
else, so a rejected value means the value is wrong, not the CLI. Use only:

- `--sort`: `relevance` (default), `newest`, `distance`, `price`. `--desc` is
  valid only with `--sort price`.
- `--condition` (repeatable): `NEW`, `OPEN_BOX`, `REFURBISHED`, `USED`,
  `BROKEN`, `OTHER`.
- `--radius`: `5`, `10`, `20`, `30`, `50` miles.
</principle>

<principle name="Set The Search Location Explicitly">
OfferUp is a local marketplace, and with no coordinates it searches the area it
resolves from the connection's IP address. When the user names a place, pass
`--latitude` and `--longitude`; otherwise say which area the results cover.
</principle>

<principle name="Prices Are Whole-Dollar Strings">
`price` comes back as a string in whole US dollars (`"20"`, not cents and not a
number). Convert before arithmetic or numeric comparison.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`offerup --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
