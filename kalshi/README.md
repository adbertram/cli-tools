# Kalshi CLI

## DESCRIPTION

Use this CLI to watch and trade Kalshi prediction markets from a terminal or an agent, starting with the Bitcoin 15 minute market. It reads market data without credentials, streams a market over WebSocket with a live reference price, and places, cancels and lists orders. Any other Kalshi series works through a data-driven preset registry.

## Docs

- API documentation: https://docs.kalshi.com
- Base URL: https://external-api.kalshi.com/trade-api/v2


## Installation

```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/install-cli-tool.sh --force-refresh kalshi
```

After installation, the `kalshi` command will be available in your terminal.

## Quick Start

```bash
# Public market data needs no credentials
kalshi markets current btc15m --table

# Stream the open market, one JSON line per update (needs a Kalshi API key)
kalshi stream watch btc15m

# Preview an order without sending it
kalshi orders place KXBTC15M-26NOV011630-30 --outcome yes --count 1 --price 0.40 --demo --dry-run
```

## Credentials

Public commands (`presets`, `markets`, `metrics`) work with no credentials. Streaming, orders, balance and positions are signed with a Kalshi API key: a Key ID plus a private key PEM.

1. Create the key at kalshi.com, Profile Settings, API Keys. Kalshi shows the private key once. Save it to a file and note the Key ID. Demo keys are created separately at https://demo.kalshi.co.
2. Store the private key in the CLI-tools secret manager as one line of base64 (the secret manager returns multi-line values hex-encoded), then link it to the profile. The default profile is production; the profile named `demo` is the demo exchange.

```bash
# Production
base64 -i /path/to/key.pem | tr -d '\n' | <cli-tools-root>/_repo/_secret-manager/secrets.sh set kalshi-private-key && kalshi auth login

# Demo
base64 -i /path/to/demo-key.pem | tr -d '\n' | <cli-tools-root>/_repo/_secret-manager/secrets.sh set kalshi-demo-private-key && kalshi auth login --profile demo
```

`auth login` prompts for the Key ID, which is not secret (it is sent in every request header), then validates the stored key. The private key never goes in a `.env` file.

## Safety

- The default environment is production. Add `--demo` (or `--env demo`) for the demo exchange, which uses the `demo` profile.
- `orders place`, `orders cancel` and `metrics get --orders` refuse to run without `--yes` or `--dry-run`: `Refusing to place order without --yes or --dry-run`.
- A real-money order on production additionally needs `--allow-production`. Without it the command refuses even with `--yes`.
- `--dry-run` builds and prints the exact request body and sends nothing, needs no credentials and no network.
- Order writes are never retried, so a lost response cannot double-place an order. A client order ID is generated unless `--client-order-id` is given.

## Commands

### Presets (`kalshi presets`)

A preset maps a short name to a Kalshi series ticker and its reference index. Presets live in `kalshi_cli/presets.json`; adding a market is a data change.

```bash
kalshi presets list
kalshi presets get btc15m
```

Any command that takes a series also accepts a raw series ticker such as `KXBTC15M`.

### Markets (`kalshi markets`)

```bash
# List open markets of a series
kalshi markets list --series btc15m --status open --limit 5 --table

# Filter and project fields
kalshi markets list --series btc15m --filter "ticker:startswith:KXBTC15M-26NOV01" --properties ticker,close_time

# One market
kalshi markets get KXBTC15M-26NOV011630-30

# Full order book, including every YES and NO bid price level
kalshi markets orderbook KXBTC15M-26NOV011630-30

# The market open right now: target price, seconds left, YES(up) and NO(down) bid/ask and sizes
kalshi markets current btc15m --table
```

`markets current` adds the live CF Benchmarks BRTI price and the delta to the target when a `kalshi stream watch` for the same series is running and its state is fresher than `--max-stream-age` seconds. Otherwise `reference_price` is `null`. NO quotes are derived from YES: NO bid is `1 - YES ask` and NO ask is `1 - YES bid`.

`markets orderbook` returns the native `orderbook_fp` object, with `yes_dollars` and `no_dollars` arrays of `[price, count]` string pairs. Both sides are bids; the opposite side's asks are `1 - bid` with the same count. It requests all levels.

### Streaming (`kalshi stream`)

```bash
# Stream the open market, rolling to each new 15 minute market on the same socket
kalshi stream watch btc15m

# Ten updates, then stop
kalshi stream watch btc15m --count 10

# At most one printed line per second for 60 seconds
kalshi stream watch btc15m --interval 1 --duration 60
```

`watch` keeps one WebSocket session with local state, so there is no polling. The first line prints once the BRTI price has arrived. Kalshi requires a signed WebSocket handshake even for public data, so it needs an API key.

### Orders (`kalshi orders`)

`--outcome yes` buys YES (up on BTC 15m); `--outcome no` buys NO (down). `--price` is always the price of the chosen outcome in dollars.

```bash
kalshi orders list --status resting --table
kalshi orders get ORDER_ID
kalshi orders place TICKER --outcome yes --count 1 --price 0.40 --demo --yes
kalshi orders place TICKER --outcome no --count 5 --price 0.60 --tif ioc --dry-run
kalshi orders place TICKER --outcome yes --count 1 --price 0.40 --yes --allow-production
kalshi orders cancel ORDER_ID --ticker TICKER --demo --yes
```

Time in force is `gtc` (default), `ioc` or `fok`. `--post-only` rejects instead of crossing, `--reduce-only` requires `--tif ioc`, and `--expiration-ts` requires `--tif gtc`.

### Balance and positions

```bash
kalshi balance get
kalshi positions list --table
kalshi positions get TICKER
```

`position_fp` is positive for YES contracts and negative for NO contracts.

### Metrics (`kalshi metrics`)

```bash
# Cold and warm REST latency on the persistent connection, plus per-request signing cost
kalshi metrics get --samples 20

# Also time a demo order place and cancel round trip (demo credentials required)
kalshi metrics get --orders --demo --yes
```

### Authentication (`kalshi auth`)

```bash
kalshi auth login
kalshi auth login --profile demo
kalshi auth status
kalshi auth test
kalshi auth logout
```

### Profiles (`kalshi auth profiles`)

```bash
kalshi auth profiles list
kalshi auth profiles get default
kalshi auth profiles select PROFILE_NAME
kalshi auth profiles create PROFILE_NAME
kalshi auth profiles delete PROFILE_NAME
```

## Performance

One persistent HTTP/1.1 keep-alive connection serves every REST call; `open_client` prewarms it in the background while credentials load. HTTP/1.1 beat HTTP/2 on this host: lower cold start and the same warm latency. The private key is parsed once per process, requests are signed with a single signature call, and JSON uses orjson. Run `kalshi metrics get` for current numbers on your machine. It spaces samples 0.25 seconds apart and disables retries, because the exchange answers bursts with HTTP 429 and a retried request would inflate the timings; a 429 during the run is reported as an error.

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output.
- `stream watch` prints newline-delimited JSON.
- `--limit` accepts 1 to 10000. Filters on `ticker`, `event_ticker` and `status:eq:<initialized|active|finalized>` are sent to the API; every other `markets list` filter runs on the rows after the API applied `--limit`.

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display data as a table |
| `--limit` | `-l` | Maximum number of results |
| `--filter` | `-f` | Filter results using `field:op:value` syntax |
| `--properties` | `-p` | Restrict output to selected fields |
| `--env` | `-e` | Exchange environment: `prod` (default) or `demo` |
| `--demo` |  | Use the demo exchange |
| `--yes` | `-y` | Confirm an order write |
| `--dry-run` |  | Print an order request without sending it |
| `--allow-production` |  | Allow a real-money order on production |
| `--version` | `-v` | Show version and exit |
| `--no-cache` |  | Bypass cached read responses for this execution |

## Configuration

Non-authentication configuration is stored in `~/.local/share/cli-tools/kalshi/.env`. CLI-managed runtime auth state is stored in the active profile at `~/.local/share/cli-tools/kalshi/authentication_profiles/<profile>/.env`. The source repo only carries `.env.example`.

Reusable CLI credentials are governed by the `cli-tool` skill's `references/secrets.md`. Do not put reusable credentials in any `.env` file. The profile holds a `secret://` reference to the private key, not the key:

```bash
KEY_ID=<kalshi_api_key_id>
PRIVATE_KEY=secret://kalshi-private-key
```

The demo profile uses `secret://kalshi-demo-private-key`.

## Cache

```bash
# Clear cached read responses
kalshi cache clear

# Bypass the cache for one execution
kalshi --no-cache markets list --series btc15m --status open
```


## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Client/config/authentication error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### Distance from target as a number

```bash
kalshi markets current btc15m --properties ticker,seconds_left,target_price,yes_ask,no_ask
```

### Log a market to a file

```bash
kalshi stream watch btc15m --duration 900 --interval 1 > btc15m.ndjson
```

## Output Contract

`markets current` and each `stream watch` line share one view:

| Field | Description |
|-------|-------------|
| `ticker` | Market ticker |
| `close_time` | When the market closes (UTC) |
| `seconds_left` | Seconds until close |
| `target_price` | Strike price the market settles against |
| `reference_index`, `reference_price`, `reference_ts_ms` | Live index (BRTI) price and its source timestamp, null without a stream |
| `delta` | Reference price minus target price |
| `yes_label`, `yes_bid`, `yes_bid_size`, `yes_ask`, `yes_ask_size` | YES (up) quotes, null when no size rests |
| `no_label`, `no_bid`, `no_bid_size`, `no_ask`, `no_ask_size` | NO (down) quotes derived from YES |
| `last_price`, `volume`, `open_interest` | Market statistics |

Prices are dollar strings; sizes and volume are contract-count strings.

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - httpx
  - orjson
  - websockets
  - cryptography

## License

MIT
