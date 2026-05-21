---
name: "raptive-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute raptive operations using the `raptive` CLI tool. CLI interface for Raptive traffic and revenue data. Triggers: raptive, raptive cli, raptive earnings, raptive traffic, ad revenue, raptive dashboard, raptive RPM, earnings by page, traffic sources, ad network earnings"
---

<objective>
Execute raptive operations using the `raptive` CLI. All raptive interactions should use this CLI.
</objective>

<quick_start>
The `raptive` CLI follows this pattern:
```bash
raptive <command-group> <action> [options]
```

| Task | Command |
|------|---------|
| Dashboard summary | `raptive dashboard summary --period last7d --table` |
| Daily earnings | `raptive earnings overview --period last7d --table` |
| Earnings by page | `raptive earnings by-page --limit 20 --table` |
| Earnings by device | `raptive earnings by-device --table` |
| Earnings by source | `raptive earnings by-traffic-source --table` |
| Traffic sources | `raptive traffic sources --table` |
| Ad network earnings | `raptive earnings sources --table` |
| Clear cache | `raptive cache clear` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `raptive` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **dashboard** -- View dashboard metrics and summaries (summary, date-bounds)
- **earnings** -- View earnings/revenue data (overview, by-device, by-page, by-traffic-source, by-country, by-category, brand-safety, sources)
- **traffic** -- View traffic/session data (sources, by-device)
- **cache** -- Manage response cache (clear)
- **auth** -- Manage authentication (login, logout, status, refresh, test)
- **auth** -- Authentication commands and nested `auth profiles` management
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
