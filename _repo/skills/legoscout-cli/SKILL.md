---
name: legoscout-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Legoscout operations using the `legoscout` CLI tool.
  CLI interface for Legoscout.
  Triggers: legoscout, legoscout cli
---

<objective>
Execute Legoscout operations using the `legoscout` CLI. All Legoscout interactions should use this CLI.
</objective>

<quick_start>
The `legoscout` CLI follows this pattern:
```bash
legoscout <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| FULL pre-run gate: verify every deal-run dependency before any worker starts | `legoscout pricing preflight [--source <NS>]...` |
| Assemble one ledger-ready record | `legoscout deals build <CANDIDATE> <APPRAISAL>` |
| Resolve every active listing to available/unavailable/blocked | `legoscout deals expire` |
| Get one deal record | `legoscout deals get <LISTING_KEY>` |
| List deals, newest score first | `legoscout deals list` |
| Read ONE field live off the listing itself, for debugging | `legoscout deals read <LISTING_KEY> <FIELD>` |
| Re-read one field across the ledger, from the listing itself | `legoscout deals refresh [FIELD]` |
| Replay the stored source-run fixtures through build and validate | `legoscout deals replay` |
| Report active-source artifacts and exact appraisal coverage | `legoscout deals run-manifest <RUN_DIR>` |
| Print the deal-record schema for one pipeline phase | `legoscout deals schema [PHASE]` |
| Set one deal's status | `legoscout deals status <LISTING_KEY> <STATUS>` |
| Hard gate: a deal record is invalid unless it stores a usable numeric price | `legoscout deals validate` |
| Snapshot adam-server's shared ledger down to the local working copy | `legoscout deploy pull-db` |
| Push the local ledger to adam-server, then deploy code if it changed | `legoscout deploy push` |
| Roll adam-server back to an earlier release and restart it | `legoscout deploy rollback [TARGET]` |
| Whether adam-server's code is in sync, release list, pm2 status | `legoscout deploy status` |
| Print the deals-table rows as JSON | `legoscout display rows` |
| Serve the deals page | `legoscout display serve` |
| Discover an AuctionNinja house's published premium, tax and origin | `legoscout pricing auctionninja-fees` |
| The published fee configuration for one source | `legoscout pricing fees --source <SOURCE>` |
| Fetch a listing's images for the vision pass | `legoscout pricing images` |
| Landed cost from a hammer price plus whatever freight is known | `legoscout pricing landed-cost` |
| Can Adam drive there? | `legoscout pricing pickup-area <LOCATION>` |
| Rebuild the pickup-area table from the public geography sources | `legoscout pricing rebuild-pickup-area` |
| BrickLink sold comps for one set number | `legoscout pricing set-sales <SET_NO>` |
| Price a whole appraiser batch in one concurrent call | `legoscout pricing comps-batch --input <HANDOFF> --output <FILE>` |
| A carrier rate for a listing whose SOURCE publishes none | `legoscout pricing shipping` |
| Record one contact on a prospect | `legoscout prospects contacts create <RECORD>` |
| Get one contact row | `legoscout prospects contacts get <CONTACT_ID>` |
| List every recorded contact | `legoscout prospects contacts list` |
| Record one evidence-backed prospect | `legoscout prospects create <RECORD>` |
| Get one prospect, with its contacts and outreach | `legoscout prospects get <PROSPECT_ID>` |
| Get one registered hypothesis type | `legoscout prospects hypotheses get <HYPOTHESIS_TYPE>` |
| List every registered hypothesis type | `legoscout prospects hypotheses list` |
| List every recorded prospect | `legoscout prospects list` |
| Get one outreach row and its state | `legoscout prospects outreach get <OUTREACH_ID>` |
| List every outreach row and its state | `legoscout prospects outreach list` |
| Send one approved outreach email | `legoscout prospects outreach send <OUTREACH_ID>` |
| Record one prospecting run | `legoscout prospects runs create <RECORD>` |
| Get one prospecting run | `legoscout prospects runs get <RUN_ID>` |
| List every prospecting run | `legoscout prospects runs list` |
| Score one or more stored deals | `legoscout score deal <LISTING_KEY>` |
| Recompute every live deal's score through the current rules | `legoscout score rescore` |
| Build seller rows from the seller identity already on the deal records | `legoscout sellers backfill` |
| Flag a seller as a favorite | `legoscout sellers favorite <SOURCE> <SELLER_ID>` |
| Get one seller row | `legoscout sellers get <SOURCE> <SELLER_ID>` |
| List every seller the ledger has seen | `legoscout sellers list` |
| Register a researched source, or print the template to research it | `legoscout sources add [ENTRY]` |
| Get one source's payload | `legoscout sources get <SOURCE>` |
| List every registered source | `legoscout sources list` |
| Append a learning note to a source | `legoscout sources notes add <SOURCE>` |
| Get one learning note by its id | `legoscout sources notes get <NOTE_ID>` |
| List a source's current learning notes | `legoscout sources notes list <SOURCE>` |
| Delete a source and its notes: the reverse of `add` | `legoscout sources remove <NAMESPACE>` |
| Report every structural problem with the registry | `legoscout sources validate` |
| Per-source crawl watermarks: how far back the next run must reach | `legoscout sources watermarks` |
| Filter, categorize and optionally detail a batch of raw eBay candidates | `legoscout triage <CANDIDATES>` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `legoscout` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `legoscout --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **deals** -- The canonical deal ledger (subcommands: build, expire, get, list, read, refresh, replay, run-manifest, schema, status, validate)
- **deploy** -- Sync the ledger and app code to adam-server (subcommands: pull-db, push, rollback, status)
- **display** -- The local deals web page (subcommands: rows, serve)
- **pricing** -- Deal economics: fees, landed cost, comps and freight (subcommands: auctionninja-fees, comps, comps-batch, ebay-comps, fees, images, landed-cost, pickup-area, preflight, profit, rebuild-pickup-area, set-sales, shipping)
- **prospects** -- Prospecting: new inventory sources and their contacts (subcommands: contacts, create, get, hypotheses, list, outreach, runs)
- **score** -- The deterministic 0-100 deal score (subcommands: deal, rescore)
- **sellers** -- Sellers, and Adam's favorite flag (subcommands: backfill, favorite, get, list)
- **sources** -- The source registry: which marketplaces, and how to reach each one (subcommands: add, get, list, notes, remove, validate, watermarks)
- **triage** -- Filter, categorize and optionally detail a batch of raw eBay candidates
</principle>
<principle name="Appraisal Contract">
- Pass one JSON object to each `legoscout deals build` file argument.
- Put `model_score` and `model_rationale` under `observations`.
- Use a numeric `model_score` from 0 through 100.
- Use a non-empty `model_rationale`.
- Run `legoscout deals run-manifest <RUN_DIR>` before synthesis.
- The manifest uses active registry sources. Dormant source rows do not create coverage gaps.
</principle>
<principle name="Mercari Buyer Fee">
- Read Mercari's numeric Buyer Protection fee from `priceSummary`.
- Pass it with `legoscout pricing landed-cost --buyer-protection-fee <AMOUNT>`.
- Do not infer the fee from Mercari's observed percentage range.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`legoscout --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
