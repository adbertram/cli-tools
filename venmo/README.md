# Venmo CLI

A command-line interface for retrieving Venmo transaction history.

Venmo does not expose a public consumer API, so this CLI uses the reverse-engineered
[venmo-api](https://github.com/mmohades/Venmo) library, which talks to Venmo's private
mobile API at `https://api.venmo.com`. Authentication is username + password + SMS OTP;
a long-lived access token is saved after the first successful login so subsequent runs
do not re-prompt.

> Unofficial integration. Venmo can change its private API at any time. The CLI is
> read-only by design — only `transactions list` and `transactions get` are exposed.

## Installation

```bash
cd venmo
pip install -e .
```

After installation the `venmo` command is on your PATH.

## Authentication

This CLI does NOT prompt for a username or password — credentials are read from the
CLI-tools macOS keychain (service `cli-tools`) under these names:

| Secret name      | Source                                                 |
|------------------|--------------------------------------------------------|
| `venmo-username` | Your Venmo phone, email, or username                   |
| `venmo-password` | Your Venmo account password                            |

Store them once via the CLI-tools secret manager from the repo root:

```bash
_repo/_secret-manager/secrets.sh set venmo-username
_repo/_secret-manager/secrets.sh set venmo-password
```

Then run the interactive login. Venmo sends a 6-digit OTP via SMS; the CLI prompts
for it and exchanges it for an access token + device id, both of which are persisted
to the per-profile `.env` (`~/.local/share/cli-tools/venmo/authentication_profiles/<profile>/.env`):

```bash
venmo auth login
```

Non-interactive login (e.g. in scripts) — pass the OTP via env var:

```bash
VENMO_OTP=123456 venmo auth login --force
```

After login the device id is marked trusted, so future `auth login` calls only
re-prompt for OTP if Venmo invalidates the device or you pass `--force`.

```bash
# Check auth status (live round-trip)
venmo auth status

# Clear stored token and device id
venmo auth logout
```

## Commands

### Transactions

```bash
# List the 50 most recent transactions (full raw Venmo API payload per record, JSON)
venmo transactions list
venmo transactions list --profile personal

# Curated, human-readable table view
venmo transactions list --table

# Limit and select fields (dotted paths into the nested record are supported)
venmo transactions list --limit 10 --properties payment_id,payment.amount,note,payment.actor.display_name,payment.target.user.display_name

# Filter (dotted paths into the nested record are supported)
venmo transactions list --filter "payment.amount:gt:100"
venmo transactions list --filter "note:contains:lego"
venmo transactions list --filter "payment.status:eq:settled"
venmo transactions list --filter "payment.action:eq:pay"

# Paginate to older transactions
venmo transactions list --before-id 4418053612741823878

# Look up one transaction by payment_id
venmo transactions get 4418053612741823878
venmo transactions get 4418053612741823878 --profile personal
venmo transactions get 4418053612741823878 --table
```

### Profiles

```bash
venmo auth profiles list
venmo auth profiles get default
venmo auth profiles create work
venmo auth profiles select work
```

Each profile keeps its own access token, device id, and cache directory.

### Cache

The shared `@cached` decorator stores response files under
`~/.local/share/cli-tools/venmo/authentication_profiles/<profile>/cache/`.

```bash
venmo cache status
venmo cache clear
venmo --no-cache transactions list   # bypass cache for one invocation
```

Disable caching globally by setting `CACHE_ENABLED=false`.

## Output Contract

`transactions list` and `transactions get` return the **raw Venmo API payload** for
each transaction by design — every field Venmo returns is in the output, no
normalization, no field-dropping. If Venmo adds fields server-side, you see them
without a CLI release. The CLI injects **one** convenience field at the top level:

| Field            | Type    | Description                                                              |
|------------------|---------|--------------------------------------------------------------------------|
| `payment_id`     | string  | Venmo's durable payment id (also present at `payment.id`). Use this with `venmo transactions get` and with `--filter "payment_id:eq:..."`. |

Everything else under each record is the raw `Transaction._json` from venmo-api.
Top-level keys observed today (Venmo can add more at any time):

```text
id                          # Venmo's story_id (null for /stories/target-or-actor results)
type                        # "payment", "transfer", "authorization", etc.
note                        # User-supplied memo
date_created date_updated   # ISO-8601 timestamps
audience                    # "public" | "friends" | "private"
transaction_external_id     # External id (mirrors payment.id today)
payment                     # Full payment object: id, status, action (pay/charge), amount, audience,
                            # actor (full user obj), target {type, user|merchant|email|phone, redeemable_target},
                            # date_authorized, date_completed, date_reminded, date_created,
                            # external_wallet_payment_info, participants, merchant_split_purchase
app                         # Venmo client info: {id, name, description, image_url, site_url}
likes                       # {count, data: [user, ...]}
reactions                   # [{reaction_id, emoji, count, reacted_by_user}, ...]
comments                    # {count, data: [comment, ...]}
mentions                    # {count, data: [...]}
transfer                    # ACH transfer details (null for non-transfer rows)
authorization               # Card authorization details (null for non-card rows)
payment_id                  # CLI-injected convenience field (== payment.id)
```

User objects on `payment.actor`, `payment.target.user`, and inside likes/comments
arrays include: `id`, `username`, `display_name`, `first_name`, `last_name`,
`profile_picture_url`, `about`, `email`, `phone`, `date_joined`, `friend_status`,
`is_active`, `is_blocked`, `is_payable`, `identity`, `identity_type`, `is_group`,
`audience`, `trust_request`, `friends_count`.

**Dotted-path filters and properties.** Both `--filter` and `--properties` walk into
the nested payload using dot notation:

```bash
--filter "payment.amount:gt:100"
--filter "payment.target.user.username:eq:ZBurklow"
--properties "payment_id,payment.amount,payment.actor.display_name,note"
```

**`venmo transactions list` JSON envelope.** Outputs are wrapped in
`{"cache_hit": <bool>, "results": [...]}` (the standard envelope this CLI suite
uses when the shared `@cached` decorator is wired). Use `jq '.results[]'` to iterate.

**`--table` view.** The table extracts a curated subset of dotted-path columns:
`payment_id`, `date_created`, `type`, `payment.action`, `payment.amount`,
`payment.status`, `payment.actor.display_name`, `payment.target.user.display_name`,
`note`. Pass `--properties` to override the column set with your own dotted paths.

## Output Formats

All commands default to JSON on stdout; pass `--table` / `-t` for a human-readable
table. stderr is reserved for status messages.

## Options Reference

| Option          | Short | Where                  | Description                                                    |
|-----------------|-------|------------------------|----------------------------------------------------------------|
| `--limit`       | `-l`  | `transactions list`    | Max transactions to return (default 50)                        |
| `--filter`      | `-f`  | `transactions list`    | `field:op:value` filter, repeatable. Supports dotted paths (e.g. `payment.amount:gt:100`). |
| `--table`       | `-t`  | list / get             | Render as a table (curated dotted-path columns by default).    |
| `--properties`  | `-p`  | list / get             | Comma-separated whitelist of fields. Supports dotted paths (e.g. `payment_id,payment.amount,payment.actor.display_name`). |
| `--before-id`   |       | `transactions list`    | Return transactions older than this `payment_id` (pagination)  |
| `--profile`     |       | list / get             | Authentication profile to use for the transaction query         |
| `--force`       | `-F`  | `auth login`           | Clear existing token + device id and re-authenticate           |
| `--no-cache`    |       | top-level              | Bypass the response cache for this invocation                  |
| `--version`     | `-v`  | top-level              | Print version and exit                                         |

## Configuration

Per-profile state lives in `~/.local/share/cli-tools/venmo/authentication_profiles/<profile>/.env`:

```bash
ACCESS_TOKEN=<long-lived Venmo access token>
DEVICE_ID=<trusted device id; reused to skip OTP next login>
```

Username/password are NOT stored here; they are read from the keychain on each login.

## Exit Codes

| Code | Meaning                              |
|------|--------------------------------------|
| 0    | Success                              |
| 1    | General error                        |
| 2    | Authentication / credential error    |
| 130  | User interrupted (Ctrl+C)            |

## Examples

```bash
# Total amount paid in the most recent 50 transactions where note mentions "lego"
venmo transactions list --filter "note:contains:lego" | jq '[.results[].payment.amount] | add'

# Export the full raw payload to JSON
venmo transactions list --limit 200 > transactions.json

# Just the people you've paid most recently (curated columns)
venmo transactions list --limit 20 --properties payment.target.user.display_name,payment.amount,note --table
```

## Requirements

- Python 3.9+
- Dependencies (installed automatically): `typer`, `python-dotenv`, `requests`, `venmo-api`, `cli-tools-shared`

## License

MIT
