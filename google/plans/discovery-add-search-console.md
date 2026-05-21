# Discovery: Add Search Console Command to Google CLI

## Codebase Context

### Key Files

**Core Infrastructure:**
- `google_cli/client.py` - OAuth2 authentication with SCOPES list (lines 14-21), service builders (lines 107-140)
- `google_cli/main.py` - Main Typer app with subcommand registration (lines 17-22)
- `google_cli/output.py` - Standardized output: `print_json()`, `print_table()`, `print_success()`, `print_error()` with Rich tables
- `google_cli/filter_translator.py` - Filter translation pattern for converting standard CLI filters to API-specific query syntax
- `google_cli/config.py` - Configuration management for credentials and token paths

**Existing Commands:**
- `google_cli/commands/drive.py` - File listing/search with filters, properties selection, table output
- `google_cli/commands/gmail.py` - Message operations with label support, filter translation, sub-typers for labels
- `google_cli/commands/sheets.py` - Spreadsheet operations using Drive API for listing, Sheets API for data
- `google_cli/commands/docs.py` - Document management
- `google_cli/commands/calendar.py` - Read-only calendar access

### Existing Patterns

**Authentication Pattern:**
- SCOPES defined globally in `client.py:14-21`
- Search Console requires: `https://www.googleapis.com/auth/webmasters` (full access)
- Service access via `get_client().get_service("webmasters", "v3")`

**Command Structure Pattern (drive.py:11-53):**
- Typer app with descriptive help
- Commands use decorators: `@app.command("list")`
- Try/except with `HttpError` handling
- Output via `print_json()` or `print_table()`

**Filter Translation Pattern (filter_translator.py):**
- Supports both standard format (`field:op:value`) and native API format
- Each API has dedicated translator function: `translate_gmail_filters()`, `translate_drive_filters()`
- Maps CLI operators to API-specific query syntax

**Output Pattern:**
- Default: JSON to stdout for piping
- `--properties` flag: Select which fields to display
- Success/error messages to stderr

**Service Registration (main.py:15-22):**
- Import command module
- Register with `app.add_typer(module.app, name="...", help="...")`

## Q&A Results

### Wave: Clarify Task

**Q:** The Google Search Console API is called 'webmasters' in the API client. Should the CLI command be 'google search', 'google searchconsole', or 'google webmasters'?
**A:** google searchconsole

**Q:** Search Console has multiple capabilities (search analytics, URL inspection, sitemaps, sites). Should this command cover all of them or focus only on search analytics?
**A:** Search analytics only

**Q:** Following the pattern in gmail.py with sub-typers, should we use subcommands like 'google search analytics query' or keep it flat like 'google search query'?
**A:** Nested: google search analytics query

**Q:** For search analytics queries, what should be the primary use case: query performance analysis, page performance analysis, or both equally?
**A:** Flexible/both - Require explicit dimension selection via flags

### Wave: Success Criteria

**Q:** What date range should be the default for search analytics queries?
**A:** Last 28 days

### Wave: Technical Decisions

**Q:** The Search Console API requires a verified site property. Should this be an argument, environment variable, or both?
**A:** Config file - Store in config.py like credentials_path

**Q:** Which Search Console API scope should we add to client.py SCOPES?
**A:** webmasters (full access)

**A:** Follow exactly - Use --limit, --table, --filter, --properties like other commands

**Q:** Search Console allows filtering by dimensions. Should we create a translate_search_filters() function in filter_translator.py or use native API format?
**A:** Create translator - Standard field:op:value format with translation

**Q:** The Search Console API returns metrics (clicks, impressions, ctr, position). Should all be returned by default or allow selection?
**A:** All by default - Return all 4 metrics unless --metrics specified

### Wave: Integration Impact

**Q:** Following main.py registration pattern, where should the import go?
**A:** Alphabetical - Insert alphabetically: auth, calendar, docs, drive, gmail, searchconsole, sheets

**Q:** Should we create get_search_console_service() or get_webmasters_service()?
**A:** get_webmasters_service - Matches API name, consistent with API docs

### Wave: Implementation Preferences

**Q:** Following output.py pattern, should table output use the same Rich table style?
**A:** Same as other commands - Use HEAVY_HEAD box, auto-discover columns

**Q:** Should the default table columns for search analytics show dynamic or fixed columns?
**A:** query, clicks, impressions, ctr, position - 5 key columns for query analysis

**Q:** Following drive.py error handling, should we catch HttpError separately or use handle_error()?
**A:** handle_error only - Let handle_error() handle all exceptions uniformly

**Q:** Should we validate site ownership before querying or let the API error handle it?
**A:** Need a validate command - Create a command to check site verification status

## Key Decisions

1. **Command Name:** `google searchconsole` (matches Google's product branding)
2. **Scope:** Search analytics only (focus on searchanalytics.query())
3. **Structure:** Nested subcommands - `google searchconsole analytics query`
4. **API Scope:** Full `webmasters` scope for future extensibility
5. **Site Config:** Stored in config.py (SEARCH_CONSOLE_SITE or similar)
6. **Date Default:** Last 28 days for trend analysis
8. **Filter Translation:** Create `translate_searchconsole_filters()` function
9. **Metrics:** All 4 metrics by default (clicks, impressions, ctr, position)
10. **Import Order:** Alphabetical in main.py
11. **Service Method:** `get_webmasters_service()`
12. **Table Style:** Same HEAVY_HEAD box as other commands
13. **Default Columns:** query, clicks, impressions, ctr, position
14. **Error Handling:** Use handle_error() uniformly
15. **Validation:** Add a dedicated command to check site verification status
16. **Dimensions:** Flexible - require explicit --dimensions flag
