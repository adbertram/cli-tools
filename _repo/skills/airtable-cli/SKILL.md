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
| List fields in a table | `airtable fields list "Table Name"` |
| Create a field | `airtable fields create "Table Name" "Field Name" singleLineText` |
| Update a field | `airtable fields update "Table Name" fldXXX --name "New Name"` |
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

For named-base work, resolve the base ID in the same sequential shell flow that runs the dependent commands: capture the `id` returned by `airtable --no-cache bases get <base-name>`, verify it is non-empty, then reuse that captured value for every `--base` option. Do not hardcode, paste, or reuse remembered `app...` IDs, including CourseCraft base IDs, and do not launch schema or record commands in parallel with the base-resolution command they depend on.
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

### 3. Lookup field creation is not a reliable production schema path through fields create

**Symptom:** `airtable fields create tbl... "Lookup" multipleLookupValues --options '{"recordLinkFieldId":"fld...","fieldIdInLinkedTable":"fld..."}'` returns `Error: API request failed (422): {'type': 'UNSUPPORTED_FIELD_TYPE_FOR_CREATE'}`. `airtable fields create Clips "Module Status" lookup --base app... --options '{"recordLinkFieldId":"fld...","fieldIdInLinkedTable":"fld..."}'` returns `Error: API request failed (422): Invalid options for Clips.Module Status: Creating lookup fields is not supported at this time`.

**Cause:** Airtable schema reads expose lookup fields as `multipleLookupValues`, while current Airtable docs list create-field variant type `lookup`; both have been rejected by the public create-field API for live CourseCraft-style schema work. Do not copy a lookup field's returned `type` from `fields list` into `fields create`, and do not treat documented `lookup` create examples as a reliable production schema-migration path.

**Correct path:** Create lookup fields in Airtable's web UI, then verify with `airtable fields list <table> --filter 'name:eq:<field name>'` or `airtable fields get <table> <field>`.

**CLI behavior:** `airtable fields create ... multipleLookupValues ...` and `airtable fields create ... lookup ...` are guarded and return a clear unsupported-operation error before making any API request.

### 4. Rollup field creation is not reliable through fields create

**Symptom:** `airtable fields create Clips "Module Status" rollup --base app... --options '{"recordLinkFieldId":"fld...","fieldIdInLinkedTable":"fld...","formula":"ARRAYJOIN(values)"}'` returns `Error: API request failed (422): {'type': 'UNSUPPORTED_FIELD_TYPE_FOR_CREATE'}`.

**Cause:** Airtable documents a rollup create payload, and the CLI can forward it, but Airtable's public create-field API has rejected rollup creation for a live CourseCraft base. Do not treat a rollup create example or schema-read field type as a reliable production schema-migration path.

**Correct path:** Create or change rollup fields in Airtable's web UI, then verify with `airtable fields list <table> --filter 'name:eq:<field name>'` or `airtable fields get <table> <field>`. Use `airtable fields create ... rollup` only in a disposable base when the task is specifically to test Airtable API support.

**CLI behavior:** `airtable fields create ... rollup ...` is not guarded today; it forwards the request and can return Airtable's 422 unsupported-field-type response.
