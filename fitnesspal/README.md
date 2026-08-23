# Fitnesspal CLI

## DESCRIPTION

The `fitnesspal` CLI provides a command-line interface for Fitnesspal API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Installation

```bash
cd fitnesspal
./install.sh
```

After installation, the `fitnesspal` command will be available in your terminal.

## Authentication

This CLI uses your browser's MyFitnessPal cookies for authentication. No API keys or tokens needed.

1. Log in to [myfitnesspal.com](https://www.myfitnesspal.com/) in your web browser
2. Run `fitnesspal auth status` to verify

```bash
# Check authentication status
fitnesspal auth status
fitnesspal auth status --table
```

## Commands

### Auth

```bash
# Check if browser cookies are available
fitnesspal auth status
fitnesspal auth status --table
```

### Diary

```bash
# Get today's food diary
fitnesspal diary get
fitnesspal diary get today

# Get diary for a specific date
fitnesspal diary get yesterday
fitnesspal diary get 2024-01-15

# Table format
fitnesspal diary get --table
```

### Exercises

```bash
# Get today's exercises
fitnesspal exercises get
fitnesspal exercises get today

# Get exercises for a specific date
fitnesspal exercises get yesterday
fitnesspal exercises get 2024-01-15

# Table format
fitnesspal exercises get --table
```

### Measurements

```bash
# List weight measurements
fitnesspal measurements list
fitnesspal measurements list --measurement Weight

# List body fat measurements
fitnesspal measurements list --measurement "Body Fat"

# Filter by date range
fitnesspal measurements list --from 2024-01-01 --to 2024-01-31

# Table format with limit
fitnesspal measurements list --table --limit 10

# Filter measurements
fitnesspal measurements list --filter "value:gt:150"

# Select specific fields
fitnesspal measurements list --properties "date,value"
```

### Reports

```bash
# Get net calories report
fitnesspal reports get
fitnesspal reports list --name "Net Calories"

# Get total calories report
fitnesspal reports list --name "Total Calories" --category Nutrition

# Filter by date range
fitnesspal reports list --from 2024-01-01 --to 2024-01-31

# Table format with limit
fitnesspal reports list --table --limit 7

# Filter report values
fitnesspal reports list --filter "value:gt:1500"
```

### Food

```bash
# Search the food database
fitnesspal food search "chicken breast"
fitnesspal food search banana --table
fitnesspal food search "greek yogurt" --limit 5

# Filter search results
fitnesspal food search "protein bar" --filter "verified:true"

# Select specific fields
fitnesspal food search rice --properties "mfp_id,name,calories"

# Get food item details
fitnesspal food get 12345
fitnesspal food get 12345 --table
```

### Recipes

```bash
# List all saved recipes
fitnesspal recipes list
fitnesspal recipes list --table
fitnesspal recipes list --limit 10

# Filter recipes
fitnesspal recipes list --filter "name:contains:chicken"

# Get recipe details
fitnesspal recipes get 12345
fitnesspal recipes get 12345 --table
```

### Meals

```bash
# List all saved meals
fitnesspal meals list
fitnesspal meals list --table
fitnesspal meals list --limit 10

# Filter saved meals
fitnesspal meals list --filter "name:contains:lunch"

# Get saved meal details (requires both ID and title)
fitnesspal meals get 12345 "My Lunch"
fitnesspal meals get 12345 "My Lunch" --table
```

### Cache

```bash
# Clear cached responses
fitnesspal cache clear
```

### Profiles

```bash
# List authentication profiles
fitnesspal auth profiles list

# Create a new profile
fitnesspal auth profiles create myprofile

# Select active profile
fitnesspal auth profiles select myprofile

# Delete a profile
fitnesspal auth profiles delete myprofile
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping
- **Table** (`--table` / `-t`): Human-readable table format

### JSON Output Example

```bash
fitnesspal diary get today | jq '.totals'
```

### Table Output Example

```bash
fitnesspal diary get --table
```

## Options Reference

### Global Options

| Option | Short | Description |
|--------|-------|-------------|
| `--version` | `-v` | Show version and exit |
| `--help` | | Show help and exit |

### List Command Options

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display as table |
| `--limit` | `-l` | Maximum number of results (default: 100) |
| `--filter` | `-f` | Filter results (field:op:value) |
| `--properties` | `-p` | Comma-separated fields to include |

### Get Command Options

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display as table |

## Filter Syntax

Filters use the format `field:operator:value`:

| Operator | Description | Example |
|----------|-------------|---------|
| `eq` (default) | Equals | `--filter "verified:true"` |
| `ne` | Not equals | `--filter "brand:ne:Generic"` |
| `gt` | Greater than | `--filter "value:gt:150"` |
| `gte` | Greater than or equal | `--filter "calories:gte:200"` |
| `lt` | Less than | `--filter "value:lt:200"` |
| `lte` | Less than or equal | `--filter "calories:lte:100"` |
| `contains` | Contains string | `--filter "name:contains:chicken"` |
| `startswith` | Starts with | `--filter "name:startswith:Protein"` |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Requirements

- Python 3.9+
- A web browser logged in to MyFitnessPal
- Dependencies (installed automatically):
  - typer
  - myfitnesspal
  - pydantic

## License

MIT
