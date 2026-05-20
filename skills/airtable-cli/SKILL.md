---
name: airtable-cli
description: >-
  MANDATORY: Use this skill for ALL Airtable service operations. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute airtable operations using the `airtable` CLI tool.
  CLI interface for Airtable API -- manage records, fields, tables, authentication, cache, and profiles.
  Triggers: airtable, airtable cli, airtable records, airtable fields, airtable tables, list airtable tables, create airtable table, update airtable table, create airtable field, update airtable field, list airtable records, create airtable record, update airtable, airtable data, query airtable, airtable base
---

<objective>
Execute airtable operations using the `airtable` CLI. All Airtable interactions should use this CLI.
</objective>

<quick_start>
The `airtable` CLI follows this pattern:
```bash
airtable <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List records from a table | `airtable records list "Table Name"` |
| Get a specific record | `airtable records get "Table" recXXX` |
| Create a record | `airtable records create "Table" "Field=Value"` |
| Update a record | `airtable records update "Table" recXXX "Field=Value"` |
| Delete a record | `airtable records delete "Table" recXXX` |
| List tables in a base | `airtable tables list --base appXXX` |
| Create a table | `airtable tables create "Table Name" --base appXXX` |
| Update a table | `airtable tables update tblXXX --name "New Name"` |
| List fields in a table | `airtable fields list tblXXX` |
| Create a field | `airtable fields create tblXXX "Field Name" singleLineText` |
| Update a field | `airtable fields update tblXXX fldXXX --name "New Name"` |
| Check auth status | `airtable auth status` |
| List profiles | `airtable auth profiles list` |
| Clear cache | `airtable cache clear` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `airtable` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Authentication management (login, logout, status, refresh, test) and nested `auth profiles`
- **cache** -- Local response cache management
- **tables** -- Airtable table schema operations (list, create, update). Note: Airtable's public Meta API does not expose a delete-table endpoint.
- **fields** -- Airtable field schema operations (list, create, update)
- **records** -- CRUD operations on Airtable records (list, get, create, update, delete)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>

## Known Issues

### 1. records create/update silently coerces digit-only values to integer, breaking singleLineText writes

**Symptom:** `airtable records update "T" recX "Account ID=7955906"` returns `Error: API request failed (422): Field "Account ID" cannot accept the provided value`. The targeted field exists and is `singleLineText`. `--typecast` does NOT fix it.

**Cause:** `airtable_cli/commands/records.py` parses each `FieldName=value` pair with `json.loads(field_value)` before falling back to string. Any digit-only value (`"7955906"`) parses successfully as a JSON number and is sent to Airtable as an integer. Airtable's `singleLineText` field rejects integer values, and `--typecast` does not coerce int→string in this direction.

**Fix (immediate workaround):** Wrap the value in JSON-quoted form so it stays a string after `json.loads`: `airtable records update "T" recX 'Account ID="7955906"'`. The double quotes inside the single-quoted shell arg are part of the JSON.

**Fix (CLI bug — needs cli-tool-expert):** `records.py` create/update should default to string and only `json.loads` when the value looks structural (starts with `{`, `[`, or matches `true|false|null`). The current eager-JSON behavior is a fallback pattern that silently changes types.

**Verification:** After the JSON-quoted form, the record JSON shows `"Account ID": "7955906"` (string), and the API returns 200.

**Recurrence Prevention:** Always JSON-quote digit-only or boolean-looking values intended for text fields: `'Field="123"'`, `'Field="true"'`. Until the CLI is patched, treat the bare `Field=Value` form as unsafe for any value that is valid JSON (numbers, booleans, null, objects, arrays) being written to a text field.

**General rule:** When a CLI pre-parses user input with `json.loads` and falls back to string, digit-only and boolean-looking values silently become non-strings — always force-quote them to preserve string type.
