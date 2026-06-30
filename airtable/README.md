# Airtable CLI

## DESCRIPTION

The `airtable` CLI provides a command-line interface for Airtable API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Features

- **Full CRUD Operations**: List, get, create, update, and delete records
- **Field Schema Operations**: List, get, create, and update fields. Airtable's public Web/Meta API does not support field deletion.
- **Default Base ID**: Configure a default base to avoid repetition
- **Advanced Filtering**: Use Airtable formulas to filter records
- **Pagination Support**: Handle large datasets with pagination
- **Sorting**: Sort records by any field
- **Field Selection**: Return only specific fields to reduce data transfer
- **Table & JSON Output**: Human-readable tables or JSON for scripting
- **Type Casting**: Automatic data type conversion for easier updates

## Installation

```bash
cd airtable
pip install -e .
```

After installation, the `airtable` command will be available globally in your terminal.

## Quick Start

### 1. Get a Personal Access Token

1. Visit [https://airtable.com/create/tokens](https://airtable.com/create/tokens)
2. Create a new token with the following scopes:
   - `data.records:read` (for reading records)
   - `data.records:write` (for updating/creating records)
   - `schema.bases:write` (for creating/updating fields)
3. Add the bases you want to access to the token

### 2. Authenticate

```bash
# Interactive authentication
airtable auth login

# Or provide token directly
airtable auth login --token YOUR_PERSONAL_ACCESS_TOKEN
```

### 3. Configure Default Base (Optional)

Add your default base ID to `.env`:

```bash
AIRTABLE_BASE_ID=appXXXXXXXXXXXXXX
```

### 4. Start Using the CLI

```bash
# List records from a table (uses default base)
airtable records list "Tasks"

# Update a record
airtable records update "Tasks" recXXX "Status=Complete"

# Create a new record
airtable records create "Tasks" "Name=New Task" "Status=Todo"

# Create a new field
airtable fields create tblXXXXXXXXXXXXXX "Status" singleLineText

# Use a different base with --base
airtable records list "Tasks" --base appOTHERBASE
```

## Commands

### Authentication

```bash
# Login with Personal Access Token
airtable auth login
airtable auth login --token YOUR_TOKEN

# Check authentication status
airtable auth status
airtable auth status

# Clear stored credentials
airtable auth logout
```

### Profiles

```bash
# List all profiles
airtable auth profiles list

# List profiles as table
airtable auth profiles list --table

# Get a specific profile
airtable auth profiles get staging

# Create a new profile
airtable auth profiles create staging

# Select active profile
airtable auth profiles select staging

# Delete a profile
airtable auth profiles delete staging
```

### Cache

```bash
# Clear cached Airtable responses
airtable cache clear
```

### Records

All record commands use the default `BASE_ID` from `.env`. Override with `--base` / `-b` if needed.

#### List Records

```bash
# List all records from a table
airtable records list "Table Name"

# Limit results
airtable records list "Tasks" --limit 10

# Use a specific base (overrides default)
airtable records list "Tasks" --base appXXX

# Filter with standard syntax
airtable records list "Tasks" --filter "Status:eq:Active"

# Filter with raw Airtable formula
airtable records list "Tasks" --formula "AND({Status}='Active', {Priority}='High')"

# Select specific properties
airtable records list "Tasks" --properties "Name,Status,Priority"

# Sort records
airtable records list "Tasks" --sort-field "Created" --sort-direction desc

# Display as table
airtable records list "Tasks" --table

# List next page using offset
airtable records list "Tasks" --offset "itrXXXXXXXXXXXXXX/recXXXXXXXXXXXXXX"

# Use a specific view
airtable records list "Tasks" --view "Active Tasks"
```

#### Get a Record

```bash
# Get a specific record by ID
airtable records get "Tasks" recXXXXXXXXXXXXXX

# Display as table
airtable records get "Tasks" recXXX
```

#### Update a Record

```bash
# Update specific fields (PATCH - preserves other fields)
airtable records update "Tasks" recXXX "Status=Complete" "Priority=High"

# Replace entire record (PUT - clears unspecified fields)
airtable records update "Tasks" recXXX "Name=New Name" --replace

# Update with automatic type conversion
airtable records update "Tasks" recXXX "Completed=true" "Count=5" --typecast

# Update with JSON values (arrays, objects)
airtable records update "Tasks" recXXX 'Tags=["urgent","work"]'
```

#### Create a Record

```bash
# Create a new record
airtable records create "Tasks" "Name=New Task" "Status=Todo"

# Create with typecast
airtable records create "Tasks" "Name=Task" "Priority=1" --typecast

# Create with complex values
airtable records create "Tasks" 'Tags=["important"]' 'Details={"note":"test"}'
```

#### Delete a Record

```bash
# Delete a record (with confirmation prompt)
airtable records delete "Tasks" recXXX

# Delete without confirmation
airtable records delete "Tasks" recXXX --yes
```

### Fields

Field schema commands use Airtable table IDs beginning with `tbl`. Table names are not accepted by Airtable's schema endpoints.

#### Create a Field

```bash
# Create a single line text field
airtable fields create tblXXXXXXXXXXXXXX "Status" singleLineText

# Create a checkbox field with options
airtable fields create tblXXXXXXXXXXXXXX "Done" checkbox \
  --options '{"icon":"check","color":"greenBright"}'

# Create with a description
airtable fields create tblXXXXXXXXXXXXXX "Notes" multilineText \
  --description "Internal notes for this record"

# Create a rollup field when supported by Airtable for the target base
airtable fields create tblXXXXXXXXXXXXXX "Total Hours" rollup \
  --options '{"recordLinkFieldId":"fldLinks","fieldIdInLinkedTable":"fldHours","formula":"SUM(values)"}'
```

Do not use the `multipleLookupValues` type returned by `fields list` as a
`fields create` type. Airtable's public create-field API has returned
`UNSUPPORTED_FIELD_TYPE_FOR_CREATE` for that read-schema type; create lookup
fields in the Airtable web UI, then verify them with `fields list` or
`fields get`.

#### Update a Field

```bash
# Rename a field
airtable fields update tblXXXXXXXXXXXXXX fldXXXXXXXXXXXXXX --name "Current Status"

# Update a field description
airtable fields update tblXXXXXXXXXXXXXX fldXXXXXXXXXXXXXX \
  --description "The current workflow status"

# Update field options
airtable fields update tblXXXXXXXXXXXXXX fldXXXXXXXXXXXXXX \
  --options '{"formula":"{Hours} * {Rate}"}'
```

#### Delete a Field

```bash
# Field deletion is not supported by Airtable's public Web/Meta API.
# Delete the field in Airtable's web UI, then verify removal with fields get/list.
airtable fields delete tblXXXXXXXXXXXXXX fldXXXXXXXXXXXXXX
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

### JSON Output Example

```bash
airtable records list "Tasks" --max-records 2
```

Returns:
```json
{
  "records": [
    {
      "id": "recXXXXXXXXXXXXXX",
      "createdTime": "2024-01-15T10:30:00.000Z",
      "fields": {
        "Name": "Task 1",
        "Status": "Active",
        "Priority": "High"
      }
    }
  ]
}
```

### Table Output Example

```bash
airtable records list "Tasks" --max-records 5
```

## Configuration

Authentication profile files live under `~/.local/share/cli-tools/airtable/authentication_profiles/<profile>/`; non-auth defaults live in `~/.local/share/cli-tools/airtable/.env`:

```bash
# Personal Access Token
AIRTABLE_ACCESS_TOKEN=your_personal_access_token

# Default Base ID (optional - avoids specifying --base each time)
AIRTABLE_BASE_ID=appXXXXXXXXXXXXXX

# Optional: API base URL (defaults to production)
AIRTABLE_BASE_URL=https://api.airtable.com/v0
```

## Finding Base and Table IDs

### Base ID
1. Open your Airtable base in a web browser
2. The URL will be: `https://airtable.com/appXXXXXXXXXXXXXX/...`
3. The `appXXXXXXXXXXXXXX` part is your base ID

### Table ID or Name
You can use either:
- **Table Name**: The human-readable name (e.g., "Tasks", "Contacts")
- **Table ID**: The ID starting with `tbl` (found in the table URL)

Field schema commands require the table ID.

### Record ID
Record IDs start with `rec` and can be found:
- In the record URL when viewing a record
- In the response from list/get commands

### Field ID
Field IDs start with `fld` and appear in Airtable API schema responses and field URLs.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Advanced Examples

### Filter and Export Active Tasks

```bash
airtable records list "Tasks" \
  --filter "{Status}='Active'" \
  --sort-field "Priority" \
  --sort-direction desc \
  > active_tasks.json
```

### Extract Specific Fields with jq

```bash
airtable records list "Tasks" | jq '.records[] | {id: .id, name: .fields.Name}'
```

### Batch Update Status

```bash
# Get all incomplete task IDs
TASK_IDS=$(airtable records list "Tasks" \
  --filter "{Status}='Todo'" | jq -r '.records[].id')

# Update each one
for id in $TASK_IDS; do
  airtable records update "Tasks" $id "Status=In Progress"
done
```

### Create Multiple Records from CSV

```bash
# Assuming a CSV with Name,Status,Priority columns
tail -n +2 tasks.csv | while IFS=, read name status priority; do
  airtable records create "Tasks" \
    "Name=$name" \
    "Status=$status" \
    "Priority=$priority"
done
```

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests

## License

MIT
