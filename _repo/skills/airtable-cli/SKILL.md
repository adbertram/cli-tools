---
name: airtable-cli
description: >-
  MANDATORY: Use this skill for ALL Airtable service operations. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute airtable operations using the `airtable` CLI tool.
  CLI interface for Airtable API -- manage records, fields, tables, authentication, cache, and profiles.
  Triggers: airtable, airtable cli, airtable records, airtable fields, airtable tables, airtable bases, list airtable bases, list airtable tables, find airtable base id, resolve airtable base by name, create airtable table, update airtable table, create airtable field, update airtable field, list airtable records, create airtable record, update airtable, airtable data, query airtable, airtable base
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
| List bases the token can access | `airtable bases list` |
| Resolve a base by name to its ID | `airtable bases get CourseCraft` |
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
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `airtable` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Base And Table Names">
`records`, `tables`, and `fields` commands operate against one Airtable base at a time. If the target base matters, resolve it with `airtable bases get <base-name>` and pass the returned `app...` ID with `--base`; do not rely on the default base. Table-name arguments are Airtable table names inside that selected base, not project CLI resource names such as CourseCraft `modules`.
</principle>

<principle name="Command Groups">
- **auth** -- Authentication management (login, logout, status, refresh, test) and nested `auth profiles`
- **cache** -- Local response cache management
- **bases** -- Discover the bases the active Personal Access Token can access (list, get). `bases list` follows the Metadata API `offset` pagination to return every accessible base; `bases get <id-or-name>` resolves one base to its id/name/permissionLevel. Airtable exposes no single-base detail endpoint, so `get` resolves from the full listing.
- **tables** -- Airtable table schema operations (list, create, update). Note: Airtable's public Meta API does not expose a delete-table endpoint.
- **fields** -- Airtable field schema operations (list, create, update). Airtable's public Web/Meta API does not support deleting fields.
- **records** -- CRUD operations on Airtable records (list, get, create, update, delete)
</principle>

<principle name="Confirmation In Non-Interactive Contexts">
**Destructive commands require `--yes`/`-y` when stdin is not a terminal** (agent
Bash tools, pipes, CI). Without a TTY they cannot show an interactive
confirmation prompt, so they fail fast with a clear refusal
(`Refusing to delete ... Re-run with --yes in non-interactive contexts.`) and a
non-zero exit instead of hanging. Always pass `--yes` for `records delete` (and
`auth profiles delete` uses `--force`/`-F`) from any agent or script.

```bash
airtable records delete "Table" recXXX --yes
airtable auth profiles delete <name> --force
```
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

### 2. Field deletion is not supported by Airtable's public API

**Symptom:** `airtable fields delete tbl... fld... --base app... --yes` fails instead of deleting the field.

**Cause:** Airtable documents public Web/Meta API support for listing, creating, and updating schema fields, but it does not expose a public field-delete endpoint.

**Correct path:** Delete the field in Airtable's web UI, then verify removal with `airtable fields get <table> <field>` or `airtable fields list <table> --filter 'name:eq:<field name>'`. Because absence is the expected success state, wrap the probe so `Field not found in table metadata: <field>` or an empty filtered list prints explicit evidence and exits `0`; any auth, base, table, or runtime error remains a failure.

**CLI behavior:** `airtable fields delete` is intentionally guarded and returns a clear unsupported-operation error before making any API request.

### 3. Lookup fields returned as multipleLookupValues are not safe field-create input

**Symptom:** `airtable fields create tbl... "Lookup" multipleLookupValues --options '{"recordLinkFieldId":"fld...","fieldIdInLinkedTable":"fld..."}'` returns `Error: API request failed (422): {'type': 'UNSUPPORTED_FIELD_TYPE_FOR_CREATE'}`.

**Cause:** Airtable schema reads expose lookup fields as `multipleLookupValues`, but that read-schema type has been rejected by the public create-field API. Do not copy a lookup field's returned `type` from `fields list` into `fields create`.

**Correct path:** Create lookup fields in Airtable's web UI, then verify with `airtable fields list <table> --filter 'name:eq:<field name>'` or `airtable fields get <table> <field>`. For rollups, the CLI can forward Airtable's documented write payload when the API supports it for the target base: `airtable fields create <table> "Rollup" rollup --options '{"recordLinkFieldId":"fldLinks","fieldIdInLinkedTable":"fldValue","formula":"SUM(values)"}'`.

**CLI behavior:** `airtable fields create ... multipleLookupValues ...` is guarded and returns a clear unsupported-operation error before making any API request.
