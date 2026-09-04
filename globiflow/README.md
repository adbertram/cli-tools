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

# Enable or disable an existing flow (exactly one of --enabled/--disabled
# is required); prints the flow's resulting record, same shape as `flows get`
globiflow flows update FLOW_ID --disabled
globiflow flows update FLOW_ID --enabled
globiflow flows update FLOW_ID --enabled --table

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

# Chain 2+ steps in one `flows create --steps` call, including one step
# referencing a variable an earlier step in the same call creates
globiflow flows create --app-id 30560419 --trigger C --name "Chained" --steps '[{"action_type": "Custom Variable", "variable_name": "myvar1", "code": "1+1"}, {"action_type": "Custom Variable", "variable_name": "myvar2", "code": "[(Variable) myvar1] + 1"}]'

# Field-less logic steps -- End If (closes an If (Sanity Check) block) and
# Continue (ends a For Each loop early) -- take no other options
globiflow flows steps add FLOW_ID --action "If (Sanity Check)" --code "[*status*] == 'new'"
globiflow flows steps add FLOW_ID --action "End If"
globiflow flows steps add FLOW_ID --action "For Each"
globiflow flows steps add FLOW_ID --action "Continue"

# "Get Referenced Item(s)" collector step: target app, relationship
# direction, and (optionally) the specific relationship field to follow, via
# --params. `using_field` is the field's full option label as Globiflow
# renders it, "(ItemName) FieldLabel" -- ItemName is the CURRENT app's
# singular item-name config, not its app name (see `flows steps list` output
# for an existing such step to get the exact string)
globiflow flows steps add FLOW_ID --action "Get Referenced Item(s)" --params '{"app": "Topics", "direction": "FORWARD"}'
globiflow flows steps add FLOW_ID --action "Get Referenced Item(s)" --params '{"app": "Topics", "direction": "FORWARD", "using_field": "(test1) Topic"}'

# Trigger-condition filter steps -- gate the whole flow before any action
# runs. "Field Changed" (only continue if a field's value changed on this
# update) requires an Item Updated (U) trigger; "Custom Filter" (a PHP
# eval) works with any trigger. Both take --params/--code, not --fields
globiflow flows steps add FLOW_ID --action "Field Changed" --params '{"field": "Status"}'
globiflow flows steps add FLOW_ID --action "Custom Filter" --code '[*item_value_approve-to-write*] != ""'

# A leading filter + action combo in one `flows create --steps` call --
# common for "only act when a specific field changes" flows
globiflow flows create --app-id 30560419 --trigger U --name "Gated Update" --steps '[{"action_type": "Field Changed", "field": "Status"}, {"action_type": "Update Item", "fields": {"Notes": "Status changed"}}]'
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

**Multi-step `--steps` chains:** `flows create --steps` with 2+ steps adds
only the first step in-page, saves, then adds every remaining step via a
fresh `flows steps add`-equivalent call against the now-saved flow. This
matters because Globiflow's variable/token registry (what makes
`[(Variable) myvar1]` resolve) is only populated for steps that existed when
the page was last loaded/saved -- a step referencing a variable an earlier
step in the *same unsaved* page just created would otherwise fail with
`Token '(Variable) myvar1' does not exist in this flow`.

**Field-less step types:** "End If" (closes an "If (Sanity Check)" block)
and "Continue" (ends a "For Each" loop early) render no configurable fields
in Globiflow's UI at all -- pass no other options for these.

**`--params` (steps add):** a JSON escape hatch for step parameters that
don't have a dedicated flag, following the same "JSON object, merged into
the step" convention as `--fields`:
- **"Get Referenced Item(s)" collector** -- `app` (required, matched like
  Create Item's target-app picker: the trailing segment of Globiflow's "Org
  \> Space > App" label), `direction` (`FORWARD`/`REVERSE`/`BOTH`,
  case-insensitive), `using_field` (optional, requires `direction` to also
  be set -- Globiflow doesn't render this picker until then). `using_field`'s
  value is the picker's full option text, `"(ItemName) FieldLabel"`, where
  `ItemName` is the *current* app's singular item-name config (Podio app
  settings -> "What is a single item called?"), not its app/display name --
  e.g. an app named "Content Submissions" with item-name "Submission" and a
  "Topic" relationship field offers `"(Submission) Topic"`. Only one field
  and direction combination is supported per call; "Follow references to
  another App" (a second hop) is not yet exposed.
- **Filter steps' target field** -- `{"field": "<Podio field label>"}` for
  "Field Changed" (and other field-based filters this CLI's `action_type_map`
  now recognizes: "Field Value Match", "Date Match", "Creator / Editor",
  "Comment Match" -- but only "Field Changed" and "Custom Filter" have their
  fields fully wired up end to end; the others add successfully as a step
  type but this CLI does not yet fill their extra controls, such as an
  operator or match value, so an add call for one of those fails loudly with
  a `ClientError` naming the unfilled control instead of silently reporting
  success).

**Trigger-condition filter steps:** Field Changed, Custom Filter, and other
condition steps that gate the whole flow live in a separate section of
Globiflow's editor from action/logic/collector steps, added via a different
picker than the Actions "+" button. "Field Changed" is only valid on an Item
Updated (`U`) trigger -- Globiflow's own client-side validation rejects it
(and, only for that specific reason, blocks the entire save) on any other
trigger type. Because Globiflow pre-seeds every *new* Update-triggered
flow's Filters section with an unconfigured "Field Changed" filter as a
suggested starting point, `flows create --trigger U` deletes any such
pre-existing, unconfigured filter/action step before adding the steps you
asked for -- otherwise even a plain `flows create --trigger U` with no
`--steps` at all would fail to save. "Custom Filter" (PHP eval) uses
`--code`, the same option/field as "Custom Variable" and "If (Sanity
Check)". `flows steps list`/`flows steps get` do not yet surface filter
steps (a known, separate gap) -- use `flows export` and inspect the raw XML
to confirm a filter step's saved configuration.

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
