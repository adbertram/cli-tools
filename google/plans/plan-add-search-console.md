# Implementation Plan: Add Search Console URL Indexing to Google CLI

## Summary
Add `google searchconsole index <url>` command to request Google to crawl and index a URL via the Search Console URL Inspection API.

**Solution approach:** Create a minimal command module that uses the Search Console API's urlInspection.index.inspect method to request indexing of a given URL.

## Why This Approach
- **Simplest solution**: Single command, minimal code (~50 lines)
- **No new dependencies**: Uses existing Google API client
- **Focused scope**: Just URL indexing, no analytics or sitemaps

## Prerequisites
- Existing Google OAuth2 authentication system (`client.py`)
- Verified Search Console property for the domain

## Implementation Steps

### Step 1: Add Search Console OAuth scope
**File:** `<cli-tools-root>/google/google_cli/client.py`
**Action:** Add webmasters scope to SCOPES list (after calendar.readonly)
```python
"https://www.googleapis.com/auth/webmasters",
```
**Verify:** `grep -n "webmasters" <cli-tools-root>/google/google_cli/client.py`

### Step 2: Add service builder method
**File:** `<cli-tools-root>/google/google_cli/client.py`
**Action:** Add `get_webmasters_service()` method after `get_calendar_service()` (around line 140)
```python
def get_webmasters_service(self):
    """Get Google Search Console (Webmasters) service."""
    return self.get_service("searchconsole", "v1")
```
**Verify:** `grep -A2 "def get_webmasters_service" <cli-tools-root>/google/google_cli/client.py`

### Step 3: Add Search Console site configuration
**File:** `<cli-tools-root>/google/google_cli/config.py`
**Action:** Add `searchconsole_site` property
```python
@property
def searchconsole_site(self) -> Optional[str]:
    """Get Search Console site URL from environment."""
    return os.getenv("GOOGLE_SEARCHCONSOLE_SITE")
```
**Verify:** `grep -A3 "searchconsole_site" <cli-tools-root>/google/google_cli/config.py`

### Step 4: Create searchconsole command module
**File:** `<cli-tools-root>/google/google_cli/commands/searchconsole.py`
**Action:** Create new file with URL indexing command
```python
"""Google Search Console commands."""
import typer
from ..client import get_client
from ..output import print_json, print_success, handle_error
from ..config import get_config

app = typer.Typer(help="Access Google Search Console")


@app.command("index")
def searchconsole_index(
    url: str = typer.Argument(..., help="URL to request indexing for"),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Output as table instead of JSON"
    ),
):
    """Request Google to crawl and index a URL."""
    try:
        client = get_client()
        service = client.get_webmasters_service()
        config = get_config()

        # Get site URL from config
        site_url = config.searchconsole_site
        if not site_url:
            raise ValueError(
                "Search Console site URL not configured. "
                "Set GOOGLE_SEARCHCONSOLE_SITE environment variable."
            )

        # Request indexing via URL inspection API
        response = service.urlInspection().index().inspect(
            body={
                "inspectionUrl": url,
                "siteUrl": site_url
            }
        ).execute()

        # Output result
        result = response.get("inspectionResult", {})
        print_json(result)

        # Show indexing status
        indexing_state = result.get("indexStatusResult", {}).get("verdict", "UNKNOWN")
        print_success(f"URL inspection complete. Status: {indexing_state}")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("sites")
def searchconsole_sites(
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Output as table instead of JSON"
    ),
):
    """List verified Search Console sites."""
    try:
        client = get_client()
        service = client.get_webmasters_service()

        # List sites
        response = service.sites().list().execute()
        sites = response.get("siteEntry", [])

        # Output
        if table:
            from ..output import print_table
            columns = ["siteUrl", "permissionLevel"]
            headers = ["Site URL", "Permission Level"]
            print_table(sites, columns, headers)
        else:
            print_json(sites)

    except Exception as e:
        raise typer.Exit(handle_error(e))
```
**Verify:** `python -c "import ast; ast.parse(open('<cli-tools-root>/google/google_cli/commands/searchconsole.py').read())"`

### Step 5: Register searchconsole command in main
**File:** `<cli-tools-root>/google/google_cli/main.py`
**Action:**
1. Add import (alphabetically between gmail and sheets): `searchconsole`
2. Add registration (alphabetically): `app.add_typer(searchconsole.app, name="searchconsole", help="Access Google Search Console")`
**Verify:** `google --help | grep searchconsole`

### Step 6: Update commands __init__.py
**File:** `<cli-tools-root>/google/google_cli/commands/__init__.py`
**Action:** Add searchconsole to imports
**Verify:** `cat <cli-tools-root>/google/google_cli/commands/__init__.py`

### Step 7: Update README with searchconsole command
**File:** `<cli-tools-root>/google/README.md`
**Action:** Add searchconsole section with:
- Configuration instructions for `GOOGLE_SEARCHCONSOLE_SITE`
- Command examples: `google searchconsole index <url>`
- Command example: `google searchconsole sites`
**Verify:** Manual review

### Step 8: Reinstall CLI and test
**Action:**
1. Reinstall: `cd <cli-tools-root>/google && source venv/bin/activate && pip install -e .`
2. Delete existing token: `rm ~/.config/google-cli/token.json` (if exists)
3. Test sites command: `google searchconsole sites`
4. Test index command: `google searchconsole index https://example.com/page`
**Verify:** Commands execute without errors

## Testing Strategy

**Manual Testing:**
1. Run `google searchconsole sites` to verify API connection
2. Run `google searchconsole index <url>` with valid URL

**Error Testing:**
1. Missing site URL configuration - should show helpful error
2. Invalid URL format - API should return error
3. URL not under verified property - API should return 403

## Success Criteria
- [ ] Command `google searchconsole index <url>` requests indexing
- [ ] Command `google searchconsole sites` lists verified sites
- [ ] Missing site URL configuration shows helpful error message
- [ ] OAuth flow grants webmasters scope successfully
- [ ] README documents configuration and usage
