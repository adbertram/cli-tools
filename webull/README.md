# Webull CLI

## DESCRIPTION

Use the `webull` CLI to access Webull OpenAPI accounts, orders, futures historical bars, and streaming ticks through the official Python SDK. TickSmith calls this executable and keeps its own strategy, risk, order ownership, and audit decisions.

## Installation

Use the repository installer: `_repo/skills/cli-tool/scripts/install-cli-tool.sh webull`.

This is the local TickSmith-compatible SDK tool. Webull also publishes a separate [upstream Go CLI](https://github.com/webull-inc/webull-openapi-cli) with the same command name and a different interface. It is not a drop-in replacement for this tool's JSON, streaming, or send-deadline contract.

## Authentication

Create an OpenAPI application in Webull's [account center](https://www.webull.com/center). Run `webull auth login` and enter the application key and secret in the hidden prompts. The CLI stores reusable credentials in the CLI-tools secret manager and saves references in its authentication profile. Never put raw credentials in `.env` files or command arguments.

`webull auth status --profile default` verifies the saved credentials with a real account-list request and returns the shared `profiles[].credential_types.custom` JSON structure. The sandbox was verified with signature-only account access on October 26, 2026. Current [Webull authentication documentation](https://developer.webull.com/apis/docs/about-open-api/) requires an authorized access token for production trading/account access. After authorizing the token through Webull, run `webull auth token --profile default` for a hidden terminal prompt, or pipe the value securely into that command for automation. The CLI stores it in the secret manager.

```bash
webull auth login --profile default
webull auth login --profile default --force
webull auth status --profile default
webull auth test --profile default
webull auth logout --profile default
webull auth profiles list --table --limit 10 --properties name,active,auth_type
webull auth profiles get default --table
webull auth profiles create research
webull auth profiles select research
webull auth profiles rename research research-two
webull auth profiles delete research-two --force
webull auth profiles remove research-two --force
```

## Global options

Global options precede the command group. `--environment sandbox` is the default. Production access requires both `--environment live` and `--confirm-live`. `--profile NAME` chooses an existing authentication profile. `--region`, `--api-host`, `--quotes-api-host`, `--events-api-host`, `--connect-timeout`, and `--read-timeout` let callers pass their resolved configuration. Host overrides accept hostnames (optionally with ports); known production hosts are rejected in sandbox mode. `--version` prints the installed version and `--help` describes the command tree.

```bash
webull --version
webull --help
webull --environment sandbox --profile default --connect-timeout 3 --read-timeout 6 account list
```

## Accounts

```bash
webull account list
webull account list --limit 1 --filter 'account_type:eq:FUTURES' --properties account_id,account_type --table
webull account balance ACCOUNT_ID --table
webull account get ACCOUNT_ID --table
webull account positions ACCOUNT_ID
webull account positions ACCOUNT_ID --limit 10 --filter 'symbol:eq:MESZ6' --properties symbol,quantity --table
```

Account and position endpoints have no server-side pagination or filtering. Their optional `--limit/-l`, `--filter/-f`, and `--properties/-p` are applied locally; omitted options preserve the complete raw broker response. `--table/-t` changes presentation.

## Orders

```bash
webull order open ACCOUNT_ID --page-size 100
webull order list ACCOUNT_ID --page-size 100
webull order open ACCOUNT_ID --last-client-order-id CURSOR --limit 25 --table
webull order history ACCOUNT_ID --page-size 100 --start-date 2026-10-01 --end-date 2026-10-26
webull order history ACCOUNT_ID --filter 'client_order_id:eq:ORDER_ID' --properties client_order_id --table
webull order get ACCOUNT_ID CLIENT_ORDER_ID --table
webull order place ACCOUNT_ID --orders-json orders.json --dry-run
webull order place ACCOUNT_ID --orders-json - --yes
webull order place ACCOUNT_ID --orders-json orders.json --yes --send-before-epoch-ms 1793020000000
webull order replace ACCOUNT_ID --orders-json changes.json --dry-run
webull order replace ACCOUNT_ID --orders-json - --yes
webull order cancel ACCOUNT_ID CLIENT_ORDER_ID --dry-run
webull order cancel ACCOUNT_ID CLIENT_ORDER_ID --yes
```

`account get` is an alias of `account balance`. `order list` is an alias of `order open`. Open/history fetch exactly one API page. `--page-size` is passed to the broker and must be between 10 and 100 (default 100). Optional `--limit/-l` is a positive local output cap on that page; it does not change the API page size. `--last-client-order-id` and every returned combo's client order ID remain unchanged, including when output is capped, so the caller can use the last returned ID as its next cursor. History date filters pass unchanged to the SDK. The caller owns cursor traversal. Optional `--filter/-f` and `--properties/-p` also operate locally on the returned page because the API does not accept arbitrary field filters. Omitting these presentation options preserves the complete broker page.

Place and replace read a nonempty strict JSON array of raw SDK order objects from `--orders-json FILE`, or stdin when the value is `-`. Numeric NaN, Infinity, and overflowing numbers are rejected, including in nested fields. Every object must have a caller-defined unique `client_order_id` of at most 32 characters. Place, replace, and cancel require exactly one of `--yes` or `--dry-run`. This low-level broker tool does not calculate position size, attach stops, or enforce TickSmith strategy and account risk policies. TickSmith performs those checks before calling it.

`--send-before-epoch-ms` on place and replace is an optional absolute UTC deadline. It is checked after credential/SDK setup and immediately before the SDK transport; an expired deadline returns `kind=not_sent` without sending. This lets TickSmith keep an entry's original price-freshness deadline across process startup.

## Futures market data

```bash
webull futures bars MESmain --category US_FUTURES --timespan M1 --count 200
webull futures bars MESmain --timespan M5 --count 20 --table
webull futures stream MESmain --category US_FUTURES --reconnect-attempts 3 --reconnect-delay-milliseconds 1000 --mqtt-port 8883 --socket-loop-seconds 1 --close-grace-seconds 2
```

Bars preserve the full API response. Count is passed to Webull (1 through 1200). Streaming runs until interrupted and prints one compact JSON document per line:

```json
{"event":"tick","data":{"basic":{"symbol":"MESmain"},"time":"1793020000000","price":"5900.25","volume":"1","side":"B"}}
{"event":"disconnect"}
{"event":"error","error":{"kind":"upstream","message":"Webull tick connection ended.","http_status":null,"error_code":null}}
```

Every decoded tick field is preserved, including nested `basic` metadata. Decimal prices become strings. Disconnect events let consumers invalidate buffered prices. Malformed protobuf data is terminal and produces an error event. The stream's reconnect, MQTT, and socket-loop options control SDK transport; `--close-grace-seconds` communicates the caller's close budget.

## Output and failures

REST commands print one complete JSON object or array on stdout, preserving every API field unless explicit presentation options request a subset. Status messages use stderr. Data is never cached. HTTP requests are sent once; there are no automatic REST retries, because a retry after an uncertain mutation could duplicate a trade and external callers own pacing/recovery.

Failures exit nonzero and return a sanitized JSON envelope:

```json
{"error":{"kind":"unknown","message":"Webull request failed (TimeoutError). Order outcome is unknown; inspect its client_order_id before resending.","http_status":null,"error_code":null,"client_order_id":"caller-intent-1"}}
```

`rejected` means the SDK returned a definite HTTP 3xx/4xx broker rejection. `unknown` means a mutation encountered transport failure, a 5xx response, or unusable response JSON; the caller must reconcile its original client order ID before resending. `not_sent` proves the local deadline stopped transport. Other kinds include `validation`, `authentication`, `authorization`, and `upstream`. Request headers, tokens, secrets, and raw SDK exception messages are never included in errors.

## Development

```bash
uv sync --project webull
webull/.venv/bin/python -m pytest webull/tests
_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name webull
```

Official API documentation: https://developer.webull.com/apis/docs/ . SDK dependency: `webull-openapi-python-sdk==3.0.3`.
