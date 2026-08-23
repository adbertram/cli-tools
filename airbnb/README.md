# Airbnb CLI

## DESCRIPTION

Use this CLI to search public renter stay availability and read Airbnb host listings, reservations, and messages. It does not automate a browser or use Airbnb partner APIs; host reads use `airbnb auth login` to import Adam's current Chrome cookies, while renter search uses public search page JSON state.

## Installation

```bash
cd <cli-tools-root>/airbnb
uv tool install -e . --force --refresh
```

## Authentication

Sign in to Airbnb in Chrome first, then run:

```bash
airbnb auth login
airbnb auth status
airbnb auth test
```

Use `airbnb auth login --force` to refresh the imported Chrome session.

## Read Commands

```bash
airbnb stays search "Pigeon Forge, TN" --checkin 2026-08-01 --checkout 2026-08-03 --adults 2 --limit 10
airbnb stays search "Sevierville, TN" --checkin 2026-08-01 --checkout 2026-08-03 --adults 4 --children 2 --max-price 500 --bedrooms 2 --table

airbnb listings list --limit 25
airbnb listings list --table
airbnb listings get LISTING_ID

airbnb reservations list --limit 25
airbnb reservations list --date-min 2026-06-17 --status accepted,request
airbnb reservations get RESERVATION_ID_OR_CONFIRMATION_CODE

airbnb messages list --limit 25
airbnb messages get THREAD_ID
```

JSON is the default output. Add `--table` for a compact table.

Every list-style command supports:

```bash
--limit / -l
--filter / -f
--properties / -p
--table / -t
```

Every get command supports:

```bash
--properties / -p
--table / -t
```

## Examples

```bash
airbnb stays search "Pigeon Forge, TN" --checkin 2026-08-01 --checkout 2026-08-03 --adults 2 --properties "id,name,price_display,rating,url"
airbnb listings list --properties "id,name,status"
airbnb reservations list --properties "id,confirmation_code,start_date,end_date,status"
airbnb messages list --properties "id,threadId,type,status"
```

## Configuration

Non-authentication configuration is stored in:

```bash
~/.local/share/cli-tools/airbnb/.env
```

CLI-managed authentication state is stored in:

```bash
~/.local/share/cli-tools/airbnb/authentication_profiles/<profile>/.env
```

Sensitive session fields are routed through the CLI-tools secret manager:

```bash
AUTH_COOKIES_JSON=secret://airbnb-auth-cookies-json
AIRBNB_API_KEY=secret://airbnb-api-key
```

Source-controlled `.env` files must not contain Airbnb cookies, API keys, or reusable credentials.

## Cache

```bash
airbnb cache clear
airbnb --no-cache listings list --limit 10
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Client/config/authentication error |
| 130 | User interrupted |
