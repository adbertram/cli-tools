---
name: clipster-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Clipster operations using the `clipster` CLI tool.
  Read Clipster's public, unauthenticated clipping campaign catalog.
  Triggers: clipster, clipster cli, clipster campaigns, clipping campaign catalog, clipster discover
---

<objective>
Execute Clipster operations using the `clipster` CLI. All Clipster interactions should use this CLI.
</objective>

<quick_start>
The `clipster` CLI follows this pattern:
```bash
clipster <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List campaigns (default 100, follows pages up to the limit) | `clipster campaigns list` |
| List the whole catalog (about 113 rows) | `clipster campaigns list --limit 200` |
| List the first few as a table | `clipster campaigns list --limit 10 --table` |
| Pick fields only | `clipster campaigns list --properties id,name,status,web_url` |
| Filter rows read within the limit | `clipster campaigns list --filter "status:eq:CAMPAIGN_STATUS_ACTIVE"` |
| Get one campaign by id | `clipster campaigns get <CAMPAIGN_ID>` |
| Get one campaign as a field/value table | `clipster campaigns get <CAMPAIGN_ID> --table` |
| Fresh read, skipping the 5-minute cache | `clipster --no-cache campaigns list --limit 200` |
| Clear cached reads | `clipster cache clear` |

Every row is exactly what Clipster's API returns, plus `web_url` (`https://www.clipster.gg/discover?openedCampaignId=<id>`). No login: the catalog is public. `campaigns get` reads the catalog and errors when the id is absent.
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `clipster` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `clipster --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **cache** -- Manage response cache (subcommands: clear)
- **campaigns** -- Read Clipster campaigns (subcommands: get, list)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`clipster --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
