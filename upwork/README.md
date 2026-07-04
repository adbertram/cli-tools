# Upwork CLI

## DESCRIPTION

Use this CLI to search Upwork marketplace job postings through the official GraphQL API and to read or update common freelancer profile attributes. Job search runs on an OAuth2 authorization-code credential; profile commands use a browser session. Live profile reads and writes are currently disabled because Upwork's Cloudflare challenge blocks non-headed automation, but field metadata, update dry-runs, and the GraphQL `jobs` commands still work.

## Docs

- Upwork profile essentials: https://support.upwork.com/hc/en-us/articles/360016252373-How-to-build-your-freelancer-profile-the-essentials
- Upwork profile settings: https://www.upwork.com/freelancers/settings/profile
- Upwork profile page: https://www.upwork.com/freelancers/

## Installation

```bash
cd <cli-tools-root>/upwork
uv tool install -e . --force --refresh
```

After installation, the `upwork` command is available in your terminal.

## Quick Start

```bash
# Authenticate with Upwork in a persistent browser profile
upwork auth login

# Live profile reads return a disabled-due-to-Cloudflare error
upwork profile get

# List supported fields
upwork profile fields list --table

# Preview an update
upwork profile update --dry-run --set title="Automation Consultant"

# Live profile writes return a disabled-due-to-Cloudflare error
upwork profile update --yes --set title="Automation Consultant"
```

## Commands

### Authentication (`upwork auth`)

This CLI has two credential types:

- `browser_session` — persistent browser profile used by `upwork profile` commands.
- `oauth_authorization_code` — OAuth2 token used by `upwork jobs` (the official GraphQL API).

```bash
# Log in to all configured credential types
upwork auth login

# Log in to just the OAuth (GraphQL API) credential
upwork auth login --credential-type oauth_authorization_code

# Log in to just the browser session
upwork auth login --credential-type browser_session

upwork auth login --force
upwork auth status        # makes a live GraphQL call for the OAuth credential
upwork auth refresh       # refresh the OAuth access token
upwork auth test          # verifies the OAuth credential with a live GraphQL call
upwork auth logout
```

**OAuth setup:** create an API key at https://www.upwork.com/developer/keys/apply,
register the redirect URI **exactly** as `http://localhost:8765/callback` (override
with `REDIRECT_URI` in the profile env if you registered a different value), then
run `upwork auth login -c oauth_authorization_code` and paste `CLIENT_ID` /
`CLIENT_SECRET` when prompted. `CLIENT_ID` and `CLIENT_SECRET` are reusable secrets —
never store them in a `.env` file.

### Profiles (`upwork auth profiles`)

```bash
upwork auth profiles list
upwork auth profiles get default
upwork auth profiles select PROFILE_NAME
upwork auth profiles create PROFILE_NAME
upwork auth profiles delete PROFILE_NAME
```

### Profile (`upwork profile`)

```bash
# Disabled: returns a Cloudflare/non-headed automation error
upwork profile get

# Show one field definition without logging in
upwork profile get bio

# Preview updates without changing Upwork
upwork profile update --dry-run --set title="Automation Consultant"

# Disabled: returns a Cloudflare/non-headed automation error
upwork profile update --yes --set title="Automation Consultant" --set hourly_rate=150

# Disabled: returns a Cloudflare/non-headed automation error
upwork profile update --yes --file profile.json

# List supported field metadata
upwork profile fields list

# Filter field metadata
upwork profile fields list --filter "editable:eq:True"

# Show one field by name or alias
upwork profile fields get bio
```

### Jobs (`upwork jobs`)

Search Upwork marketplace job postings via the official GraphQL API
(`marketplaceJobPostingsSearch`). Requires the `oauth_authorization_code`
credential (`upwork auth login -c oauth_authorization_code`). JSON is the default
output and returns the full job node.

```bash
# Free-text search
upwork jobs list --filter "query:eq:python automation" --limit 20

# Filter by skills (comma or pipe separated slugs), sort by most recent
upwork jobs list --filter "skills:eq:python|automation" --sort recency

# Hourly jobs paying at least $50/hr (client-side filters)
upwork jobs list --filter "job_type:eq:hourly" --filter "hourly_min:gte:50"

# Fixed-price jobs within a budget band
upwork jobs list --filter "job_type:eq:fixed" --filter "fixed_min:gte:500" --filter "fixed_max:lte:2000"

# Expert-level jobs for clients in the United States
upwork jobs list --filter "experience_level:eq:expert" --filter "client_location:eq:United States"

# Table view with selected columns
upwork jobs list --filter "query:eq:react" --table --properties "id,title,job_type,totalApplicants"

# Full detail for one posting (by id or ciphertext)
upwork jobs get ~021234567890abcdef
```

**Filter fields:** `query`, `skills`, `category`, `client_location` (server-side);
`job_type` (hourly|fixed), `experience_level` (entry|intermediate|expert),
`fixed_min`, `fixed_max`, `hourly_min`, `hourly_max`, `posted_after` (client-side).
**Sort:** `recency`, `relevance`.

## Supported Profile Fields

| Field | Editable | Notes |
|-------|----------|-------|
| `name` | No | Read from profile page metadata/headings |
| `title` | Yes | Professional headline/title |
| `overview` | Yes | Bio/overview text |
| `hourly_rate` | Yes | Numeric hourly rate |
| `skills` | Yes | List or comma-separated string |
| `categories` | Yes | List or comma-separated string |
| `availability` | Yes | Availability/hours text |
| `languages` | Yes | List or comma-separated string |
| `location` | No | Read-only in this CLI |
| `profile_url` | No | Current profile URL |

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output.
- Add `--properties` / `-p` to restrict returned fields.

## Configuration

Non-authentication configuration is stored in `~/.local/share/cli-tools/upwork/.env`. CLI-managed runtime auth state is stored in the active profile at `~/.local/share/cli-tools/upwork/authentication_profiles/<profile>/.env`. The source repo only carries `.env.example`.

Reusable CLI credentials that agents or scripts need to store/retrieve are governed by the user-level `cli-tool` skill's `references/secrets.md`.

Do not put reusable credentials in any `.env` file. Store and retrieve them through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. `.env` files are limited to non-secret config and CLI-managed runtime auth state.

Root config variables (all non-secret):

```bash
BASE_URL=https://www.upwork.com
HEADLESS=true
CACHE_ENABLED=true
CACHE_TTL=3600
# Optional OAuth redirect URI override (default http://localhost:8765/callback)
REDIRECT_URI=http://localhost:8765/callback
# Optional GraphQL endpoint override (default https://api.upwork.com/graphql)
GRAPHQL_URL=https://api.upwork.com/graphql
```

Browser-auth URLs and selectors are defined in `upwork_cli/browser.py`. The
GraphQL transport (endpoint, retry, error handling) lives in `upwork_cli/graphql.py`,
and the data-driven job filter map lives in `upwork_cli/filters.py`.

## Cloudflare / Bot Challenges

Upwork returns a Cloudflare challenge to the CLI's non-interactive browser
profile. Live profile reads (`upwork profile get`) and writes
(`upwork profile update --yes ...`) are disabled instead of launching a headed
browser or retrying around the challenge.

Never automate, click through, refresh around, or solve a human-verification
challenge.

## Cache

```bash
upwork cache clear
upwork --no-cache profile fields list
```

Browser session data is stored in the active profile data directory for persistence between commands.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Requirements

- Python 3.11+
- Dependencies installed automatically:
  - typer
  - python-dotenv
  - requests
  - cli-tools-shared

## License

MIT
