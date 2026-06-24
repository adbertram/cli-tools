# Bricklink CLI

A command-line interface for the [Bricklink API](https://www.bricklink.com/v3/api.page). Bricklink marketplace API

## Installation

```bash
cd bricklink
pip install -e .
```

After installation, the `bricklink` command will be available in your terminal.

## Testing

From this directory, run BrickLink's tests through the uv project environment and
add pytest for the run:

```bash
uv run --with pytest python -m pytest tests
```

For a focused regression test:

```bash
uv run --with pytest python -m pytest tests/test_browser_runtime.py::test_get_page_for_does_not_require_networkidle -vv
```

Do not use bare `python -m pytest` or `uv run python -m pytest` for this repo.
The first misses project dependencies such as `cli_tools_shared`; the second
does not include pytest unless it is supplied for the run.

## Quick Start

```bash
# Authenticate with Bricklink
bricklink auth login

# List items
bricklink items list

# Get a specific item
bricklink items get ITEM_ID
```

## Commands

### Authentication

```bash
# Login with API key
bricklink auth login
bricklink auth login --api-key YOUR_API_KEY

# Check authentication status
bricklink auth status
bricklink auth status

# Clear stored credentials
bricklink auth logout
```

Browser-backed commands prompt for BrickLink email confirmation codes when
BrickLink redirects the active browser page to `confirmation_code_required`.
The command keeps the browser session open, asks for the emailed code on
stderr, submits it, and retries the original request.

#### Browser Session Recovery Notes

When browser-backed commands report an expired session or a persistent AWS WAF
challenge, rebuild only the browser session first:

```bash
bricklink auth login --credential-type browser_session
```

In Codex or another non-interactive runner, start that command in a real TTY.
It opens a headed Chrome profile at
`~/.local/share/cli-tools/bricklink/authentication_profiles/default/browser-data/chromium-profile`
and waits for Enter before verifying and closing the browser. Do not press
Enter until the visible browser is actually signed in.

Important gotchas from a live recovery attempt:

- `--force` clears the saved browser profile before opening login. If the
  runner cannot complete the interactive browser login, the prior session is
  gone. Prefer the non-force command first.
- The profile `.env` may contain `secret://...` placeholders. Resolve those
  placeholders only through the CLI-tools secret manager, and never echo the
  values. These are CLI credentials, not proof of a LEGO web login. In the
  observed recovery, the saved `bricklink-username` was the store username and
  LEGO rejected it as a login; the saved `bricklink-password` value also
  produced LEGO `invalid_login`, so verify that secret is current before
  trusting it for browser login.
- Use the LEGO account email plus the LEGO web password. LastPass is the
  expected source for that browser password. If `lastpass`/`lpass` is not logged
  in, stop at the credential blocker; do not reset the LEGO password without
  explicit approval.
- The CLI-owned auth browser is opened through the shared Playwright harness and
  is not exposed as an attachable CDP browser. For diagnostics, a Codex run can
  launch the same persistent profile with Playwright and interact with the LEGO
  form directly, then return to `bricklink auth status` for verification.
- For email codes, use the newest Gmail result. Known BrickLink confirmation
  subject: `Your BrickLink confirmation code`. If the local `google` CLI lacks
  Gmail scopes, use the Gmail connector instead of asking the user to relay the
  code.
- `bricklink messages list` may be cached. Use `bricklink cache clear` and a
  live browser-backed command such as `bricklink messages get <message-id>` to
  verify the session.
- Copying cookies from the normal Chrome profile did not restore CLI auth in
  the observed recovery. BrickLink/LEGO auth cookies were `HttpOnly` and
  encrypted (`v10`); reading Chrome Safe Storage required a macOS Keychain
  Allow prompt, and a temporary copy of the normal Chrome profile still opened
  BrickLink at the LEGO login page with only non-auth cookies exposed. Chrome
  also refused remote debugging on the default profile with: `DevTools remote
  debugging requires a non-default data directory`.

### Items

```bash
# List all items (JSON output)
bricklink items list

# List items with table format
bricklink items list

# Limit results
bricklink items list --limit 10

# Get a specific item
bricklink items get ITEM_ID
bricklink items get ITEM_ID
```

### order

Manage orders.

```bash
bricklink order list
bricklink order get <order-id>
bricklink order items <order-id>
bricklink order update-status <order-id> --status SHIPPED
bricklink order ship <order-id> --tracking-number <number>
```

### inventory

Manage store inventory.

```bash
bricklink inventory list
bricklink inventory get <inventory-id>
bricklink inventory search <part-number>
bricklink inventory update <inventory-id> --quantity 10
bricklink inventory update-qty --input items.json
bricklink inventory stats
bricklink inventory stockroom
```

### catalog

Browse catalog data.

```bash
bricklink catalog get PART 3001
bricklink catalog part 3001
bricklink catalog set 10255-1
bricklink catalog minifig sw0001
bricklink catalog price PART 3001
bricklink catalog colors PART 3001
bricklink catalog subsets SET 10255-1
bricklink catalog supersets PART 3001
```

### member

Member information.

```bash
bricklink member ratings <username>
bricklink member note <username>
bricklink member set-note <username> --note "Repeat buyer"
bricklink member delete-note <username>
```

### coupon

Manage coupons.

```bash
bricklink coupon list
bricklink coupon get <coupon-id>
bricklink coupon create --buyer <username> --discount 10
bricklink coupon delete <coupon-id>
```

### messages

Manage messages (browser-based).

```bash
bricklink messages list-inbox
bricklink messages list-outbox
bricklink messages get <message-id>
bricklink messages send <order-id> "Your order has shipped!"
bricklink messages send --member <username> "Hello!" --subject "Re: Your message"
bricklink messages reply <message-id> --message "Thank you!"
bricklink messages mark-read <message-id>
```

### refund

Manage refunds (browser-based).

```bash
bricklink refund info <order-id>
bricklink refund issue <order-id> --amount 5.00
bricklink refund full <order-id>
```

### notification

Manage notifications (browser-based).

```bash
bricklink notification list
bricklink notification get <type>
bricklink notification send-wanted-list
```

### profiles

Manage authentication profiles.

```bash
bricklink auth profiles list
bricklink auth profiles get <profile-name>
bricklink auth profiles create <profile-name>
bricklink auth profiles select <profile-name>
bricklink auth profiles delete <profile-name>
```

### Cache (`bricklink cache`)

Manage the response cache. Cached responses speed up repeated commands by avoiding redundant browser/API calls.

```bash
# Clear all cached responses
bricklink cache clear
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

### JSON Output Example

```bash
bricklink items list --limit 2
```

### Table Output Example

```bash
bricklink items list --limit 5
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--limit` | `-l` | Maximum number of results (default: 50) |
| `--offset` | `-o` | Offset for pagination |
| `--version` | `-v` | Show version and exit |

## Configuration

Authentication profile files live under `~/.local/share/cli-tools/bricklink/authentication_profiles/<profile>/`; non-auth defaults live in `~/.local/share/cli-tools/bricklink/.env`:

```bash
# API Key
BRICKLINK_API_KEY=your_api_key

# Or OAuth credentials
BRICKLINK_CLIENT_ID=your_client_id
BRICKLINK_CLIENT_SECRET=your_client_secret

# OAuth tokens (managed automatically after login)
BRICKLINK_ACCESS_TOKEN=<access_token>
BRICKLINK_REFRESH_TOKEN=<refresh_token>
BRICKLINK_TOKEN_EXPIRES_AT=<timestamp>

# Optional: API base URL
BRICKLINK_BASE_URL=https://api.bricklink.com/api/store/v1
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### List Items and Filter with jq

```bash
bricklink items list | jq '.items[].id'
```

### Export Items to JSON File

```bash
bricklink items list --limit 200 > items.json
```

## Data Output

Commands emit plain JSON-compatible dictionaries and lists. Table output is a rendering option only; the JSON shape is the command contract.

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests
  - cli-tools-shared

## License

MIT
