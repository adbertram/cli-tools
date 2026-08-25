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
manifest plus `_headers`/`_redirects` from the directory root. Ignored like
wrangler: `_worker.js`, `_redirects`, `_headers`, `_routes.json`, `functions`,
`.wrangler` at the directory root; `.DS_Store`, `node_modules`, and `.git` at
any depth; symlinks are skipped. Files over the Pages 25 MiB per-file cap are
rejected before any upload. `--manifest` remains available for advanced/manual
creates when assets were already uploaded out-of-band (manifest keys use
"/path" form).

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
