# Scrunch CLI

A command-line interface for the [Scrunch AI API](https://scrunchai.com). Brand visibility, AI search analytics, competitors, personas, prompts, and agent traffic.

## Installation

```bash
cd scrunch
pip install -e .
```

After installation, the `scrunch` command will be available in your terminal.

## Quick Start

```bash
# Authenticate with Scrunch
scrunch auth login --api-key YOUR_API_KEY

# Check authentication status
scrunch auth status

# List brands
scrunch brands list

# Get a specific brand
scrunch brands get 123
```

## Command Tree

```
scrunch
├── auth
│   ├── login          # Authenticate with API key
│   ├── status         # Check authentication status
│   └── logout         # Clear stored credentials
├── brands
│   ├── list           # List all brands
│   ├── get            # Get brand details
│   ├── create         # Create a new brand
│   ├── update         # Update a brand
│   └── delete         # Archive a brand
├── competitors
│   ├── list           # List competitors for a brand
│   ├── get            # Get competitor details
│   ├── create         # Create a competitor
│   ├── update         # Update a competitor
│   └── delete         # Archive a competitor
├── personas
│   ├── list           # List personas for a brand
│   ├── get            # Get persona details
│   ├── create         # Create a persona
│   ├── update         # Update a persona
│   └── delete         # Archive a persona
├── prompts
│   ├── list           # List prompts for a brand
│   ├── get            # Get prompt details
│   ├── create         # Create a prompt
│   └── delete         # Archive a prompt
├── query
│   └── metrics        # Query aggregated metrics
├── responses
│   └── list           # List AI responses
├── page-audits
│   ├── list           # List page audits
│   ├── get            # Get page audit details
│   └── create         # Create a page audit
├── agent-traffic
│   └── get            # Get agent traffic data
├── cache
│   └── clear          # Clear cached data
└── auth
    └── profiles
        ├── list       # List profiles
        ├── create     # Create a profile
        └── set-default # Switch default profile
```

## Commands

### Authentication

```bash
# Login with API key
scrunch auth login
scrunch auth login --api-key YOUR_API_KEY

# Check authentication status
scrunch auth status

# Clear stored credentials
scrunch auth logout
```

### Brands

```bash
# List all brands
scrunch brands list
scrunch brands list --table
scrunch brands list --limit 10
scrunch brands list --filter "status:eq:active"
scrunch brands list --properties "id,name,website"

# Get a specific brand
scrunch brands get 123
scrunch brands get 123 --table
scrunch brands get 123 --properties "id,name"

# Create a brand
scrunch brands create --name "My Brand" --website "https://example.com" --description "Brand description"
scrunch brands create --name "My Brand" --website "https://example.com" --description "Brand description" --key-topics "ai,ml"

# Update a brand
scrunch brands update 123 --name "New Name"
scrunch brands update 123 --status "active"

# Delete (archive) a brand
scrunch brands delete 123
```

### Competitors

```bash
# List competitors for a brand
scrunch competitors list 123
scrunch competitors list 123 --table
scrunch competitors list 123 --filter "name:contains:acme"

# Get a specific competitor
scrunch competitors get 123 456

# Create a competitor
scrunch competitors create 123 --name "Competitor Inc" --websites "https://competitor.com"

# Update a competitor
scrunch competitors update 123 456 --name "New Name"

# Delete (archive) a competitor
scrunch competitors delete 123 456
```

### Personas

```bash
# List personas for a brand
scrunch personas list 123
scrunch personas list 123 --table

# Get a specific persona
scrunch personas get 123 456

# Create a persona
scrunch personas create 123 --name "Developer" --description "Software developer persona"

# Update a persona
scrunch personas update 123 456 --name "New Name"

# Delete (archive) a persona
scrunch personas delete 123 456
```

### Prompts

```bash
# List prompts for a brand
scrunch prompts list 123
scrunch prompts list 123 --table
scrunch prompts list 123 --limit 50 --offset 100

# Get a specific prompt
scrunch prompts get 123 456

# Create a prompt
scrunch prompts create 123 --text "What is the best AI tool?" --stage Awareness
scrunch prompts create 123 --text "Compare AI tools" --stage Comparison --platforms "chatgpt,claude"

# Delete (archive) a prompt
scrunch prompts delete 123 456
```

### Query (Aggregated Metrics)

```bash
# Query metrics for a brand
scrunch query metrics 123 --start-date 2025-01-01 --end-date 2025-03-31
scrunch query metrics 123 --fields "date,ai_platform,brand_presence_percentage" --table
scrunch query metrics 123 --limit 500 --offset 0
scrunch query metrics 123 --start-date 2025-01-01 --end-date 2025-03-31 --filter "ai_platform:eq:chatgpt"
```

Available dimensions: date, date_week, date_month, date_quarter, date_year, prompt_id, prompt, persona_id, persona_name, ai_platform, ai_platform_search_enabled, tag, source_url, source_type, competitor_id, competitor_name, branded, stage, prompt_topic, country

Available metrics: responses, brand_presence_percentage, brand_position_score, brand_sentiment_score, competitor_presence_percentage, competitor_position_score, competitor_sentiment_score

### Responses (AI Responses)

```bash
# List AI responses for a brand
scrunch responses list 123
scrunch responses list 123 --platform chatgpt --table
scrunch responses list 123 --start-date 2025-01-01 --end-date 2025-03-31
scrunch responses list 123 --stage Awareness --limit 50
scrunch responses list 123 --prompt-id 456 --persona-id 789
```

### Page Audits

```bash
# List page audits for a brand
scrunch page-audits list 123
scrunch page-audits list 123 --status completed
scrunch page-audits list 123 --url "https://example.com/page"

# Get a specific page audit
scrunch page-audits get 123 456

# Create a page audit
scrunch page-audits create 123 --url "https://example.com/page"
```

### Agent Traffic

```bash
# Get agent traffic for a brand's site
scrunch agent-traffic get 123 789 --start-date 2025-01-01 --end-date 2025-03-31
scrunch agent-traffic get 123 789 --start-date 2025-01-01 --end-date 2025-03-31 --table
scrunch agent-traffic get 123 789 --start-date 2025-01-01 --end-date 2025-03-31 --time-bucket day
scrunch agent-traffic get 123 789 --start-date 2025-01-01 --end-date 2025-03-31 --path "/blog"
```

## Output Formats

All list/get commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping
- **Table** (`--table` / `-t`): Human-readable table format

### Common Options

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display output as table |
| `--limit` | `-l` | Maximum number of results |
| `--filter` | `-f` | Filter results (field:op:value) |
| `--properties` | `-p` | Comma-separated fields to include |
| `--offset` | `-o` | Pagination offset (where supported) |

### Filter Operators

| Operator | Description | Example |
|----------|-------------|---------|
| `eq` | Equals (default) | `--filter "status:active"` |
| `ne` | Not equals | `--filter "status:ne:archived"` |
| `contains` | Contains substring | `--filter "name:contains:acme"` |
| `gt` / `gte` | Greater than / or equal | `--filter "id:gt:100"` |
| `lt` / `lte` | Less than / or equal | `--filter "id:lt:50"` |
| `in` | In list | `--filter "status:in:active\|pending"` |
| `null` / `notnull` | Null check | `--filter "description:notnull"` |

## Configuration

Credentials are stored in a `.env` file in the package directory:

```bash
# API Key
API_KEY=your_api_key_here

# Optional: API base URL
BASE_URL=https://api.scrunchai.com/v1
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Models

This CLI uses Pydantic models for type-safe data handling. All commands return strongly-typed models.

### Available Models

| Model | Description | Key Fields |
|-------|-------------|------------|
| `Brand` | Brand entity | `id`, `name`, `website`, `status` |
| `Competitor` | Brand competitor | `id`, `name`, `websites` |
| `Persona` | Brand persona | `id`, `name`, `description` |
| `Prompt` | Prompt definition | `id`, `text`, `stage`, `platforms` |
| `QueryResult` | Aggregated metric row | dimensions + metrics |
| `ResponseListing` | AI response data | `id`, `platform`, `text`, `brand_mentioned` |
| `PageAuditRecord` | Page audit record | `id`, `url`, `status` |
| `AgentTrafficRow` | Traffic data row | `requests`, `date`, `agent_source` |

### Model Architecture

```
models/
├── __init__.py          # Exports all models
├── base.py              # CLIModel base class
├── brand.py             # Brand, CreateBrand, UpdateBrand
├── competitor.py        # Competitor, CreateCompetitor, UpdateCompetitor
├── persona.py           # Persona, CreatePersona, UpdatePersona
├── prompt.py            # Prompt, CreatePrompt, PromptStage, AIPlatform
├── query.py             # QueryResult, QueryResponse
├── response.py          # ResponseListing
├── page_audit.py        # PageAuditRecord, CreatePageAudit
└── agent_traffic.py     # AgentTrafficRow, AgentTrafficResponse
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
