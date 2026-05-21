# Technical Research: Add Search Console Command

## Files Analyzed

| File | Key Functions/Classes | Relevant Lines | Purpose |
|------|----------------------|-----------------|---------|
| `client.py` | `GoogleClient`, `get_client()`, `retry_with_exponential_backoff()` | 14-21 (SCOPES), 75-150 (service builders) | OAuth2 authentication, service factory pattern, retry logic with exponential backoff |
| `config.py` | `Config`, `get_config()` | 1-48 (full file) | Configuration management for credentials and token paths; loads from .env |
| `filter_translator.py` | `translate_gmail_filters()`, `translate_drive_filters()`, `translate_calendar_filters()` | 55-253 (all translators) | Pattern for converting CLI filters (field:op:value) to API-specific syntax |
| `output.py` | `print_json()`, `print_table()`, `handle_error()`, `_format_cell_value()` | 131-184 (output functions), 108-128 (table creation with HEAVY_HEAD box) | Standardized output handling, table formatting with Rich |
| `main.py` | `app`, registration pattern, import order | 14-22 (command registration) | Typer app setup, alphabetical import and registration pattern |
| `commands/drive.py` | `drive_list()`, `drive_get()`, `drive_search()` | 11-163 (command structure) | Example of list command with filters, properties selection, table output |
| `commands/gmail.py` | `app`, `labels_app`, sub-typer pattern | 18-20 (sub-typer setup), 845-961 (sub-commands) | Nested command structure using Typer sub-apps (model for analytics subcommand) |
| `commands/calendar.py` | `calendar_list()`, date range handling | 12-89 (list command with date logic) | Date range calculation pattern (datetime + timedelta), filter integration |
| `filters.py` | `OPERATORS`, `parse_filter_with_aliases()` | 10-52 (filter parsing) | Standard filter validation and parsing supporting operators: eq, ne, gt, gte, lt, lte, in, nin, like, ilike |

## APIs/Tools Verified

| Tool/API | Method/Endpoint | Expected Signature | Verified Notes |
|----------|-----------------|-------------------|----------------|
| Google Search Console API | `webmasters().sites().list()` | `service.webmasters().sites().list(siteUrl=None).execute()` | Returns verified sites; required to know which site to query |
| Google Search Console API | `searchanalytics().query()` | `service.searchanalytics().query(siteUrl='...', body={...}).execute()` | Core method for analytics queries; requires siteUrl and query body with startDate, endDate, dimensions, metrics |
| Google Client | `get_service(service_name, version)` | `get_service("webmasters", "v3")` → service object | Method builder pattern used for all Google APIs |
| Python datetime | `datetime.utcnow()` | Returns current UTC datetime | Used in calendar.py for date calculations |
| Typer sub-apps | `app.add_typer(sub_app, name="...")` | Nesting pattern from gmail.py | Creates command hierarchy like `google searchconsole analytics query` |

## Integration Map

```
┌─────────────────────────────────────────────────────────┐
│ google_cli/main.py                                      │
│ • Import: from .commands import searchconsole          │
│ • Register: app.add_typer(searchconsole.app,           │
│   name="searchconsole", help="...")                     │
│ (Alphabetical: auth, calendar, docs, drive,            │
│  gmail, SEARCHCONSOLE, sheets)                          │
└──────────────────────┬──────────────────────────────────┘
                       │ imports & registers
                       ▼
┌─────────────────────────────────────────────────────────┐
│ google_cli/commands/searchconsole.py                    │
├─────────────────────────────────────────────────────────┤
│ • app = typer.Typer(help="...")                         │
│ • analytics_app = typer.Typer(help="...")              │
│ • app.add_typer(analytics_app, name="analytics")       │
│                                                         │
│ @analytics_app.command("query")                        │
│ def searchconsole_analytics_query(...)                 │
└──────────────┬──────────────────┬──────────────────────┘
               │ imports          │
       ┌───────▼────────┐        │
       │ client.py      │        │
       │ get_client()   │        │
       │ HttpError      │        │
       └────────────────┘        │
                                 │
                 ┌───────────────▼─────────────────┐
                 │ filter_translator.py            │
                 │ translate_searchconsole_filters│
                 └───────────────────────────────┘
                                 │
                 ┌───────────────▼─────────────────┐
                 │ output.py                       │
                 │ print_json(), print_table(),   │
                 │ handle_error(), print_success() │
                 └───────────────────────────────┘
```

## Patterns to Follow

### 1. OAuth Scope Pattern (client.py:14-21)
- Add to SCOPES list: `"https://www.googleapis.com/auth/webmasters"`
- Single scope covers full Search Console access

### 2. Service Builder Pattern (client.py:122-140)
```python
def get_webmasters_service(self):
    """Get Google Search Console (Webmasters) service."""
    return self.get_service("webmasters", "v3")
```

### 3. Command Structure Pattern (drive.py:11-53)
```python
@app.command("command_name")
def function_name(
    limit: int = typer.Option(...),
    table: bool = typer.Option(...),
    filter: Optional[List[str]] = typer.Option(...),
    properties: Optional[List[str]] = typer.Option(...),
):
    """Docstring."""
    try:
        client = get_client()
        service = client.get_webmasters_service()

        # Build query from filters
        query = translate_searchconsole_filters(filter) if filter else None

        # API call
        results = service.searchanalytics().query(...).execute()

        # Output
        if table:
            print_table(results, columns, headers)
        else:
            print_json(results)

    except Exception as e:
        raise typer.Exit(handle_error(e))
```

### 4. Sub-Typer Pattern (gmail.py:18-20)
```python
app = typer.Typer(help="Access Google Search Console")
analytics_app = typer.Typer(help="Query search analytics")
app.add_typer(analytics_app, name="analytics")

@analytics_app.command("query")
def searchconsole_analytics_query(...):
    ...
```

### 5. Filter Translation Pattern (filter_translator.py)
- Accept filters as `Optional[List[str]]`
- Parse with standard format: `field:operator:value`
- Create `translate_searchconsole_filters()` function
- Search Console API format: `{"dimension":"...","operator":"...","expression":"..."}`

### 6. Date Range Pattern (calendar.py)
```python
from datetime import datetime, timedelta

# For Search Console: use YYYY-MM-DD format
start_date = (datetime.utcnow() - timedelta(days=28)).strftime("%Y-%m-%d")
end_date = datetime.utcnow().strftime("%Y-%m-%d")
```

### 7. Table Output Pattern (output.py)
```python
if table:
    table_cols = ['query', 'clicks', 'impressions', 'ctr', 'position']
    table_headers = ['Query', 'Clicks', 'Impressions', 'CTR', 'Position']
    print_table(results, table_cols, table_headers)
```

## Search Console API Specifics

### Query Body Structure:
```python
{
    'startDate': 'YYYY-MM-DD',
    'endDate': 'YYYY-MM-DD',
    'dimensions': ['query', 'page', 'country', 'device', 'searchAppearance'],
    'rowLimit': 25000,
    'startRow': 0
}
```

### Dimension Values:
- `query` - Search queries
- `page` - Landing pages
- `country` - Geographic location
- `device` - Desktop/mobile/tablet
- `searchAppearance` - Featured snippet, rich result, etc.

### Default Metrics (all 4 returned):
- `clicks` - Number of clicks
- `impressions` - Number of impressions
- `ctr` - Click-through rate (0-1)
- `position` - Average position (1-100+)

## Configuration Storage

Based on config.py pattern:
1. **Environment variable**: `GOOGLE_SEARCHCONSOLE_SITE`
2. **Config file property**: `.env` file in project root

```python
@property
def searchconsole_site(self) -> Optional[str]:
    """Get Search Console site URL from environment or config."""
    return os.getenv("GOOGLE_SEARCHCONSOLE_SITE")
```

## Key Implementation Notes

1. **Site URL Requirement**: Search Console API requires fully verified site URL (e.g., `https://example.com/`)
2. **Validation Command**: Add `sites list` command to check verification status
3. **Flexible Dimensions**: User specifies dimensions via flag
4. **Metrics Default**: All 4 metrics returned by default
5. **Date Format**: Search Console uses YYYY-MM-DD (not ISO 8601)
6. **Table Columns**: Fixed 5 columns (query, clicks, impressions, ctr, position)
7. **Retry Logic**: Inherit from client.py's `retry_with_exponential_backoff()` for rate limit handling
