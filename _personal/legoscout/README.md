# LegoScout CLI

## DESCRIPTION

LegoScout sources used LEGO bulk lots and set listings across about 20 marketplaces and auction sites, then prices them on resale economics. This CLI owns every piece of that pipeline: the source registry, the canonical deal ledger, set comps and landed cost, the deterministic 0-100 deal score, prospect discovery, and the local deals web page. It finds and prices deals; it never buys, bids, or messages a seller.

## Installation

```bash
cd <cli-tools-root>/_personal/legoscout
uv tool install -e . --force --refresh
```

After installation, the `legoscout` command is available in your terminal.

## Data

The canonical ledger lives at
`/Users/adam/Dropbox/GitRepos/Agents/LegoScout/data/found_deals.db`. Every
canonical path is a constant in `legoscout_cli/paths.py`; nothing else
hardcodes one.

## Quick Start

```bash
legoscout --version
legoscout sources list --table
legoscout deals list --limit 5 --table
legoscout score rescore --dry-run
```

## Commands

### sources

Manage the source registry: which marketplaces the pipeline crawls, and how it
reaches each one.

```bash
# List every registered source
legoscout sources list --table

# Restrict output fields and row count
legoscout sources list --limit 5 --properties namespace,short,status

# Filter the list
legoscout sources list --filter "status:eq:active"

# Get one source, with its learning notes
legoscout sources get ebay --notes --table

# Add a researched source, or emit the template to research
legoscout sources add entry.json --dry-run
legoscout sources add --template mynewsource

# Reverse an add that should not have landed
legoscout sources remove mynewsource

# Read and append per-source learning notes
legoscout sources notes list ebay --table
legoscout sources notes add ebay --text "newest-first sort is _sop=10"

# Check the whole registry for structural problems
legoscout sources validate

# Per-source crawl watermarks
legoscout sources watermarks --table
```

### deals

Read and repair the canonical deal ledger.

```bash
# List deals
legoscout deals list --limit 5 --table
legoscout deals list --filter "status:eq:active" --properties listing_key,score,title

# Get one deal
legoscout deals get "hibid|314234951" --table

# Read one field live off the listing itself, for debugging
legoscout deals read "shopgoodwill|272682584" available_fulfillment

# Re-read one field across the ledger
legoscout deals refresh available_fulfillment --dry-run --limit 3

# Assemble a deal record from a candidate and an appraisal (prints JSON)
legoscout deals build candidate.json appraisal.json

# Validate every stored record
legoscout deals validate --strict

# Set one deal's status
legoscout deals status "ebay|123456789" rejected

# Sweep listings whose auction has already ended
legoscout deals expire --dry-run

# Print the record schema for one pipeline phase
legoscout deals schema crawl

# Replay the stored source-run fixtures
legoscout deals replay
```

### sellers

The per-seller table the ledger joins on, and Adam's favorite flag.

```bash
legoscout sellers list --table
legoscout sellers list --filter "is_favorite:eq:1" --limit 10 --properties source,seller_name
legoscout sellers get shopgoodwill 8 --table
legoscout sellers favorite shopgoodwill 8
legoscout sellers backfill --dry-run
```

### prospects

Prospecting records: new inventory sources, their contacts, outreach, and runs.

```bash
legoscout prospects list --table
legoscout prospects list --filter "status:eq:new" --limit 20 --properties id,name,status
legoscout prospects get 42 --table
legoscout prospects create prospect.json

legoscout prospects contacts list --limit 10 --table
legoscout prospects contacts create contact.json

legoscout prospects outreach list --table
legoscout prospects outreach send 7 --confirm

legoscout prospects runs list --table
legoscout prospects runs create

legoscout prospects hypotheses list --table
legoscout prospects hypotheses get estate_sale_company --table
```

### pricing

Deal economics: fees, landed cost, comps, freight, images, and the pickup area.

```bash
# Published fee configuration for one source
legoscout pricing fees --source shopgoodwill

# Landed cost from a hammer price plus freight
legoscout pricing landed-cost --source shopgoodwill --hammer 100 --shipping 20
legoscout pricing landed-cost --source ebay --hammer 45 --shipping-unknown

# BrickLink sold comps for a set number
legoscout pricing set-sales 10497 --purchase-price 60 --condition used

# A carrier estimate for a listing whose source publishes no rate
legoscout pricing shipping --origin-zip 55340 --weight-lbs 25
legoscout pricing shipping --hibid-lot 314234951 --weight-lbs 25

# Fetch listing images for the vision pass
legoscout pricing images --key "hibid|314234951"

# Resolve a stated location against the drive radius
legoscout pricing pickup-area "Evansville, IN 47725"

# Rebuild the pickup-area table
legoscout pricing rebuild-pickup-area --radius-miles 30

# Discover an AuctionNinja house's published fees
legoscout pricing auctionninja-fees --url https://www.auctionninja.com/example/
```

### score

The deterministic 0-100 deal score. A model reports what it observes; this
decides what that is worth. No model ever picks a point value.

```bash
legoscout score deal "hibid|314234951"
legoscout score rescore --dry-run
legoscout score rescore --apply --limit 50
```

### server

Start and stop the owned local deals server. `start` starts the loopback server,
proves the spawned PID answers its private health gate, opens the deals page,
and prints the URL, PID, and log path as JSON. It reuses a live verified server
that it already owns. It refuses a port answered by another process.

```bash
legoscout server start
legoscout server start --port 8790
legoscout server stop
```

The command stores `server.json` and per-start logs under
`$XDG_DATA_HOME/cli-tools/legoscout/server/`. When `XDG_DATA_HOME` is unset,
the path is `~/.local/share/cli-tools/legoscout/server/`.

### display

The local deals web page, and the rows it renders.

```bash
legoscout display serve --port 8787
legoscout display serve --port 8788 --no-open
legoscout display rows --active-only
```

### triage

Filter, categorize, and optionally detail a batch of raw eBay candidates.

```bash
legoscout triage candidates.json
legoscout triage candidates.json --min-price 25
legoscout triage candidates.json --fetch-details --run-key 20260806T120000Z
```

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output.

Every `list` command accepts `--table/-t`, `--filter/-f`, `--limit/-l` and
`--properties/-p`. Every `get` command accepts `--table/-t`.

Filters use `field:op:value` and are repeatable:

```bash
legoscout deals list --filter "status:eq:active" --filter "score:gt:70"
```

## Library Use

Modules with no command are importable from the tool's own interpreter:

```bash
~/.local/share/uv/tools/legoscout-cli/bin/python -c \
  "from legoscout_cli.ledger import build_record; print(build_record.__doc__)"
```

## Configuration

Non-authentication configuration lives in
`~/.local/share/cli-tools/legoscout/.env`. LegoScout stores no credentials of
its own; the marketplace CLIs it drives own theirs. Reusable credentials belong
in the CLI-tools secret manager (`_repo/_secret-manager/secrets.sh`), never in
a `.env` file.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Client/configuration error |
| 130 | User interrupted (Ctrl+C) |

## Requirements

- Python 3.11+
- The marketplace CLIs the source readers drive (`shopgoodwill`, `ebay`,
  `facebook`, `mercari`, `depop`, `auctionzip`, `stockx`, `bricklink`, ...)
- Dependencies (installed automatically): `cli-tools-shared`, `typer`,
  `python-dotenv`, `jsonschema`

## License

MIT
