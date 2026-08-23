# Crypto.com Exchange CLI

## DESCRIPTION

The `cryptocom` CLI provides command-line access to Crypto.com Exchange API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Installation

```bash
uv tool install -e <cli-tools-root>/cryptocom --force --refresh
```

The `cryptocom` command is installed into `~/.local/bin`.

## Quick Start

```bash
cryptocom instruments list --limit 5
cryptocom ticker get BTCUSD-PERP
cryptocom trades list BTCUSD-PERP --limit 10
cryptocom candlesticks list BTCUSD-PERP --timeframe 1m --limit 10
cryptocom account balance
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
cryptocom account balance
cryptocom account balance --table
cryptocom account balance --filter "instrument_name:eq:USD"
cryptocom account balance --properties "instrument_name,total_available_balance,total_cash_balance"
cryptocom account open-orders
cryptocom account open-orders --instrument-name BTCUSD-PERP
cryptocom account open-orders --table
cryptocom account open-orders --filter "side:eq:BUY"
cryptocom account open-orders --properties "order_id,instrument_name,side,quantity,limit_price,status"
```

### Orders

Authenticated trading order commands (signed private endpoints):

```bash
cryptocom orders create --symbol SOL_USD --side buy --price 96.50 --quantity 0.1
cryptocom orders create --symbol BTC_USD --side buy --price 96.50 --quantity 0.1 --type LIMIT --tif IOC
cryptocom orders create --symbol BTC_USD --side sell --quantity 0.01 --type MARKET
cryptocom orders details ORDER_ID
cryptocom orders cancel ORDER_ID
cryptocom orders list
cryptocom orders list --instrument-name BTC_USD
cryptocom orders list --table
cryptocom orders list --filter "side:eq:BUY"
cryptocom orders list --properties "order_id,instrument_name,side,quantity,limit_price,status"
```

`--tif` accepts `GTC`, `IOC`, `FOK` aliases plus the full names
`GOOD_TILL_CANCEL`, `IMMEDIATE_OR_CANCEL`, `FILL_OR_KILL`. `--price` is required
for LIMIT orders and rejected for MARKET orders. stdout carries only the API
result (for example `{"order_id": ...}`); messages go to stderr.

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
| `--version` | `-v` | Root command | Show version and exit |

## Configuration

Credentials are stored in profile-aware `.env` files.

```bash
ACTIVE=true
API_KEY=your_exchange_api_key
API_SECRET=your_exchange_api_secret
BASE_URL=https://api.crypto.com/exchange/v1
```

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
| `OpenOrder` | `private/get-open-orders` |

Models preserve extra API response fields so JSON output does not discard fields added by Crypto.com.

## Requirements

- Python 3.9+
- `requests`
- `pydantic`
- `typer`
- `cli-tools-shared`
