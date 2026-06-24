---
name: airbnb-cli
description: >-
  MANDATORY: Execute Airbnb read operations using the `airbnb` CLI tool.
  Search public renter stays without authentication, and read host listings, reservations, and message threads through Adam's imported Airbnb host session.
  Do not use Airbnb partner APIs or browser automation for this CLI.
  Triggers: airbnb, airbnb cli, airbnb stays, airbnb search, airbnb listings, airbnb reservations, airbnb messages, airbnb host data
---

<objective>
Execute Airbnb read operations using the `airbnb` CLI. Renter search and Airbnb host data reads should use this CLI.
</objective>

<quick_start>
The `airbnb` CLI follows this pattern:
```bash
airbnb <command-group> <action> [arguments] [options]
```

| Command | Use |
| --- | --- |
| `airbnb stays search "Pigeon Forge, TN" --checkin 2026-08-01 --checkout 2026-08-03 --adults 2 --limit 10` | Search public renter stay availability |
| `airbnb auth login` | Import Airbnb auth from the current Chrome session |
| `airbnb auth status` | Check saved Airbnb authentication |
| `airbnb listings list --limit 25` | List Airbnb listings |
| `airbnb listings get LISTING_ID` | Get one Airbnb listing |
| `airbnb reservations list --limit 25` | List Airbnb reservations |
| `airbnb reservations get RESERVATION_ID_OR_CONFIRMATION_CODE` | Get one Airbnb reservation |
| `airbnb messages list --limit 25` | List Airbnb message threads |
| `airbnb messages get THREAD_ID` | Get one Airbnb message thread |
| `airbnb cache clear` | Clear cached Airbnb reads |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `airbnb` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Read Only">
This CLI is read-only. Do not add or use write commands for listing edits, calendar changes, messages, pricing, or booking changes.
</principle>

<principle name="Renter Search">
`stays search` uses Airbnb's public search page JSON state. It does not require host authentication and does not automate a browser.
</principle>

<principle name="Chrome Session">
Authentication imports Adam's existing Chrome Airbnb session. The CLI does not automate the browser and does not use Airbnb partner APIs.
</principle>

<principle name="Command Groups">
- `stays`: Search public available stays from a renter perspective.
- `auth`: Import, verify, clear, and profile-manage Airbnb Chrome-session authentication.
- `listings`: Read Airbnb listing records.
- `reservations`: Read Airbnb reservation records.
- `messages`: Read Airbnb message thread records.
- `cache`: Clear cached read responses.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against `usage.json`
</success_criteria>
