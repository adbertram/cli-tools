# Cloudflare CLI

## DESCRIPTION

The `cloudflare` CLI provides a command-line interface for Cloudflare API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Installation

```bash
cd cloudflare
pip install -e .
```

After installation, the `cloudflare` command will be available in your terminal.

## Quick Start

```bash
# Authenticate with Cloudflare
cloudflare auth login

# List zones
cloudflare zones list

# Purge cache for a zone
cloudflare cache purge ZONE_ID
```

## Commands

### Account Token Discovery

These read-only commands use the CLI's existing credential without exporting it.
They require Account API Tokens Read or Write. Successful reads and the available
permission catalog do not prove that the caller has Account API Tokens Write.
No create, delete, rotation, or bearer-value command is provided.

```bash
cloudflare account-tokens list ACCOUNT_ID --limit 0
cloudflare account-tokens list ACCOUNT_ID --filter 'name:eq:Issue Manager Queue' --properties id,name,status
cloudflare account-tokens get TOKEN_ID ACCOUNT_ID --table
cloudflare account-tokens permissions list ACCOUNT_ID --filter 'name:contains:Queues' --limit 0
cloudflare account-tokens permissions get PERMISSION_ID ACCOUNT_ID --table
```

Token lists follow page metadata with 50 records requested per page. Filters run
client-side before the limit; `--limit 0` returns all matching records. The permission
catalog has no pagination parameters. Its `get` command selects an ID from that catalog.
Both list/get support `--properties`, `--table`, and the shared `--profile` option.

### Authentication

```bash
# Login with API token
cloudflare auth login
cloudflare auth login --api-token YOUR_API_TOKEN

# Force re-authentication
cloudflare auth login --force

# Check authentication status
cloudflare auth status
cloudflare auth status

# Clear stored credentials
cloudflare auth logout
```

### Profiles

```bash
# List all profiles
cloudflare auth profiles list
cloudflare auth profiles list --table

# Get a specific profile
cloudflare auth profiles get default

# Filter profiles
cloudflare auth profiles list --filter "active:eq:true"

# Create a new profile
cloudflare auth profiles create staging

# Select active profile
cloudflare auth profiles select staging

# Delete a profile
cloudflare auth profiles delete staging --force
```

### Zones

```bash
# List all zones (JSON output)
cloudflare zones list

# List zones with table format
cloudflare zones list

# Limit results
cloudflare zones list --limit 10

# Filter by status
cloudflare zones list --filter "status:active"

# Select specific properties
cloudflare zones list --properties "id,name,status"

# Get a specific zone
cloudflare zones get ZONE_ID
cloudflare zones get ZONE_ID

# Update zone settings
cloudflare zones update ZONE_ID --security-level high
cloudflare zones update ZONE_ID --security-level under_attack
cloudflare zones update ZONE_ID -s medium
```

**Security Levels:**
- `off` - No security
- `essentially_off` - Challenges only the most grievous offenders
- `low` - Challenges more visitors
- `medium` - Challenges visitors displaying threatening behavior (default)
- `high` - High security level
- `under_attack` - I'm Under Attack mode

### Cache

```bash
# Purge all cache for a zone (prompts for confirmation)
cloudflare cache purge ZONE_ID

# Purge without confirmation
cloudflare cache purge ZONE_ID --force

# Show result as table
cloudflare cache purge ZONE_ID --force
```

### Access Rules

```bash
# List access rules for a zone
cloudflare access-rules list ZONE_ID
cloudflare access-rules list ZONE_ID --table
cloudflare access-rules list ZONE_ID --mode whitelist

# Get a specific rule
cloudflare access-rules get ZONE_ID RULE_ID

# Create a rule
cloudflare access-rules create ZONE_ID --target ip --value 1.2.3.4 --mode block

# Update a rule
cloudflare access-rules update ZONE_ID RULE_ID --mode challenge

# Delete a rule
cloudflare access-rules delete ZONE_ID RULE_ID --force
```

### DNS

#### DNS Zones

```bash
# List zones
cloudflare dns zones list
cloudflare dns zones list --table
cloudflare dns zones list --filter "status:eq:active"

# Get zone details
cloudflare dns zones get ZONE_ID
```

#### DNS Records

```bash
# List records for a zone
cloudflare dns records list ZONE_ID
cloudflare dns records list ZONE_ID --table
cloudflare dns records list ZONE_ID --type TXT
cloudflare dns records list ZONE_ID --filter "type:eq:A"

# Get a specific record
cloudflare dns records get ZONE_ID RECORD_ID

# Create a record
cloudflare dns records create ZONE_ID --type A --name example.com --content 1.2.3.4
cloudflare dns records create ZONE_ID --type TXT --name example.com --content "v=spf1 ..."
cloudflare dns records create ZONE_ID --type MX --name example.com --content mail.example.com --priority 10

# Update a record
cloudflare dns records update ZONE_ID RECORD_ID --content 5.6.7.8

# Delete a record
cloudflare dns records delete ZONE_ID RECORD_ID --force
```

### Email Routing

Custom-address-to-destination email forwarding for a zone (e.g. `sales@example.com`
forwards to your personal inbox). Settings and rules are zone-scoped
(`/zones/{zone_id}/email/routing...`); destination addresses are account-scoped
(`/accounts/{account_id}/email/routing/addresses...`) because one verified
address can be reused as a forward target across every zone in the account.

#### Settings

```bash
# Check whether Email Routing is enabled for a zone
cloudflare email-routing settings get example.com
cloudflare email-routing settings get ZONE_ID --table

# Enable Email Routing (Cloudflare adds and locks the required MX/SPF records)
cloudflare email-routing settings enable example.com

# Disable Email Routing (Cloudflare removes the MX records it added)
cloudflare email-routing settings disable example.com
```

#### Rules

Each rule matches a custom address (or every address, with `--catch-all`) and
either forwards matched mail to a verified destination address or drops it.

```bash
# List rules for a zone
cloudflare email-routing rules list example.com
cloudflare email-routing rules list ZONE_ID --limit 0
cloudflare email-routing rules list ZONE_ID --filter "name:contains:Support" --table
cloudflare email-routing rules list ZONE_ID --enabled true

# Get a single rule
cloudflare email-routing rules get example.com RULE_ID

# Create a rule: custom address -> forward
cloudflare email-routing rules create example.com --address sales@example.com --forward-to me@gmail.com
cloudflare email-routing rules create example.com --address sales@example.com --forward-to me@gmail.com --name "Sales inbox" --priority 0

# Create a catch-all rule that drops everything not matched elsewhere
cloudflare email-routing rules create example.com --catch-all --drop --name "Catch-all drop" --disabled

# Advanced: pass raw matchers/actions JSON (e.g. for a "worker" action)
cloudflare email-routing rules create example.com \
  --matchers-json '[{"type":"literal","field":"to","value":"hooks@example.com"}]' \
  --actions-json '[{"type":"worker","value":["my-worker"]}]'

# Update a rule (only the fields provided are changed)
cloudflare email-routing rules update example.com RULE_ID --disabled
cloudflare email-routing rules update example.com RULE_ID --forward-to new-dest@example.net

# Delete a rule
cloudflare email-routing rules delete example.com RULE_ID --force
```

`rules list` follows Cloudflare page metadata (5-50 rows per page); `--filter`
runs client-side before `--limit` (default 100; `--limit 0` returns all pages).
`--enabled` is a server-side filter. Forward actions require exactly one
already-verified destination address (see Destination Addresses below); create
sends one POST attempt and is never replayed on failure.

#### Destination Addresses

Account-scoped. Cloudflare emails a verification link when an address is
added; the address cannot be used as a forward target until that link is
clicked.

```bash
# List destination addresses for an account
cloudflare email-routing addresses list --limit 0
cloudflare email-routing addresses list ACCOUNT_ID --verified false --table
cloudflare email-routing addresses list ACCOUNT_ID --filter "email:contains:gmail"

# Get a single address
cloudflare email-routing addresses get ADDRESS_ID ACCOUNT_ID

# Add a destination address (one POST attempt, never replayed)
cloudflare email-routing addresses create me@gmail.com
cloudflare email-routing addresses create me@gmail.com ACCOUNT_ID

# Delete a destination address
cloudflare email-routing addresses delete ADDRESS_ID ACCOUNT_ID --force
```

The `ACCOUNT` argument is optional on every address/rule command that accepts
it; it defaults to the single account visible to the token.

**API gap:** Cloudflare's Email Routing API has no documented endpoint to
resend a destination address's verification email or to mark an address
verified programmatically (only the dashboard offers "resend verification").
No `verify`/`resend-verification` command is provided for this reason; resend
from the Cloudflare dashboard if the link is lost.

Read commands need the `Zone > Email Routing Rules > Read` (rules), `Zone >
Zone Settings > Read` (settings), or `Account > Email Routing Addresses >
Read` (addresses) permission group on the API token; writes need the matching
`Edit` group.

### Analytics

Zone traffic analytics from the Cloudflare GraphQL Analytics API. The `ZONE`
argument accepts a zone name (e.g. `adamtheautomator.com`) or a 32-character
zone ID.

```bash
# Traffic totals for the last 30 days (page views, unique visitors, requests, bytes)
cloudflare analytics summary example.com

# Totals for an explicit date range
cloudflare analytics summary example.com --start 2026-06-01 --end 2026-06-30
cloudflare analytics summary example.com --table

# Top request paths by HTML page views (adaptive sampled dataset)
cloudflare analytics top-paths example.com
cloudflare analytics top-paths example.com --start 2026-06-01 --end 2026-06-30 --limit 5
cloudflare analytics top-paths example.com --table
cloudflare analytics top-paths example.com --filter "path:contains:blog"
cloudflare analytics top-paths example.com --properties "path,page_views"
```

**Notes:**
- `summary` uses the `httpRequests1dGroups` daily rollup dataset; `unique_visitors`
  is the sum of per-day uniques (not deduplicated across days).
- `top-paths` uses `httpRequestsAdaptiveGroups` filtered to `html` edge responses;
  `pct_of_total` is each path's share of all HTML page views in the range. Data is
  adaptively sampled and retention varies by Cloudflare plan.
- The API token must include the `Analytics: Read` zone permission.

### Workers

Account-level Workers script management. The `ACCOUNT` argument accepts an
account name or a 32-character account ID; omit it when the token can see
exactly one account.

```bash
# List scripts in the account
cloudflare workers list

# List scripts for an explicit account, as a table
cloudflare workers list ACCOUNT_NAME --table
cloudflare workers list --filter "id:contains:cron" --properties "id"

# Download a script's source content
cloudflare workers get my-worker > worker.js
cloudflare workers get my-worker ACCOUNT_NAME --output worker.js

# Upload (create or replace) a script from a file or stdin
cloudflare workers upload my-worker --file ./worker.js
cloudflare workers upload my-worker --file - < worker.js
cloudflare workers upload my-worker --file ./worker.js --compatibility-date 2026-01-15
cloudflare workers upload my-worker --file ./worker.js --format service-worker
cloudflare workers upload my-worker --file ./worker.js \
  --bindings '[{"type":"plain_text","name":"TITLE","text":"hi"}]'

# Delete a script (confirmation prompt; --force skips it)
cloudflare workers delete my-worker --force
```

**Notes:**
- Listing/downloading requires the `Account > Workers Scripts > Read`
  permission on the API token; uploading/deleting requires
  `Account > Workers Scripts > Edit`.
- `--format modules` (default) uploads an ES module with entry file
  `--main-module` (`worker.js` by default); `--format service-worker` uploads
  a single-file service-worker script.
- `--bindings` must be a JSON array of Cloudflare binding objects.

### Pages

Account-level Cloudflare Pages management. The `ACCOUNT` argument accepts an
account name or a 32-character account ID; omit it when the token can see
exactly one account. All endpoints are account-scoped
(`/accounts/{account_id}/pages/...`) and require the `Pages Read` permission
for reads or `Pages Write` for writes on the API token.

#### Pages Projects

```bash
# List projects in the account (JSON default, --table for table)
cloudflare pages projects list
cloudflare pages projects list ACCOUNT_NAME --table
cloudflare pages projects list --filter "name:contains:docs" --properties "name,production_branch"

# Get a single project
cloudflare pages projects get my-site
cloudflare pages projects get my-site ACCOUNT_NAME --table

# Create a project (--production-branch is required)
cloudflare pages projects create my-site --production-branch main
cloudflare pages projects create my-site -b main \
  --config '{"build_config":{"build_command":"npm run build","destination_dir":"dist"}}'

# Update a project (Cloudflare exposes a single PATCH edit endpoint; at least
# one setting is required)
cloudflare pages projects update my-site --production-branch develop
cloudflare pages projects update my-site --build-command "npm run build" --destination-dir dist
cloudflare pages projects update my-site --build-caching false
cloudflare pages projects update my-site --config '{"deployment_configs":{"preview":{"env_vars":{"API_URL":null}}}}'

# Delete a project (confirmation prompt; --force skips it)
cloudflare pages projects delete my-site --force

# Purge cached build artifacts (confirmation prompt; --force skips it)
cloudflare pages projects purge-build-cache my-site --force

# Get the direct-upload token used by wrangler/direct-upload clients
cloudflare pages projects get-upload-token my-site
```

#### Pages Deployments

```bash
# List deployments for a project
cloudflare pages deployments list my-site
cloudflare pages deployments list my-site --env production --table
cloudflare pages deployments list my-site --filter "branch:eq:main" --properties "id,status"

# Get a single deployment
cloudflare pages deployments get my-site DEPLOYMENT_ID

# Start a new deployment from a branch (git-connected projects; defaults to
# the production branch when --branch is omitted)
cloudflare pages deployments create my-site --branch main
cloudflare pages deployments create my-site --commit-message "add docs" --commit-dirty

# Direct-upload deploy of a local directory in one command: hashes every file,
# uploads assets Cloudflare is missing, then creates the deployment.
# This is the full `wrangler pages deploy <dir>` equivalent.
cloudflare pages deployments create my-site --directory ./dist

# Preview-branch direct upload with commit metadata (--branch selects
# production vs preview; production needs no flag)
cloudflare pages deployments create my-site -d ./dist --branch preview \
  --commit-message "docs update"

# Force re-upload of every file even when Cloudflare already stores its hash
cloudflare pages deployments create my-site -d ./dist --skip-caching

# Start a direct-upload deployment from an existing manifest (advanced/manual;
# assets must already be uploaded out-of-band)
cloudflare pages deployments create my-site --manifest '{"/index.html":"<content-hash>"}'

# Retry a failed build
cloudflare pages deployments retry my-site DEPLOYMENT_ID

# Roll production back to a previous successful production deployment
# (confirmation prompt; --force skips it)
cloudflare pages deployments rollback my-site DEPLOYMENT_ID --force

# Delete a deployment (confirmation prompt; --force skips it).
# Pass --allow-aliased to delete aliased non-production deployments.
cloudflare pages deployments delete my-site DEPLOYMENT_ID --allow-aliased --force
```

**Notes / API gaps:**
- The Cloudflare API has **no bulk deployment deletion** endpoint; delete
  deployments one at a time.

**Direct uploads (`--directory`):** `pages deployments create PROJECT
--directory PATH` ships a local folder end to end — no wrangler needed. The
flow mirrors wrangler 4.125.0 exactly: per-file content hash
(`blake3(base64(content) + extension)`, first 32 hex chars), a check-missing
call against the project upload token, batched uploads (≤40 MiB / ≤2000 files
per POST), hash upsert, then the multipart deployment create with the
manifest plus `_headers`/`_redirects` from the directory root. Excluded from
the static asset manifest like wrangler: `_worker.js`, `_redirects`,
`_headers`, `_routes.json`, `functions`, `.wrangler` at the directory root;
`.DS_Store`, `node_modules`, and `.git` at any depth; symlinks are skipped.
Files over the Pages 25 MiB per-file cap are rejected before any upload.
`--manifest` remains available for advanced/manual creates when assets were
already uploaded out-of-band (manifest keys use "/path" form).

**Advanced Mode (`_worker.js`):** when `--directory` contains a root-level
`_worker.js` file, it is uploaded as the deployment's Worker (the
`"_worker.bundle"` multipart part Cloudflare's API expects), activating
Cloudflare Pages Advanced Mode — every request is then routed to the worker,
and Cloudflare stops applying `_headers`/`_redirects` directly (the worker
must reproduce any rules it still needs). Only a single self-contained
`_worker.js` file is supported: it must not `import` another module, because
this command does not bundle it (mirrors wrangler's `--no-bundle` behavior —
no esbuild step is implemented). A `_worker.js/` directory (multi-file
Advanced Mode) or a `functions/` directory with no `_worker.js` (Pages
Functions) both require wrangler's esbuild bundling and are rejected with a
clear error instead of being silently ignored; use `npx wrangler pages
deploy` for those. A root `_routes.json` is uploaded alongside the worker
when present.

#### Pages Domains

```bash
# List custom domains attached to a project (the API returns all domains in
# one response; --limit applies client-side)
cloudflare pages domains list my-site
cloudflare pages domains list my-site --table
cloudflare pages domains list my-site --filter "status:eq:active"

# Get a single domain
cloudflare pages domains get my-site docs.example.com

# Add a custom domain
cloudflare pages domains create my-site docs.example.com

# Retry validation for a domain (reprovision via the PATCH edit endpoint)
cloudflare pages domains update my-site docs.example.com

# Remove a custom domain (confirmation prompt; --force skips it)
cloudflare pages domains delete my-site docs.example.com --force
```

### R2

```bash
cloudflare r2 buckets list --table
cloudflare r2 buckets get BUCKET_NAME ACCOUNT_ID
```

Use `cloudflare r2 buckets --help` and `cloudflare r2 objects --help` for the
bucket and object command groups, including upload and synchronization options.

### Queues

```bash
cloudflare queues list --limit 0
cloudflare queues list ACCOUNT_ID --filter "queue_name:eq:issue-manager" --properties queue_id,queue_name
cloudflare queues get QUEUE_ID ACCOUNT_ID --table
cloudflare queues create issue-manager ACCOUNT_ID
cloudflare queues create regional-work ACCOUNT_ID --jurisdiction eu
```

All queue commands accept an optional account name or ID; omit it only when the
token sees exactly one account. JSON preserves Cloudflare queue fields, including
`queue_id` and `queue_name`. List/get support `--properties/-p` and `--table/-t`;
create also supports table output.

Queues list follows Cloudflare page metadata, matching Wrangler's `page` query
behavior. Filters run before `--limit/-l` (default 100; 0 means all pages).
Create sends one POST attempt, including on timeout or HTTP
5xx. If it fails, inspect `cloudflare queues list ACCOUNT_ID --limit 0` for the
requested name before retrying: the remote write may have succeeded. Creation
does not configure a consumer, buy a plan, or replace existing resources.
Optional jurisdictions are `eu`, `us`, and `fedramp`.

Read operations accept Queues Read/Write or Workers Scripts Read/Write; creation
requires Queues Write or Workers Scripts Write. Successful reads do not prove
write permission.

API references: [list](https://developers.cloudflare.com/api/resources/queues/methods/list/),
[get](https://developers.cloudflare.com/api/resources/queues/methods/get/),
[create](https://developers.cloudflare.com/api/resources/queues/methods/create/).

#### HTTP-pull consumers

```bash
cloudflare queues consumers list QUEUE_ID ACCOUNT_ID --limit 0
cloudflare queues consumers get QUEUE_ID CONSUMER_ID ACCOUNT_ID
cloudflare queues consumers create QUEUE_ID ACCOUNT_ID --batch-size 1 --visibility-timeout-ms 30000
```

Consumer list/get preserve native records and support `--table`, `--properties`,
and account/profile selection. List filters precede the limit; 0 returns all.
The consumer collection endpoint returns an array without pagination metadata.
Create configures only `type: http_pull`. Optional settings are `--batch-size`,
`--max-retries`, `--retry-delay` (seconds), `--visibility-timeout-ms` (milliseconds),
and `--dead-letter-queue` (queue name). Unspecified settings are omitted and
Cloudflare validates setting ranges. Create attempts one POST; inspect consumer
list before retrying a failed or ambiguous create. Existing consumer conflicts
are returned as errors; these commands never remove or replace a consumer.

Configuration enables external HTTP consumption; it does not run a poller or
acknowledge messages. The external consumer needs its own Queues read/write API
token and must pull and acknowledge messages through the native messages API.
Queue expiry and retry exhaustion remain separate from an application's durable
source receipts.

API references: [consumer list](https://developers.cloudflare.com/api/resources/queues/subresources/consumers/methods/list/),
[consumer get](https://developers.cloudflare.com/api/resources/queues/subresources/consumers/methods/get/),
[consumer create](https://developers.cloudflare.com/api/resources/queues/subresources/consumers/methods/create/),
[HTTP-pull configuration](https://developers.cloudflare.com/queues/configuration/pull-consumers/).

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

### JSON Output Example

```bash
cloudflare zones list --limit 2
```

### Table Output Example

```bash
cloudflare zones list --limit 5
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--limit` | `-l` | Maximum number of results (default: 50) |
| `--filter` | `-f` | Filter results (field:value) |
| `--properties` | `-p` | Comma-separated fields to display |
| `--security-level` | `-s` | Set zone security level |
| `--force` | `-F` | Skip confirmation prompts |
| `--version` | `-v` | Show version and exit |

## Configuration

Authentication profile files live under `~/.local/share/cli-tools/cloudflare/authentication_profiles/<profile>/`; non-auth defaults live in `~/.local/share/cli-tools/cloudflare/.env`:

```bash
# API Token (recommended)
CLOUDFLARE_API_TOKEN=your_api_token

# Optional: API base URL
CLOUDFLARE_BASE_URL=https://api.cloudflare.com/client/v4
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### List Zones and Filter with jq

```bash
cloudflare zones list | jq '.[].name'
```

### Export Zones to JSON File

```bash
cloudflare zones list --limit 100 > zones.json
```

### Purge Cache for Multiple Zones

```bash
for zone_id in $(cloudflare zones list | jq -r '.[].id'); do
    cloudflare cache purge "$zone_id" --force
done
```

## Models

This CLI uses Pydantic models for type-safe data handling. All commands return strongly-typed models.

### Available Models

| Model | Description | Required Fields |
|-------|-------------|-----------------|
| `Zone` | Cloudflare zone for list commands | `id`, `name`, `status` |
| `ZoneDetail` | Extended zone for get commands | `id`, `name`, `status` |
| `PurgeResult` | Cache purge result | `id` |

## Shell Completion

You can install shell completion (copy and paste appropriate command):

```bash
# Bash
cloudflare --install-completion bash

# Zsh
cloudflare --install-completion zsh

# Fish
cloudflare --install-completion fish
```

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests
  - pydantic

## License

MIT
