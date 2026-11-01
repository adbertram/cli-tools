---
name: kalshi-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Kalshi operations using the `kalshi` CLI tool.
  Watch and trade Kalshi prediction markets: market data, WebSocket streaming of the Bitcoin 15 minute market, orders, balance and positions.
  Triggers: kalshi, kalshi cli, prediction market, btc15m, KXBTC15M, bitcoin 15 minute market, kalshi order, kalshi balance
---

<objective>
Execute Kalshi operations using the `kalshi` CLI. All Kalshi interactions should use this CLI.
</objective>

<quick_start>
The `kalshi` CLI follows this pattern:
```bash
kalshi <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Configure authentication credentials | `kalshi auth login` |
| Clear stored credentials | `kalshi auth logout` |
| Create a new profile from .env.example template | `kalshi auth profiles create <NAME>` |
| Delete a profile and its data | `kalshi auth profiles delete <NAME>` |
| Get details for a specific profile | `kalshi auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `kalshi auth profiles list` |
| Delete a profile and its data | `kalshi auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `kalshi auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `kalshi auth profiles select <NAME>` |
| Check authentication status across profiles | `kalshi auth status` |
| Test authentication by verifying credentials work across profiles | `kalshi auth test` |
| Get the available balance and portfolio value | `kalshi balance get` |
| Remove all cached responses | `kalshi cache clear` |
| Show the open market of a series: target, time left, YES/NO quotes, live reference price when streaming | `kalshi markets current <TARGET>` |
| Get one market by ticker | `kalshi markets get <TICKER>` |
| List markets, optionally for one series | `kalshi markets list` |
| Measure cold and warm REST latency, signing cost, and optionally the demo order round trip | `kalshi metrics get` |
| Cancel an order | `kalshi orders cancel <ORDER_ID>` |
| Get one order | `kalshi orders get <ORDER_ID>` |
| List orders | `kalshi orders list` |
| Place a limit order | `kalshi orders place <TICKER>` |
| Get the position in one market | `kalshi positions get <TICKER>` |
| List market positions (position_fp: positive = YES contracts, negative = NO contracts) | `kalshi positions list` |
| Get one market preset | `kalshi presets get <NAME>` |
| List market presets from presets.json | `kalshi presets list` |
| Stream the open market of a series as one JSON line per update, rolling to each new market | `kalshi stream watch <TARGET>` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `kalshi` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `kalshi --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage kalshi authentication (subcommands: login, logout, profiles, status, test)
- **balance** -- Account balance and portfolio value (subcommands: get)
- **cache** -- Manage response cache (subcommands: clear)
- **markets** -- Read markets and the current open market of a series (subcommands: current, get, list)
- **metrics** -- Measure request latency (subcommands: get)
- **orders** -- List, place and cancel orders (subcommands: cancel, get, list, place)
- **positions** -- List and inspect positions (subcommands: get, list)
- **presets** -- Market presets (name to series ticker) (subcommands: get, list)
- **stream** -- Stream live market data over WebSocket (subcommands: watch)
</principle>

<principle name="Presets">
Commands that take a series accept a preset name (`btc15m` maps to series `KXBTC15M`, reference index BRTI, YES = up, NO = down) or a raw series ticker. Presets live in `kalshi_cli/presets.json`; add a market by adding an entry.
</principle>

<principle name="Credentials">
`presets`, `markets` and `metrics` need no credentials. `stream watch`, `orders`, `balance` and `positions` are signed with a Kalshi Key ID plus a private key. The default profile is production; the profile named `demo` is the demo exchange and `--demo` selects it. Store the private key as one line of base64 in the secret manager (`base64 -i key.pem | tr -d '\n' | secrets.sh set kalshi-private-key`, or `kalshi-demo-private-key`), then run `kalshi auth login [--profile demo]`.
</principle>

<principle name="Order Safety">
`orders place`, `orders cancel` and `metrics get --orders` refuse without `--yes` or `--dry-run`. A real-money order on production also needs `--allow-production`. Use `--demo` for testing and `--dry-run` to preview the exact request. Never place a production order unless Adam explicitly asked for that order.
</principle>

<principle name="Live Reference Price">
`markets current` shows the BRTI reference price and its delta to the target only while `kalshi stream watch` runs for the same series. Start `stream watch` first when the live price matters.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`kalshi --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
