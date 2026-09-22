# Crypto.com Exchange CLI

## DESCRIPTION

The `cryptocom` CLI provides command-line access to Crypto.com Exchange API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Installation

```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/install-cli-tool.sh --force-refresh cryptocom
```

The installer pins the tool venv to the system `python3` and installs the
repo-local editable `cli-tools-shared` dependency before creating the launcher.
The `cryptocom` command is installed into `~/.local/bin`.

## Quick Start

```bash
cryptocom instruments list --limit 5
cryptocom ticker get BTCUSD-PERP
cryptocom trades list BTCUSD-PERP --limit 10
cryptocom candlesticks list BTCUSD-PERP --timeframe 1m --limit 10
cryptocom account balance
cryptocom account positions
```

Private account commands require Exchange API credentials:

```bash
cryptocom auth login
cryptocom auth status
```

## Authentication

Create an API key in Crypto.com Exchange under `User Center > API`, then run:

```bash
cryptocom auth login
```

The standard shared auth command group is available:

```bash
cryptocom auth login
cryptocom auth login --force
cryptocom auth status
cryptocom auth status --table
cryptocom auth logout
```

Profiles are available under the standard `auth profiles` command:

```bash
cryptocom auth profiles list
cryptocom auth profiles get default
cryptocom auth profiles create sandbox
cryptocom auth profiles select sandbox
cryptocom auth profiles delete sandbox
```

## Commands

### Instruments

```bash
cryptocom instruments list
cryptocom instruments list --limit 10 --table
cryptocom instruments list --filter "inst_type:eq:PERPETUAL_SWAP"
cryptocom instruments list --properties "symbol,inst_type,tradable"
cryptocom instruments get BTCUSD-PERP
cryptocom instruments get BTCUSD-PERP --table
```

### Ticker

```bash
cryptocom ticker list
cryptocom ticker list --limit 10 --table
cryptocom ticker get BTCUSD-PERP
cryptocom ticker get BTCUSD-PERP --table
cryptocom ticker get BTCUSD-PERP --properties "i,a,b,k,t"
```

### Book

```bash
cryptocom book list
cryptocom book list --limit 10 --table
cryptocom book get BTCUSD-PERP
cryptocom book get BTCUSD-PERP --depth 10
cryptocom book get BTCUSD-PERP --properties "instrument_name,depth,t"
```

### Trades

```bash
cryptocom trades list BTCUSD-PERP
cryptocom trades list BTCUSD-PERP --limit 10
cryptocom trades list BTCUSD-PERP --filter "s:eq:sell"
cryptocom trades list BTCUSD-PERP --properties "d,p,q,s,t"
cryptocom trades list BTCUSD-PERP --start-ts 1776190000000 --end-ts 1776199999999
cryptocom trades get TRADE_ID BTCUSD-PERP
```

### Candlesticks

```bash
cryptocom candlesticks list BTCUSD-PERP
cryptocom candlesticks list BTCUSD-PERP --timeframe 1m --limit 10
cryptocom candlesticks list BTCUSD-PERP --filter "c:gt:70000"
cryptocom candlesticks list BTCUSD-PERP --properties "t,o,h,l,c,v"
cryptocom candlesticks get BTCUSD-PERP 1776197280000 --timeframe 1m
```

### Account

```bash
cryptocom account fee-rate
cryptocom account instrument-fee-rate SOL_USD
cryptocom account fills --instrument-name SOL_USD --start-time 1771761038000 --end-time 1771847438000 --limit 100
cryptocom account balance
cryptocom account balance --table
cryptocom account balance --filter "instrument_name:eq:USD"
cryptocom account balance --properties "instrument_name,total_available_balance,total_cash_balance"
cryptocom account positions
cryptocom account positions --table
cryptocom account positions --filter "market_value:gt:10"
cryptocom account positions --properties "instrument_name,quantity,market_value"
cryptocom account open-orders
cryptocom account open-orders --instrument-name BTCUSD-PERP
cryptocom account open-orders --table
cryptocom account open-orders --filter "side:eq:BUY"
cryptocom account open-orders --properties "order_id,instrument_name,side,quantity,limit_price,status"
```

### Orders

Authenticated trading order commands (signed private endpoints):

```bash
cryptocom orders create --symbol SOL_USD --side buy --price 96.50 --quantity 0.1 --spot-margin SPOT
cryptocom orders create --symbol BTC_USD --side buy --price 96.50 --quantity 0.1 --type LIMIT --tif IOC
cryptocom orders create --symbol BTC_USD --side sell --quantity 0.01 --type MARKET
cryptocom orders get ORDER_ID
cryptocom orders get --client-oid CLIENT_ORDER_ID
cryptocom orders details ORDER_ID
cryptocom orders details --client-oid CLIENT_ORDER_ID
cryptocom orders history --instrument-name SOL_USD --start-time 1771761038000 --end-time 1771847438000 --limit 100
cryptocom orders cancel ORDER_ID
cryptocom orders list
cryptocom orders list --instrument-name BTC_USD
cryptocom orders list --table
cryptocom orders list --filter "side:eq:BUY"
cryptocom orders list --properties "order_id,instrument_name,side,quantity,limit_price,status"
```

`--tif` accepts `GTC`, `IOC`, `FOK` aliases plus the full names
`GOOD_TILL_CANCEL`, `IMMEDIATE_OR_CANCEL`, `FILL_OR_KILL`. `--price` is required
for LIMIT orders and rejected for MARKET orders. `--quantity` and `--price` must
be positive finite decimal numbers: `Infinity`, `-Infinity` and `NaN` are
rejected before any request is signed. stdout carries only the API
result (for example `{"order_id": ...}`); messages go to stderr.

`--spot-margin` accepts `SPOT` or `MARGIN` (case-insensitive). Use `SPOT` to
make the execution mode explicit and prevent a spot order from borrowing.

Order lookup requires exactly one positional order ID or `--client-oid`; client-ID lookup also supports terminal orders. Create and cancel requests are attempted once, without automatic transport retries. Persist the client order ID before submission and reconcile ambiguous outcomes before another mutation. A cancel acknowledgement alone does not prove cancellation.

`account fee-rate` and `account instrument-fee-rate` preserve the venue fee fields in basis points; divide by 10,000 for a fractional rate. `account fills` preserves private executed trades, including `trade_id`, `client_oid`, `fees`, and `fee_instrument_name`; negative fees deduct from the balance.

`orders history` and `account fills` return a single venue page, capped at 100 rows, with raw fields and exact decimal strings. They do not claim complete history or paginate automatically. Use explicit `--start-time` and `--end-time` windows and nanosecond timestamps for recovery; the fills end time is exclusive. A full page requires further recovery reads before claiming completeness. `--filter` and `--properties` operate only on the returned page.

Official contracts: [order detail](https://exchange-developer.crypto.com/exchange/v1/docs/api/rest/private-get-order-detail), [order history](https://exchange-developer.crypto.com/exchange/v1/docs/api/rest/private-get-order-history), [private fills](https://exchange-developer.crypto.com/exchange/v1/docs/api/rest/private-get-trades), [account fees](https://exchange-developer.crypto.com/exchange/v1/docs/api/rest/private-get-fee-rate), [instrument fees](https://exchange-developer.crypto.com/exchange/v1/docs/api/rest/private-get-instrument-fee-rate).

### Cache

```bash
cryptocom cache status
cryptocom cache clear
cryptocom --no-cache ticker get BTCUSD-PERP
```

## Output Formats

JSON is the default output and is safe for piping:

```bash
cryptocom ticker get BTCUSD-PERP | jq '.a'
```

Use `--table` for human-readable output:

```bash
cryptocom instruments list --limit 5 --table
```

Use `--properties` to select fields:

```bash
cryptocom trades list BTCUSD-PERP --limit 5 --properties "p,q,s,t"
```

## Options Reference

| Option | Short | Commands | Description |
|--------|-------|----------|-------------|
| `--table` | `-t` | Output commands | Display table output |
| `--limit` | `-l` | List-style commands | Maximum number of rows |
| `--filter` | `-f` | List-style commands | Filter with `field:op:value` syntax |
| `--properties` | `-p` | Output commands | Comma-separated fields to include |
| `--depth` | `-d` | `book get` | Order book depth |
| `--timeframe` | | `candlesticks list` | Candlestick timeframe |
| `--start-ts` | | `trades list`, `candlesticks list` | Inclusive start timestamp |
| `--end-ts` | | `trades list`, `candlesticks list` | Exclusive end timestamp |
| `--instrument-name` | `-i` | `account open-orders`, `orders list` | Restrict open orders to one instrument |
| `--symbol` | `-s` | `orders create` | Instrument name (e.g., BTC_USD) |
| `--side` | | `orders create` | Order side: buy or sell |
| `--price` | | `orders create` | Limit price (required for LIMIT) |
| `--quantity` | `-q` | `orders create` | Order quantity in base currency |
| `--type` | | `orders create` | Order type: MARKET or LIMIT |
| `--tif` | | `orders create` | Time in force: GTC, IOC, FOK |
| `--client-oid` | | `orders create` | Optional client order ID |
| `--spot-margin` | | `orders create` | Execution mode: SPOT or MARGIN |
| `--version` | `-v` | Root command | Show version and exit |

## Configuration

Non-authentication configuration is stored in `~/.local/share/cli-tools/cryptocom/.env`. CLI-managed runtime auth state is stored in the active profile at `~/.local/share/cli-tools/cryptocom/authentication_profiles/<profile>/.env`. The source repo only carries `.env.example`.

Reusable CLI credentials that agents or scripts need to store/retrieve are governed by the user-level `cli-tool` skill's `references/secrets.md`.

Do not put reusable credentials in any `.env` file. Store and retrieve them through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. `.env` files are limited to non-secret config and CLI-managed runtime auth state.

Root config variables:

```bash
# API base URL (optional - defaults to production)
BASE_URL=https://api.crypto.com/exchange/v1
```

Authentication profile variables (CLI-managed runtime auth state):

```bash
ACTIVE=true
API_KEY=secret://cryptocom-api-key
API_SECRET=secret://cryptocom-api-secret
```

`API_KEY` and `API_SECRET` are sensitive credential fields. `auth login` writes the entered values to the CLI-tools secret manager and leaves only those `secret://` references in the profile `.env`; a plain-text value in either field is rejected when the profile loads. A named profile uses `secret://cryptocom-<profile>-api-key` and `secret://cryptocom-<profile>-api-secret`. To rotate a stored credential, run `cryptocom auth login --force` rather than editing the profile.

Sandbox profile example:

```bash
cryptocom auth profiles create sandbox
cryptocom auth profiles select sandbox
```

Then set `BASE_URL=https://uat-api.3ona.co/exchange/v1` in that profile.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication or credential error |
| 130 | User interrupted |

## Models

The client returns Pydantic models from `cryptocom_cli.models`:

| Model | Source |
|-------|--------|
| `Instrument` | `public/get-instruments` |
| `Ticker` | `public/get-tickers` |
| `BookSnapshot` | `public/get-book` |
| `Trade` | `public/get-trades` |
| `Candlestick` | `public/get-candlestick` |
| `AccountBalance` | `private/user-balance` |
| `PositionBalance` | `private/user-balance` nested position balances |
| `OpenOrder` | `private/get-open-orders` |

Models preserve extra API response fields so JSON output does not discard fields added by Crypto.com.

## Requirements

- Python 3.11+
- `typer`
- `python-dotenv`
- `requests`
- `pydantic`
- `cli-tools-shared`
