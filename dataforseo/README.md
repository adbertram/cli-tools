# Dataforseo CLI

## DESCRIPTION

A command-line interface for Dataforseo. DataForSEO API client for keyword research: search volume, keyword difficulty, related keyword ideas, and account balance.

Use this CLI when you need scriptable, JSON-first access to Dataforseo from agents, automation, or terminal workflows.

## Docs

- API documentation: https://docs.dataforseo.com/v3/
- Base URL: https://api.dataforseo.com


## Installation

```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/install-cli-tool.sh --force-refresh dataforseo
```

After installation, the `dataforseo` command will be available in your terminal.

## Quick Start

```bash
# Authenticate with the DataForSEO API login and API password
dataforseo auth login

# Check remaining funds (free)
dataforseo account balance

# Related keyword ideas with volume, difficulty, CPC and intent
dataforseo keywords ideas "powershell" --limit 10 --table
```

## Commands

### Authentication (`dataforseo auth`)

```bash
# Interactive login
dataforseo auth login

# Force re-authentication
dataforseo auth login --force

# Check authentication status
dataforseo auth status

# Run the configured live auth test
dataforseo auth test

# Clear saved credentials/session
dataforseo auth logout
```

### Profiles (`dataforseo auth profiles`)

```bash
# List all profiles
dataforseo auth profiles list

# Show a profile
dataforseo auth profiles get default

# Select the active profile for its auth type
dataforseo auth profiles select PROFILE_NAME

# Create a profile
dataforseo auth profiles create PROFILE_NAME

# Delete a profile
dataforseo auth profiles delete PROFILE_NAME
```

### Keywords (`dataforseo keywords`)

All three commands default to the United States (`--location-code 2840`) and English (`--language-code en`). Each prints the per-call API `cost` (USD) to stderr, for example `cost: $0.0121`, and a result served from the local cache prints `cost: $0 (cached result)`. Any non-20000 DataForSEO status (top level or task level) fails with the API `status_message`.

```bash
# Monthly Google search volume, competition, CPC and 12-month trend (Google Ads, live; $0.09 per request)
dataforseo keywords volume "powershell tutorial" "active directory"

# Same data as a table, restricted to a few fields
dataforseo keywords volume "powershell tutorial" --table
dataforseo keywords volume "powershell tutorial" --properties "keyword,search_volume,cpc"

# Keyword difficulty 0-100 (DataForSEO Labs bulk keyword difficulty, live)
dataforseo keywords difficulty "powershell tutorial" "active directory" --table

# Related keyword ideas (DataForSEO Labs keyword ideas, live)
dataforseo keywords ideas "powershell" --limit 25 --table
dataforseo keywords ideas "powershell" "azure automation" --limit 50 \
  --filter "keyword_info.search_volume:gte:100,keyword_properties.keyword_difficulty:lt:40" \
  --order-by "keyword_info.search_volume,desc" \
  --properties "keyword,keyword_info.search_volume,keyword_properties.keyword_difficulty,keyword_info.cpc,search_intent_info.main_intent"

# Other location or language
dataforseo keywords volume "powershell" --location-code 2826 --language-code en
```

`keywords ideas` is the list-style command: `--limit` and `--order-by` are sent to the API, `--filter` is translated to the DataForSEO `filters` array server-side, and `--properties` projects fields from the full record using dot-notation. Filter fields are the API record paths shown in the JSON output (`keyword_info.search_volume`, `keyword_properties.keyword_difficulty`, `keyword_info.cpc`, `search_intent_info.main_intent`, `keyword`). Supported operators: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `nin` (values separated by `|`), `like`, `ilike`, `contains`, `startswith`, `endswith`. Commas inside one `--filter` mean AND (max 8 conditions). Passing `--filter` more than once is an error because multiple flags mean OR in cli-tools syntax and the API call can only AND.

Output records are the full API records. `keywords volume` returns the Google Ads record (`keyword`, `search_volume`, `competition`, `competition_index`, `cpc`, `low_top_of_page_bid`, `high_top_of_page_bid`, `monthly_searches`, ...). `keywords difficulty` returns `{keyword, keyword_difficulty}`. `keywords ideas` returns Labs items (`keyword`, `keyword_info`, `keyword_properties`, `search_intent_info`, ...). Limits per request: volume 1000 keywords, difficulty 1000 keywords, ideas 200 seeds and `--limit` up to 1000.

Costs (from the account price list): volume $0.09 per request, difficulty and ideas $0.012 per request plus $0.00012 per returned result. The ideas endpoint also returns the seed keyword's own volume, so it is the cheaper way to get volume plus difficulty for one keyword.

### Account (`dataforseo account`)

```bash
# Remaining funds (free)
dataforseo account balance

```

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output.

## AI Instruction Results

Commands that reach a non-deterministic boundary may return an AI instruction result instead of normal resource data. This is JSON on stdout with `type: "ai_instruction"` and tells the calling AI agent what objective to complete, what context is available, what tools are allowed, and what success means.

The CLI must not call an LLM or include required pre-action command lists. Optional `verification_commands` and `follow_up_commands` may appear only for actions to run after the agent completes the instruction.

### JSON Output Example

```bash
dataforseo keywords difficulty "powershell tutorial"
```

```json
[
  {
    "keyword": "powershell tutorial",
    "keyword_difficulty": 41
  }
]
```

### Table Output Example

```bash
dataforseo keywords ideas "powershell" --limit 5 --table
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display data as a table |
| `--limit` | `-l` | Maximum number of results |
| `--filter` | `-f` | Filter results using `field:op:value` syntax |
| `--properties` | `-p` | Restrict output to selected fields |
| `--location-code` |  | DataForSEO location code (default 2840, United States) |
| `--language-code` |  | Language code (default `en`) |
| `--order-by` |  | `keywords ideas` API sort rule, e.g. `keyword_info.search_volume,desc` |
| `--version` | `-v` | Show version and exit |
| `--no-cache` |  | Bypass cached read responses for this execution |

## Configuration

Non-authentication configuration is stored in `~/.local/share/cli-tools/dataforseo/.env`. CLI-managed runtime auth state is stored in the active profile at `~/.local/share/cli-tools/dataforseo/authentication_profiles/<profile>/.env`. The source repo only carries `.env.example`.

Reusable CLI credentials that agents or scripts need to store/retrieve are governed by the user-level `cli-tool` skill's `references/secrets.md`.

Do not put reusable credentials in any `.env` file. Store and retrieve them through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. `.env` files are limited to non-secret config and CLI-managed runtime auth state.

Root config variables:

```bash
# Optional: override the default API base URL
BASE_URL=https://api.dataforseo.com

# Optional: response cache settings
CACHE_ENABLED=true
CACHE_TTL=3600
```

Authentication profile (CLI-managed; holds only secret-manager references):

```bash
ACTIVE=true
USERNAME=secret://dataforseo-username
PASSWORD=secret://dataforseo-password
```

The values are the **API login** and **API password** from the API Access page of the DataForSEO dashboard (not the website password). Store them in the CLI-tools secret manager as `dataforseo-username` and `dataforseo-password`, then run `dataforseo auth login` so the CLI writes the references. DataForSEO rejects paid calls with status `40104` until the account is verified in the user panel (https://app.dataforseo.com/); `account balance` is free and work before verification.

## Cache

```bash
# Clear cached read responses
dataforseo cache clear

# Bypass the cache for one execution
dataforseo --no-cache keywords ideas "powershell" --limit 10
```


## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Client/config/authentication error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### Score a Candidate Post Keyword

```bash
dataforseo keywords ideas "powershell tutorial" --limit 1 \
  --properties "keyword,keyword_info.search_volume,keyword_properties.keyword_difficulty"
```

### Pull Low-Difficulty Ideas as CSV-ready JSON

```bash
dataforseo keywords ideas "powershell" --limit 100 \
  --filter "keyword_properties.keyword_difficulty:lt:30" \
  --properties "keyword,keyword_info.search_volume,keyword_info.cpc" | jq -r '.[] | [.keyword, ."keyword_info.search_volume"] | @csv'
```

### Check Funds Before a Batch

```bash
dataforseo account balance | jq '.balance'
```

## Output Contract

Commands return the DataForSEO result records unmodified (JSON array for `keywords *`, JSON object for `account balance`, which returns `{login, balance, total}` from the free `user_data` endpoint. The per-call `cost` is reported on stderr and is not part of stdout.

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests

## License

MIT
