---
name: nextdoor-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute nextdoor operations using the `nextdoor` CLI tool.
  CLI interface for Nextdoor (browser automation) -- feed, For Sale & Free classifieds, notifications, me, and content search.
  Triggers: nextdoor, nextdoor cli, nextdoor feed, nextdoor classifieds, for sale and free, nextdoor listings, nextdoor notifications, nextdoor search, nextdoor login, nextdoor auth profiles, check nextdoor auth
---

<objective>
Execute nextdoor operations using the `nextdoor` CLI. All Nextdoor interactions should use this CLI.
</objective>

<quick_start>
The `nextdoor` CLI exposes top-level data commands plus `auth` and `cache`
subapps:
```bash
nextdoor <command> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check auth status | `nextdoor auth status` |
| Login to Nextdoor | `nextdoor auth login` |
| View feed | `nextdoor feed --limit 25` |
| Browse For Sale & Free listings | `nextdoor classifieds list --limit 25` |
| Keyword-search listings | `nextdoor classifieds list "lego" --limit 25 --filter "type:eq:ORGANIC,title:contains:lego"` |
| Get one listing's full detail | `nextdoor classifieds get <listing-uuid>` |
| Search all Nextdoor content | `nextdoor search "<query>" --limit 25` |
| View notifications | `nextdoor notifications --table` |
| Get current user | `nextdoor me --table` |
| List profiles | `nextdoor auth profiles list` |

All data commands support `--table/-t`, `--properties/-p`, and (except `me`)
`--filter/-f` and `--limit/-l`. `feed` and `classifieds list` also support
`--sort/-s` (`newest` default, `relevance`) and `--desc/-d`.
</quick_start>

<listing_urls>
**Use `classifieds list` when the task needs a verified direct listing URL.**
It is the only command backed by Nextdoor's dedicated For Sale & Free surface,
and every `type: ORGANIC` row returns a real `url`
(`https://nextdoor.com/for_sale_and_free/<uuid>/?init_source=search`) plus
`price`. Sponsored grid slots come back with all listing fields `null` — filter
them out with `--filter "type:eq:ORGANIC"`.

`feed` rows also carry `url`, the post's permalink
(`https://nextdoor.com/p/<slug>?view=detail`). These slugs are opaque and exist
only in the API response — **never construct a Nextdoor URL from an `id`**.
PROMO rows have no permalink and report `url: null`.

The general `feed` mixes classifieds in with neighborhood news at roughly
5-10% of items and has no classified type filter, so do not use it to harvest
listings — use `classifieds list`.
</listing_urls>

<keyword_search_is_not_a_filter>
**`classifieds list <query>` is a relevance signal, not a filter. Never trust
it to restrict results to the keyword.**

The query IS wired through — it is sent verbatim as
`classifiedSearchArgs.query` on Nextdoor's own For Sale & Free search. That is
proven, not assumed: a nonsense token returns zero rows.

```bash
nextdoor classifieds list "zzzzznotarealthing"   # -> 0 rows (query reaches the server)
```

What Nextdoor does with it is the problem. Its classifieds search ranks by
relevance and applies **no relevance floor**, so it pads thin result sets with
unrelated listings instead of returning fewer rows:

| Query | What comes back |
|-------|-----------------|
| `wheelchair` (real local inventory) | "Electric Wheelchair", "Lightweight Transport Wheelchair" — plus "Burgundy Sofa", "Chicago Cubs Office Chair" |
| `lego` / `legos` (no local inventory) | 100% padding: "Vintage Secretary Desk", "New Xbox Series S Bundle", "Everest & Jennings Transport Wheelchair" |

The padding is also unstable: the same keyword returned 2, 3, and 4 rows on
consecutive runs. Nextdoor exposes no exact-match flag and no relevance
threshold on this operation, so there is nothing to turn off.

**Post-filter every keyword search**, and put the conditions in ONE `--filter`:

```bash
nextdoor classifieds list "lego" --limit 50 \
  --filter "type:eq:ORGANIC,title:contains:lego"
```

Repeating `--filter` is **OR**, not AND — `--filter "type:eq:ORGANIC" --filter
"title:contains:lego"` keeps every sponsored-free row regardless of title.
Comma-separated conditions inside a single `--filter` are AND.

A keyword search that returns zero rows after post-filtering is the honest
answer: Nextdoor has no local listing for that term. Do not read the unfiltered
padding as inventory.
</keyword_search_is_not_a_filter>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `nextdoor` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Authentication management (login, status, profiles)
- **classifieds** -- Browse/search the For Sale & Free section (`list`) and read one listing (`get`); direct listing URLs + prices
- **feed** -- View neighborhood feed (posts, classifieds mixed in, sponsored items)
- **me** -- Get current user profile and neighborhood info
- **notifications** -- View recent notifications
- **search** -- Search all Nextdoor content (listings, neighbors, events, businesses, posts)
</principle>

<principle name="Search Returns Sectioned Results">
`nextdoor search` hits Nextdoor's real content search and returns rows from
every section in one list, tagged with `section` (`CLASSIFIED`, `USER`,
`LOCAL_EVENT`, `BUSINESS`, `POST`). Narrow with
`--filter "section:eq:CLASSIFIED"` or `--filter "type:eq:post"`. The upstream
operation accepts no sort or paging arguments, so there is no `--sort`; `--limit`
caps the flattened list.
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
