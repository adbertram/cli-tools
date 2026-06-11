---
name: cloudflare-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute cloudflare operations using the `cloudflare` CLI tool.
  CLI interface for Cloudflare API — manage zones, DNS records, cache, and IP access rules.
  Triggers: cloudflare, cloudflare cli, cloudflare dns, cloudflare zones, cloudflare cache, cloudflare access rules, manage dns records, purge cloudflare cache, cloudflare ip rules, block ip cloudflare
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
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `cloudflare` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** — Manage authentication (login, logout, status, refresh, test)
- **auth** -- Authentication commands and nested `auth profiles` management
- **zones** — Manage Cloudflare zones (list, get, update security settings)
- **cache** — Manage cache (purge all cached content)
- **access-rules** — Manage IP access rules (whitelist, block, challenge IPs/ranges/ASNs/countries)
- **dns** — Manage DNS with sub-groups: `dns zones` (list/get zones) and `dns records` (full CRUD on DNS records)
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
