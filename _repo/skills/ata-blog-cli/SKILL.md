---
name: ata-blog-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute ata-blog operations using the `ata-blog` CLI tool.
  CLI for managing ATA Blog (adamtheautomator.com) -- Notion pages, WordPress posts, WordPress pages, WordPress admin/plugin maintenance, media, categories, tags, Raptive ads, schema, earnings, shoutouts, and live ad-advertiser scanning.
  Triggers: ata-blog, ata blog, adamtheautomator, wordpress post, wordpress page, wordpress admin, plugin updates, update wordpress plugins, edit wordpress page, notion page publish, blog post, blog page, blog media, raptive ads, blog earnings, blog shoutouts, schema markup, scan ads, scan advertisers, what advertisers ran on this post, observed advertisers, include-ads, --include-ads, live ad scan
---

<objective>
Execute ata-blog operations using the `ata-blog` CLI. All ATA Blog interactions should use this CLI.
</objective>

<quick_start>
The `ata-blog` CLI follows this pattern:
```bash
ata-blog <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List Notion pages | `ata-blog notion-page list` |
| Publish Notion page to WordPress | `ata-blog notion-page publish <page_id>` |
| List WordPress posts | `ata-blog wordpress-post list` |
| Get WordPress post fields | `ata-blog wordpress-post get --properties id,title,slug,link,status,modified,content <post_id>` |
| List WordPress pages | `ata-blog wordpress-page list --table` |
| Get page (raw HTML) | `ata-blog wordpress-page get <page_id> --raw` |
| Update page content | `ata-blog wordpress-page update <page_id> --content-file page.html` |
| List WordPress plugins | `ata-blog wordpress-admin plugins list --properties "name,status,version"` |
| Get WordPress plugin | `ata-blog wordpress-admin plugins get <plugin> --properties "name,status,version"` |
| Upgrade WordPress plugin | `ata-blog wordpress-admin plugins upgrade <plugin>` |
| Upload media | `ata-blog media upload <file_path>` |
| Check ad earnings | `ata-blog earnings get` |
| Set schema on post | `ata-blog schema set <post_id> <type>` |
| Check Raptive ad status | `ata-blog raptive status <post_id>` |
| List shoutouts in a post | `ata-blog shoutouts list <post_id>` |
| List shoutouts by sponsor | `ata-blog shoutouts list --sponsor Specops` |
| Scan live advertisers on a post | `ata-blog wordpress-post get --include-ads <post_id>` |
| Scan advertisers on multiple posts | `ata-blog wordpress-post list --include-ads --limit 5` |
</quick_start>

<live_ad_scanning>
`--include-ads` on `wordpress-post get` (single post) or `wordpress-post list` (batch) live-scans the published URL using Playwright + playwright-stealth, extracts advertiser domains from Prebid's `getAllWinningBids()`, and merges them under a top-level `ads` key. Live-only -- no storage, no caching. Every invocation runs a fresh scan.

**Syntax note:** Flags must come BEFORE the post_id positional (typer `allow_interspersed_args=False`):
```bash
ata-blog wordpress-post get --include-ads --ad-checks 3 <post_id>
```

**Key flags:**
| Flag | Default | Meaning |
|------|---------|---------|
| `--include-ads` / `-A` | off | enable the scan |
| `--ad-checks` | 3 | reloads per scan |
| `--ad-interval` | 5 | seconds between reloads |
| `--ad-timeout` | 30 | max seconds per check |

Incompatible with `--table` (JSON only). Scan takes ~20-60s per post depending on `--ad-checks`.

**Output shape** under `ads` -- includes ALL bidders (winners AND losers) with full CPM stats. Each advertiser entry has `won_count`, `appearances`, `bidders`, `min_cpm`, `avg_cpm`, `max_cpm`. Losing bidders (`won_count: 0`) still reveal demand and CPM ranges.

**ATA uses AdThrive/Raptive** which strips `googletag.getResponseInformation`. The scanner installs a pre-page-load hook via `context.add_init_script()` that listens to Prebid's `bidResponse`, `bidWon`, `noBid`, and `bidTimeout` events -- capturing every bidder response, not just the final winners exposed by `getAllWinningBids()`. Works on Raptive-wrapped or GPT-wrapped sites.
</live_ad_scanning>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `ata-blog` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="WordPress Passthrough Constraints">
`ata-blog wordpress-*` commands wrap the repo-owned `wordpress` CLI. For ATA
sitewide ACF option writes, do not use the ACF REST options endpoints when they
return `500 Cannot update item`; follow the `wordpress-cli` skill's ACF options
write guidance and use a server-side WordPress execution path instead.

If a diagnostic task must import WordPress CLI internals, there is no
`wordpress_cli.auth` module. Use the live `wordpress` launcher shebang
interpreter and the actual module documented by the `wordpress-cli` skill.
</principle>

<principle name="Command Groups">
- **auth** -- Authentication management (login, logout, status, refresh, test)
- **auth** -- Authentication commands and nested `auth profiles` management
- **notion-page** -- Notion page management (list, get, publish, update, search, statuses, comments, content)
- **wordpress-post** -- WordPress post CRUD (list, get, create, update, schedule, delete)
- **wordpress-page** -- WordPress page CRUD (list, get, create, update, delete). Passthrough to `wordpress pages`; pages support `parent`, `menu_order`, `template` (no tags/categories/format).
- **wordpress-admin** -- WordPress admin operations, including plugin list/get/activate/deactivate/delete/install/upgrade.
- **media** -- WordPress media management (list, get, upload, delete)
- **categories** -- WordPress categories (list, get, create)
- **tags** -- WordPress tags (list, get, create)
- **raptive** -- Raptive/AdThrive ad settings (disable, enable, status, fields)
- **schema** -- Rank Math schema markup (list, types, set, get, remove)
- **earnings** -- Ad earnings and revenue data (get, list)
- **shoutouts** -- Sponsored shoutouts in posts (list, get, add, remove)
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
