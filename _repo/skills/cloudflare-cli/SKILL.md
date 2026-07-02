---
name: cloudflare-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute cloudflare operations using the `cloudflare` CLI tool.
  CLI interface for Cloudflare API — manage zones, DNS records, cache, IP access rules, and zone traffic analytics.
  Triggers: cloudflare, cloudflare cli, cloudflare dns, cloudflare zones, cloudflare cache, cloudflare access rules, manage dns records, purge cloudflare cache, cloudflare ip rules, block ip cloudflare, cloudflare analytics, zone traffic, page views, top paths
---

<objective>
Execute cloudflare operations using the `cloudflare` CLI. All cloudflare interactions should use this CLI.
</objective>

<quick_start>
The `cloudflare` CLI follows this pattern:
```bash
cloudflare <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List zones | `cloudflare zones list --table` |
| Get zone details | `cloudflare zones get ZONE_ID` |
| List DNS records | `cloudflare dns records list ZONE_ID --table` |
| Create DNS record | `cloudflare dns records create ZONE_ID --type A --name sub.example.com --content 1.2.3.4` |
| Purge cache | `cloudflare cache purge ZONE_ID` |
| List access rules | `cloudflare access-rules list ZONE_ID --table` |
| Block an IP | `cloudflare access-rules create ZONE_ID --target ip --value 1.2.3.4 --mode block` |
| Set Under Attack mode | `cloudflare zones update ZONE_ID --security-level under_attack` |
| Traffic totals for a date range | `cloudflare analytics summary example.com --start 2026-06-01 --end 2026-06-30` |
| Top pages by HTML page views | `cloudflare analytics top-paths example.com --limit 5 --table` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `cloudflare` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** — Manage authentication (login, logout, status, refresh, test)
- **auth** -- Authentication commands and nested `auth profiles` management
- **zones** — Manage Cloudflare zones (list, get, update security settings)
- **cache** — Manage cache (purge all cached content)
- **access-rules** — Manage IP access rules (whitelist, block, challenge IPs/ranges/ASNs/countries)
- **dns** — Manage DNS with sub-groups: `dns zones` (list/get zones) and `dns records` (full CRUD on DNS records)
- **analytics** — Zone traffic analytics via the GraphQL Analytics API: `analytics summary` (totals for a date range) and `analytics top-paths` (top pages by HTML page views). Zone argument accepts a zone name or zone ID. Requires the `Analytics: Read` zone permission on the API token.
</principle>

<principle name="Optional Capability Probes">
`usage.json` is the command contract. If a needed Cloudflare API area is absent from `usage.json` (for example rulesets/header transforms for HSTS discovery), do not run a bare guessed command and let `No such command` fail the workflow. Either report the missing CLI capability and route a deliberate CLI-extension task, or wrap any exploratory `cloudflare <group> --help` probe so expected absence prints an explicit unsupported marker and exits 0. Do not mutate Cloudflare configuration while probing capability.
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
