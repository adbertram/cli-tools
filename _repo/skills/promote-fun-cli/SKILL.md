---
name: promote-fun-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute PromoteFun operations using the `promote-fun` CLI tool.
  CLI interface for PromoteFun.
  Triggers: promote-fun, promote-fun cli
---

<objective>
Execute PromoteFun operations using the `promote-fun` CLI. All PromoteFun interactions should use this CLI.
</objective>

<quick_start>
The `promote-fun` CLI follows this pattern:
```bash
promote-fun <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Configure authentication credentials | `promote-fun auth login` |
| Clear stored credentials and browser sessions | `promote-fun auth logout` |
| Create a new profile from .env.example template | `promote-fun auth profiles create <NAME>` |
| Delete a profile and its data | `promote-fun auth profiles delete <NAME>` |
| Get details for a specific profile | `promote-fun auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `promote-fun auth profiles list` |
| Delete a profile and its data | `promote-fun auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `promote-fun auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `promote-fun auth profiles select <NAME>` |
| Seed an empty shared Chromium profile from this CLI's default profile | `promote-fun auth seed-shared-chromium-profile` |
| Check authentication status across profiles | `promote-fun auth status` |
| Remove all cached responses | `promote-fun cache clear` |
| Read native public detail, including explicit rulesAccess gates | `promote-fun campaigns get <CAMPAIGN_ID>` |
| List public campaigns with server pagination; missing view floors stay missing | `promote-fun campaigns list` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `promote-fun` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `promote-fun --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage promote-fun authentication (subcommands: login, logout, profiles, seed-shared-chromium-profile, status)
- **cache** -- Manage response cache (subcommands: clear)
- **campaigns** -- Read public campaigns without signing in (subcommands: get, list)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`promote-fun --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
