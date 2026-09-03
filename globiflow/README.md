# Globiflow CLI

## DESCRIPTION

The `globiflow` CLI provides a command-line interface for Globiflow (browser automation).

Use it when you need repeatable access to globiflow workflows that are only available through a signed-in website.

## Installation

```bash
cd globiflow
pip install -e .

# Install Playwright browsers (required once)
playwright install chromium
```

After installation, the `globiflow` command will be available in your terminal.

## Quick Start

```bash
# Login to Globiflow
globiflow auth login

# Check login status
globiflow auth status

# Search for items
globiflow search query "search terms"

# Get item details
globiflow search item ITEM_ID
```

## Commands

### Authentication (`globiflow auth`)

```bash
# Interactive login (opens browser)
globiflow auth login

# Check authentication status
globiflow auth status
globiflow auth status

# Clear stored session
globiflow auth logout
```

### Cache (`globiflow cache`)

```bash
# Show cache status
globiflow cache status

# Clear cached data
globiflow cache clear
```

### Search (`globiflow search`)

```bash
# Search for items (JSON output)
globiflow search query "search terms"

# Search with table format
globiflow search query "search terms"

# Limit results
globiflow search query "search terms" --limit 10

# Get item details
globiflow search item ITEM_ID
globiflow search item https://example.com/item/123

# List all items
globiflow search list
```

### Flows (`globiflow flows`)

```bash
# List all flows
globiflow flows list
globiflow flows list

# Filter flows (client-side)
globiflow flows list --filter "org_name:contains:My Org"
globiflow flows list --filter "enabled:eq:true"

# Limit and select properties
globiflow flows list --limit 10
globiflow flows list --properties "id,name,enabled"

# Get flow details
globiflow flows get FLOW_ID
globiflow flows get FLOW_ID
globiflow flows get FLOW_ID --include-steps

# View flow execution logs
globiflow flows logs FLOW_ID

# Create a new flow
globiflow flows create --app-id 30560419 --trigger C --name "My Flow"
globiflow flows create --app-id 30560419 --trigger U --name "Update Handler" --disabled
globiflow flows create --app-id 30560419 --trigger C --name "With Steps" --steps '[{"action_type": "Custom Variable", "variable_name": "test", "code": "1+1"}]'

# Create a flow with an Update Item / Create Item step that sets Podio
# field values, keyed by field label (not the raw Podio field id)
globiflow flows create --app-id 30560419 --trigger U --name "Set Status" --steps '[{"action_type": "Update Item", "fields": {"Status": "Approved"}}]'
globiflow flows create --app-id 30560419 --trigger C --name "Create Related" --steps '[{"action_type": "Create Item", "app": "Invoices", "fields": {"Amount": "150", "Status": "Draft"}}]'

# Delete a flow
globiflow flows delete FLOW_ID
globiflow flows delete FLOW_ID --force

# Export a flow's XML definition to a file
globiflow flows export FLOW_ID
globiflow flows export FLOW_ID --output /tmp/my-flow.xml

# Import a flow XML into an app
globiflow flows import --app-id 30529466 --file flow-4321944.xml
globiflow flows import --app-id 30529466 --file flow-4321944.xml --table
# An imported flow keeps the source app's field references. Globiflow re-binds
# only the ones it can match in the target app, and its editor refuses to save
# while any reference is unmatched, so import succeeds only into an app whose
# Podio fields cover every field the flow uses. The command names each
# unmatched step and control when the save is refused.

# List one app's flows
globiflow flows list --filter app_id:eq:30529466 --table

# Manage flow steps
globiflow flows steps list FLOW_ID
globiflow flows steps get FLOW_ID STEP_NUMBER
globiflow flows steps add FLOW_ID --action "Add Comment" --comment "Hello world"
globiflow flows steps update FLOW_ID STEP_NUMBER --variable-name "new_name" --code "'expr'"

# Set Podio field values on an Update Item / Create Item step with --fields
# (a JSON object of Podio field label -> value), on both `steps add` and
# `steps update`
globiflow flows steps add FLOW_ID --action "Update Item" --fields '{"Status": "Approved"}'
globiflow flows steps update FLOW_ID STEP_NUMBER --fields '{"Status": "Approved", "Notes": "Reviewed"}'

# Set a Podio app/relationship field by the target item's title -- Globiflow
# searches for it at flow runtime (see below)
globiflow flows steps update FLOW_ID STEP_NUMBER --fields '{"Format": "Blog Post"}'

# Disambiguate which target app to search in, when a Podio app has more than
# one relationship field (Globiflow's target-app picker isn't scoped per
# field -- see below)
globiflow flows steps update FLOW_ID STEP_NUMBER --fields '{"Format": {"app": "Content Formats", "value": "Blog Post"}}'

# Set a multi-value ("multiple") relationship field to more than one item
# with a list of labels -- each becomes its own search row
globiflow flows steps update FLOW_ID STEP_NUMBER --fields '{"Related Content": ["Blog Post", "Whitepaper"]}'

# Clear (unset) any field -- category/status or app/relationship -- with a
# JSON null instead of a value
globiflow flows steps update FLOW_ID STEP_NUMBER --fields '{"Status": null}'
```

**Supported field types for `fields`:** text, number, and other scalar fields
whose value renders as free text; category/status fields (set by option
label, e.g. `"Status": "Approved"`); Podio app/relationship fields (set by
the target item's title/label -- see below). A `null` value clears
(unsets) any of these field types instead of setting one, via Globiflow's
"Unset" function -- fails loudly if a given field type doesn't offer one.

**Relationship fields:** a plain string/number value (e.g.
`{"Format": "Blog Post"}`) is the target item's title to search for.
Globiflow has no "resolve a title to an item ID" control -- it configures a
search *criterion* (target app + field + condition + value) that it
evaluates at flow **runtime**, not when you save the step, so this CLI
cannot pre-validate whether that title matches zero, one, or many items;
that is Globiflow's own runtime behavior. The condition is always set to
"Equal to" (exact match).

Globiflow's target-app picker for this search is a per-Podio-app cache, not
scoped to the specific field you're setting -- confirmed live by querying
its AJAX endpoint directly with two different field ids on the same app and
getting identical results back. For an app with only one relationship field
(or where every relationship field points at the same target app) this is
unambiguous and auto-selected. For an app with several relationship fields
pointing at *different* target apps (e.g. a "Topics" app with fields for
Format, Content, Contacts, etc.), the picker lists every one of those target
apps for any field you pick, and this CLI will not guess which one is
correct -- pass a dict value instead: `{"app": "<Target App Name>", "value":
"<title>"}`. A plain-value call on an ambiguous field fails with a
`ClientError` listing the candidate app names.

If Globiflow's picker offers zero target apps for a field that clearly
should have one, its per-app field/relationship cache is likely stale (a
field created or repointed in Podio moments earlier can be invisible until
that app's "Refresh from Podio" runs on its Globiflow flows.php page) --
refresh it there and retry.

A relationship field's value may also be a **list** of labels, which expands
into one search row per item -- confirmed live that Globiflow's field picker
allows selecting the same field in more than one row, letting a multi-value
("multiple") Podio app field be set to several items in one call.

Not yet supported: a target app whose searchable-field list (the field
Globiflow matches your label against) has more than one candidate -- this
CLI cannot tell which one holds the title, and fails loudly rather than
guessing.

### Triggers (`globiflow triggers`)

```bash
# List all available trigger types
globiflow triggers list
globiflow triggers list

# Filter triggers (client-side)
globiflow triggers list --filter "code:eq:C"
globiflow triggers list --properties "code,name"

# Get trigger details by code
globiflow triggers get C
globiflow triggers get M
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--limit` | `-l` | Maximum number of results (default: 100, client-side) |
| `--filter` | `-f` | Filter results using field:op:value format (client-side) |
| `--properties` | `-p` | Comma-separated list of fields to include in output |
| `--force` | `-F` | Skip confirmation prompts |
| `--version` | `-v` | Show version and exit |

## Configuration

Configuration is stored in `.env` file:

```bash
# Base URL
BASE_URL=https://workflow-automation.podio.com

# Browser settings (true = invisible, false = visible browser)
HEADLESS=true
```

Browser session data is stored in the shared profile data directory for persistence between commands.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Architecture

This CLI uses the **BrowserAutomationService** - a generic browser automation layer that provides:

- **Session Persistence**: Browser context persists between commands (cookies, localStorage)
- **Interactive Login**: Opens browser for manual login, saves session automatically
- **Form Automation**: Fill forms, click buttons, select dropdowns
- **Data Extraction**: Extract tables, lists, and custom data from pages
- **Pagination**: Handle "Load More" buttons and multi-page results
- **Retry Logic**: Automatic retries with exponential backoff

### Customizing for Your Site

1. **Update `client.py`**: Configure `BROWSER_CONFIG` with your site's URLs and selectors
2. **Implement Methods**: Add domain-specific methods (search, list, etc.)
3. **Add Commands**: Create new command files in `commands/` directory

Example site configuration in `client.py`:

```python
BROWSER_CONFIG = BrowserConfig(
    base_url="https://example.com",
    login_url="/login",
    login_check_url="/dashboard",
    login_indicators=["/login", "/signin"],
    logged_in_selector=".user-menu",
    username_selector="input[name='email']",
    password_selector="input[name='password']",
    submit_selector="button[type='submit']",
)
```

## Browser Automation Notes

- **First run**: Run `playwright install chromium` after pip install
- **Headless mode**: Set `HEADLESS=false` to see the browser (useful for debugging)
- **Session persistence**: Login sessions are saved in the shared profile data directory and reused automatically
- **Rate limiting**: Be respectful of the site's terms of service

## Debugging

To debug browser automation issues:

```bash
# Run with visible browser
export HEADLESS=false
globiflow search query "test"
```

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - playwright

## License

MIT
