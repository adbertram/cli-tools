---
name: auctionzip-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute AuctionZip operations using the `auctionzip` CLI tool.
  Search AuctionZip auction lots and read a lot's full detail (current bid, buyer's premium, close time, status, shipping/pickup terms) through a Cloudflare-cleared browser session. Invaluable-powered; cross-lists with LiveAuctioneers.
  Triggers: auctionzip, auctionzip cli, auctionzip search, auctionzip lot, auctionzip get
---

<objective>
Execute AuctionZip operations using the `auctionzip` CLI. All AuctionZip interactions should use this CLI.
</objective>

<quick_start>
The `auctionzip` CLI follows this pattern:
```bash
auctionzip <command> [arguments] [options]
```

| Task | Command |
|------|---------|
| Authenticate (one-time headed Cloudflare clear) | `auctionzip auth login` |
| Check auth / Cloudflare clearance | `auctionzip auth status` |
| Search lots by keyword | `auctionzip search "lego" --limit 10 --table` |
| Get one lot's full detail | `auctionzip get "<lot-url-or-slug_ref>" --table` |
| Fresh read (bypass cache) | `auctionzip --no-cache get "<lot-url>"` |

**Auth model:** auctionzip.com hard-blocks headless browsers at Cloudflare. `auth login` runs a one-time **headed** pass that mints a `cf_clearance` cookie in the persistent profile; `search`/`get` reuse that session. No AuctionZip account is required to read lots. If a command reports a Cloudflare block, re-run `auctionzip auth login --force`.
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `auctionzip` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `auctionzip --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **search `<query>`** -- Search public AuctionZip lots by keyword. List-style: `--limit/-l`, `--filter/-f`, `--table/-t`, `--properties/-p`. Returns `ref`, `lot_number`, `title`, `auction_house`, `current_bid`, `bids`, `time_remaining`/`close_time`, `estimate`, `url`.
- **get `<lot>`** -- Full detail for one lot by URL, `slug_ref`, or bare ref. `--table/-t`, `--properties/-p`. Returns current bid, bid count, next bid, `buyer_premium`, `status`, `auction_type`, `close_time`, `location`, `accepted_payment`, `shipping_terms`, `conditions_of_sale`, and more.
- **auth** -- Authentication management (login, logout, status, test) and nested `auth profiles`
- **cache** -- Local response cache management
</principle>

<principle name="Point-In-Time Bids">
`current_bid`, `bids`, and `status` are snapshots cached by default. For a live read of the current bid before acting, pass `--no-cache`.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`auctionzip --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
