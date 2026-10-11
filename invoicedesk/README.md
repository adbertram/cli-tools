# InvoiceDesk CLI

## DESCRIPTION

Use InvoiceDesk CLI to manage customers, invoices, payments and PDF exports from scripts or a terminal. It preserves former FreshBooks command flags, JSON fields, filters and resumable exports; all requests target InvoiceDesk.

## Installation

```bash
_repo/skills/cli-tool/scripts/install-cli-tool.sh --force-refresh invoicedesk
```

## Authentication

Reusable API tokens belong only in `_repo/_secret-manager/secrets.sh`. Never put tokens in source files or `.env` files. `auth login` writes a secret reference into the selected runtime profile.

```bash
_repo/_secret-manager/secrets.sh set --tool invoicedesk --type api-key
_repo/_secret-manager/secrets.sh get invoicedesk-api-key | invoicedesk auth login
invoicedesk auth status
```

Default URL: https://invoice-desk.adamtheautomator.workers.dev. Set non-secret `BASE_URL` in the tool runtime configuration to use another deployment. Payment instructions come from InvoiceDesk Settings; `--terms` overrides them and `--no-terms` stores empty terms.

## Delivery

InvoiceDesk exports PDFs; the caller emails them. Download with `invoicedesk invoice download ID -o invoice.pdf`, deliver externally, then record delivery with `invoicedesk invoice mark-sent ID -F`. No command sends email. Download and mutation status messages go to stderr. JSON and tables go to stdout.

## Data and identifiers

Imported records retain historical IDs. New records use IDs such as `native:1`; pass the complete ID unchanged. List/create/update JSON preserves existing display fields; get returns complete raw records. Money is represented as exact decimal strings in raw records.

## Commands

### `invoicedesk auth login`

Configure authentication credentials. Prompts for required credentials based on the tool's authentication type. For OAuth authorization code flows, opens a browser for user consent.

```bash
invoicedesk auth login
```

| Option | Purpose |
|---|---|
| `--profile / -p` | Profile name to save credentials to |
| `--force / -F` | Clear existing ephemeral auth state and re-authenticate |

### `invoicedesk auth logout`

Clear stored credentials.

```bash
invoicedesk auth logout
```

| Option | Purpose |
|---|---|
| `--profile / -p` | Profile name to clear credentials from |

### `invoicedesk auth profiles create`

Create a new profile from .env.example template.

```bash
invoicedesk auth profiles create work
```

### `invoicedesk auth profiles delete`

Delete a profile and its data.

```bash
invoicedesk auth profiles delete work
```

| Option | Purpose |
|---|---|
| `--force / -F` | Skip confirmation |

### `invoicedesk auth profiles get`

Get details for a specific profile.

```bash
invoicedesk auth profiles get default
```

| Option | Purpose |
|---|---|
| `--table / -t` | Display as table |

### `invoicedesk auth profiles list`

List all profiles and show their auth types and active state.

```bash
invoicedesk auth profiles list
```

| Option | Purpose |
|---|---|
| `--table / -t` | Display as table |
| `--limit / -l` | Maximum number of profiles to return |
| `--filter / -f` | Filter: field:op:value (e.g., active:eq:True) |
| `--properties / -p` | Comma-separated list of fields to include |

### `invoicedesk auth profiles remove`

Delete a profile and its data.

```bash
invoicedesk auth profiles remove NAME
```

| Option | Purpose |
|---|---|
| `--force / -F` | Skip confirmation |

### `invoicedesk auth profiles rename`

Rename a profile, re-keying its secrets to the new profile name.

```bash
invoicedesk auth profiles rename OLD NEW
```

| Option | Purpose |
|---|---|
| `--keep-old` | Build and activate the new profile but leave the old profile dir and old secrets intact |
| `--force / -F` | Skip confirmation |

### `invoicedesk auth profiles select`

Activate a profile within its auth type.

```bash
invoicedesk auth profiles select default
```

### `invoicedesk auth status`

Check authentication status across profiles. Performs a live round-trip for every configured credential type so the report reflects ground truth — not on-disk belief. Saved credentials whose live verification fails are reported as ``authenticated: false`` with the failure reason in ``api_test``.

```bash
invoicedesk auth status
```

| Option | Purpose |
|---|---|
| `--profile / -p` | Profile name to check (defaults to all profiles) |
| `--table / -t` | Display as table |

### `invoicedesk auth test`

Test authentication by verifying credentials work across profiles.

```bash
invoicedesk auth test
```

| Option | Purpose |
|---|---|
| `--table / -t` | Display as table |
| `--verbose / -v` | Show detailed checks |
| `--profile / -p` | Profile name (defaults to all profiles) |

### `invoicedesk cache clear`

Remove all cached responses. Deletes every file in the cache directory ({storage_dir}/cache/) and reports how many files and bytes were freed.

```bash
invoicedesk cache clear
```

| Option | Purpose |
|---|---|
| `--profile` | Profile name |

### `invoicedesk customer create`

Create a new customer.

```bash
invoicedesk customer create -e john@acme.com -f John -l Doe -o "Acme Corp"
```

| Option | Purpose |
|---|---|
| `--email / -e` | Customer email address |
| `--first-name / -f` | Contact first name |
| `--last-name / -l` | Contact last name |
| `--organization / -o` | Organization/company name |
| `--profile` | Auth profile name |

### `invoicedesk customer find`

Find a customer by email address.

```bash
invoicedesk customer find client@example.com
```

| Option | Purpose |
|---|---|
| `--profile` | Auth profile name |

### `invoicedesk customer get`

Get details for a specific customer.

```bash
invoicedesk customer get 12345
```

| Option | Purpose |
|---|---|
| `--table / -t` | Display output as a formatted table instead of JSON |
| `--profile` | Auth profile name |

### `invoicedesk customer list`

List all customers/clients. Shows all customers in your InvoiceDesk account. Filterable fields: id, organization, name, email. Substring searches use 'contains', or 'like' with explicit SQL wildcards ('%acme%'). A bare 'like:acme' is an anchored, case-insensitive exact match.

```bash
invoicedesk customer list
```

| Option | Purpose |
|---|---|
| `--filter / -f` | Filter results (field:op:value, e.g., organization:contains:acme). Fields: id, organization, name, email. Note that 'like' is SQL LIKE, so a substring search needs wildcards: organization:like:%acme% |
| `--limit / -l` | Maximum number of customers to return (default: 100) |
| `--properties / -p` | Comma-separated list of properties to display (e.g., 'id,organization,email') |
| `--table / -t` | Display output as a formatted table instead of JSON |
| `--profile` | Auth profile name |

### `invoicedesk customer update`

Update an existing customer.

```bash
invoicedesk customer update 12345 --email newemail@acme.com
```

| Option | Purpose |
|---|---|
| `--email / -e` | New email address |
| `--first-name / -f` | New first name |
| `--last-name / -l` | New last name |
| `--organization / -o` | New organization name |
| `--profile` | Auth profile name |

### `invoicedesk export run`

Archive raw pages, details, PDFs and a coverage manifest for every business. Unsupported resources and failed reads are recorded in manifest.json. Partial exports exit 2 after writing their summary. No invoices are sent.

```bash
invoicedesk export run -o ./private-export
```

| Option | Purpose |
|---|---|
| `--output / -o` | Private export directory; must be new unless --resume is set |
| `--resume` | Verify and reuse saved response files, then retry missing reads |
| `--profile` | Auth profile name |

### `invoicedesk invoice create`

Create a new invoice. Supports multiple line items by repeating -d and -a flags. Each -d is paired with the corresponding -a by position. Use -q to set quantity per line item (defaults to 1). Payment terms are automatically added from InvoiceDesk Settings unless --no-terms is specified or --terms provides custom terms.

```bash
invoicedesk invoice create -c 12345 -d "Consulting Services" -a 500.00
```

| Option | Purpose |
|---|---|
| `--customer-id / -c` | Customer ID to invoice |
| `--description / -d` | Line item description (repeat for multiple line items) |
| `--amount / -a` | Line item amount, e.g. '500.00' (repeat for multiple line items) |
| `--quantity / -q` | Line item quantity (default: 1; repeat for multiple line items) |
| `--notes / -n` | Invoice notes |
| `--terms / -t` | Payment terms (overrides default from config) |
| `--po-number / -p` | Purchase order number/reference |
| `--attachment / -f` | Path to file to attach (PDF or image) |
| `--due-days` | Number of days until invoice is due (default: 30) |
| `--no-terms` | Skip adding default payment terms |
| `--profile` | Auth profile name |

### `invoicedesk invoice delete`

Delete/void an invoice.

```bash
invoicedesk invoice delete 1234567
```

| Option | Purpose |
|---|---|
| `--force / -F` | Skip confirmation prompt |
| `--profile` | Auth profile name |

### `invoicedesk invoice download`

Download an invoice as a PDF.

```bash
invoicedesk invoice download native:1 -o invoice.pdf
```

| Option | Purpose |
|---|---|
| `--output / -o` | Output file path (default: invoice_{number}.pdf in current directory) |
| `--profile` | Auth profile name |

### `invoicedesk invoice get`

Get details for a specific invoice.

```bash
invoicedesk invoice get 1234567
```

| Option | Purpose |
|---|---|
| `--table / -t` | Display output as a formatted table instead of JSON |
| `--profile` | Auth profile name |

### `invoicedesk invoice list`

List all invoices. Shows all invoices in your InvoiceDesk account with optional status filtering. Filterable fields: id, number, client, status, amount, outstanding, created, due_date. Substring searches use 'contains', or 'like' with explicit SQL wildcards ('%acme%'). A bare 'like:acme' is an anchored, case-insensitive exact match.

```bash
invoicedesk invoice list
```

| Option | Purpose |
|---|---|
| `--filter / -f` | Filter results (field:op:value, e.g., client:contains:acme). Fields: id, number, client, status, amount, outstanding, created, due_date. Note that 'like' is SQL LIKE, so a substring search needs wildcards: client:like:%acme% |
| `--status / -s` | Filter by status (draft, sent, viewed, paid, overdue) |
| `--unpaid / -u` | Filter to show only unpaid invoices (sent, viewed, overdue) |
| `--limit / -l` | Maximum number of invoices to return (default: 100) |
| `--from` | Filter invoices created on or after this date (YYYY-MM-DD) |
| `--to` | Filter invoices created on or before this date (YYYY-MM-DD) |
| `--properties / -p` | Comma-separated list of properties to display (e.g., 'id,number,client') |
| `--table / -t` | Display output as a formatted table instead of JSON |
| `--profile` | Auth profile name |

### `invoicedesk invoice mark-paid`

Mark an invoice as paid.

```bash
invoicedesk invoice mark-paid 1234567 -a 500.00
```

| Option | Purpose |
|---|---|
| `--amount / -a` | Payment amount (e.g., '500.00') |
| `--date / -d` | Payment date (YYYY-MM-DD, default: today) |
| `--profile` | Auth profile name |

### `invoicedesk invoice mark-sent`

Record external invoice delivery. Download PDF first; caller sends it.

```bash
invoicedesk invoice mark-sent native:1 -F
```

| Option | Purpose |
|---|---|
| `--force / -F` | Skip confirmation prompt |
| `--profile` | Auth profile name |

### `invoicedesk invoice update`

Update an existing invoice. --line-amount LINEID=AMOUNT sets that line's unit_cost (quantity unchanged). Find line IDs with `invoicedesk invoice get <id>`. InvoiceDesk replaces the whole lines array on update, so the invoice is fetched and every line is resent; lines not named are preserved. An unknown line ID or a non-numeric/non-positive amount fails with a non-zero exit and nothing is sent. With --line-amount the output JSON also includes the invoice lines.

```bash
invoicedesk invoice update 1234567 -f ./contract.pdf
```

| Option | Purpose |
|---|---|
| `--attachment / -f` | Path to file to attach (PDF or image) |
| `--notes / -n` | Update invoice notes |
| `--terms / -t` | Update payment terms |
| `--terms-from-config` | Set payment terms from InvoiceDesk Settings |
| `--po-number / -p` | Update purchase order number/reference |
| `--line-amount / -l` | Set an existing line's unit price as LINEID=AMOUNT, e.g. 2=750.00 (repeatable; quantity and all other lines are unchanged) |
| `--profile` | Auth profile name |

## Export

`export run` creates a private directory containing current raw data, every original imported archive file, native attachments, invoice PDFs and a SHA-256 manifest. `--resume` verifies every saved checksum before fetching missing files. Failed reads produce a partial manifest and exit 2. No source records change.

## Exit codes

0 means success, 1 means validation or API failure, 2 means invalid invocation or partial export.
