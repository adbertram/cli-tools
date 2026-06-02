---
name: "cryptocom-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Use this skill to execute Crypto.com Exchange operations using the `cryptocom` CLI tool. Crypto.com Exchange API CLI. Triggers: cryptocom, cryptocom cli, Crypto.com Exchange, crypto.com exchange api, crypto.com market data, crypto.com balances, crypto.com open orders, BTCUSD-PERP ticker, Exchange API profiles"
---

<objective>
Execute Crypto.com Exchange operations using the `cryptocom` CLI. All Crypto.com Exchange interactions should use this CLI.
</objective>

<quick_start>
The `cryptocom` CLI follows this pattern:
```bash
cryptocom <command-group> <action> [arguments] [options]
```

| Command | Purpose |
|---------|---------|
| `cryptocom instruments list --limit 5` | List available Exchange instruments |
| `cryptocom ticker get BTCUSD-PERP` | Get ticker data for one instrument |
| `cryptocom book get BTCUSD-PERP --depth 10` | Get an order book snapshot |
| `cryptocom trades list BTCUSD-PERP --limit 10` | List recent public trades |
| `cryptocom candlesticks list BTCUSD-PERP --timeframe 1m --limit 10` | List OHLCV candles |
| `cryptocom account balance` | Get authenticated account balances |
| `cryptocom account open-orders --instrument-name BTCUSD-PERP` | List authenticated open orders |
| `cryptocom auth profiles list` | List auth profiles |
</quick_start>

<principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `cryptocom` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **account**: authenticated balances and open orders
- **book**: order book instrument discovery and snapshots
- **candlesticks**: OHLCV candle lists and recent candle lookup
- **instruments**: Exchange instrument discovery and metadata
- **ticker**: ticker lists and single-instrument ticker data
- **trades**: recent public trade lists and trade lookup
- **auth**: API key/secret login, status, logout, testing, and profiles
- **cache**: cache maintenance
</principle>

<principle name="Authentication">
Public market-data commands use `no_auth`. Private `account` commands require `cryptocom auth login` with Exchange `API_KEY` and `API_SECRET`; use `cryptocom auth profiles` for sandbox or alternate profile workflows.
</principle>
</principles>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against usage.json
</success_criteria>
