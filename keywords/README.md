# Keywords CLI

Query autocomplete suggestions from Google, YouTube, Bing, Amazon, and DuckDuckGo for keyword research and SEO analysis.

## Installation

```bash
cd keywords
pip install -e .
```

After installation, the `keywords` command will be available in your terminal.

## Quick Start

```bash
# Get Google suggestions for a query
keywords suggest query "python tutorial"

# Get suggestions from multiple sources
keywords suggest query "best laptop" --source google --source youtube --source amazon

# Display results as a table
keywords suggest query "seo tools" -s google -t

# Filter results containing specific text
keywords suggest query "python" --source google --filter "beginner"

# Recursive querying - build a keyword tree
keywords suggest query "python" --recurse --depth 1
```

## Commands

### Suggest Query

Get autocomplete suggestions for a search query:

```bash
# Basic Google search
keywords suggest query "python"

# YouTube video suggestions
keywords suggest query "how to learn python" --source youtube

# Amazon product suggestions
keywords suggest query "mechanical keyboard" --source amazon

# Bing suggestions
keywords suggest query "weather" --source bing

# DuckDuckGo suggestions
keywords suggest query "privacy browser" --source ddg

# Multiple sources at once
keywords suggest query "best laptop" -s google -s youtube -s amazon

# Table output for easy reading
keywords suggest query "seo" --source google

# Filter suggestions containing text
keywords suggest query "python tutorial" --source google --filter "beginner"

# Recursive querying - get suggestions of suggestions
keywords suggest query "python" --recurse --depth 1

# Recursive with custom depth and limit
keywords suggest query "seo" --recurse --depth 2 --recurse-limit 3

# Recursive with table output
keywords suggest query "machine learning" -r -d 1 -t
```

### List Sources

View available autocomplete sources:

```bash
keywords suggest sources
keywords suggest sources
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

### JSON Output Example

```bash
keywords suggest query "python"
```

```json
[
  {
    "query": "python",
    "source": "google",
    "suggestions": [
      "python download",
      "python coding",
      "python snake",
      ...
    ],
    "count": 15
  }
]
```

### Table Output Example

```bash
keywords suggest query "python" --source google -t
```

```
Source  Suggestion
----------------------------
google  python download
google  python coding
google  python snake
...
```

## Sources

| Source | Flag | Description |
|--------|------|-------------|
| Google | `--source google` | Google web search suggestions |
| YouTube | `--source youtube` | YouTube video search suggestions |
| Bing | `--source bing` | Bing web search suggestions |
| Amazon | `--source amazon` | Amazon product search suggestions |
| DuckDuckGo | `--source ddg` | DuckDuckGo web search suggestions |

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--source` | `-s` | Source to query (can be repeated for multiple sources) |
| `--limit` | `-l` | Maximum suggestions per source (default: 100) |
| `--filter` | `-f` | Filter suggestions containing this text |
| `--recurse` | `-r` | Recursively query suggestions of suggestions |
| `--depth` | `-d` | Recursion depth - how many levels deep (default: 1) |
| `--recurse-limit` | | Max suggestions to recurse into per level (default: 5) |
| `--version` | `-v` | Show version and exit |

## Configuration

No authentication required. The CLI uses public autocomplete APIs.

Optional configuration in `.env`:

```bash
# Delay between requests in seconds (default: 0.1)
KEYWORDS_REQUEST_DELAY=0.1
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | API request error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### Keyword Research for SEO

```bash
# Find related keywords
keywords suggest query "content marketing" -s google -t

# Compare suggestions across platforms
keywords suggest query "productivity apps" -s google -s youtube -s amazon
```

### Export Results for Analysis

```bash
# Save to JSON file
keywords suggest query "python" -s google -s youtube > keywords.json

# Filter and pipe with jq
keywords suggest query "python" | jq '.[].suggestions'
```

### Recursive Keyword Discovery

Build keyword trees by recursively querying suggestions:

```bash
# Get suggestions, then get suggestions for each suggestion (depth 1)
keywords suggest query "python" --recurse --depth 1

# Go deeper with depth 2 (warning: generates many API calls)
keywords suggest query "seo" --recurse --depth 2 --recurse-limit 3

# View recursive results as a table showing parent-child relationships
keywords suggest query "machine learning" -r -d 1 -t
```

**Recursive JSON output structure:**
```json
{
  "query": "python",
  "source": "google",
  "depth": 1,
  "suggestions": [
    {
      "text": "python download",
      "children": [
        {"text": "python download windows", "children": []},
        {"text": "python download mac", "children": []}
      ]
    }
  ],
  "total_count": 60
}
```

### Integration with AI Workflows

```bash
# Get suggestions and pipe to other tools
keywords suggest query "machine learning" -s google | jq -r '.[].suggestions[]'

# Get recursive suggestions and extract all leaf keywords
keywords suggest query "python" -r -d 1 | jq -r '.. | .text? // empty'
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

## Additional Commands

### Cache

```bash
keywords cache --help
```
