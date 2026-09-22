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
| Create a checkbox field | `airtable fields create "Table Name" "Field Name" checkbox --options '{"icon":"check","color":"greenBright"}'` |
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

### 3. Lookup fields are created with `multipleLookupValues`, not `lookup`

**Symptom:** `airtable fields create Clips "Module Status" lookup --base app... --options '{"recordLinkFieldId":"fld...","fieldIdInLinkedTable":"fld..."}'` is refused before the request with a message naming `multipleLookupValues`. Sending `lookup` to Airtable directly returns `422 UNSUPPORTED_FIELD_TYPE_FOR_CREATE` — "Creating lookup fields is not supported at this time".

**Cause:** Airtable's create-field endpoint accepts the same type name it returns from schema reads, `multipleLookupValues`. The `lookup` spelling in its docs is not accepted by the create-field API.

**Correct path:** Use the type that `fields list` reports:

```bash
airtable fields create Clips "Module Status" multipleLookupValues --base app... \
  --options '{"recordLinkFieldId":"fld...","fieldIdInLinkedTable":"fld..."}'
```

Measured live against base `app9uzzru5KZOImYQ` on 2026-09-11: `multipleLookupValues` returned 201 with `options.isValid: true`; `rollup` with a `formula` returned 201 with `options.isValid: true`; only `lookup` returned 422.

**CLI behavior:** `airtable fields create ... multipleLookupValues ...` and `airtable fields create ... rollup ...` forward the request normally. Only `airtable fields create ... lookup ...` is guarded, and the refusal names `multipleLookupValues` as the working type.

### 4. A created field can never be removed or repointed through the API

**Symptom:** A field created with wrong options (for example a lookup pointing at the wrong `fieldIdInLinkedTable`) cannot be deleted or corrected by API. `DELETE /v0/meta/bases/{base}/tables/{table}/fields/{id}` returns 404, and `PATCH .../fields/{id}` with `recordLinkFieldId` or `fieldIdInLinkedTable` returns 422.

**Cause:** Airtable exposes no delete-field endpoint, and the update-field endpoint accepts only `name` and `description`. Verified in the same live pass on 2026-09-11.

**Correct path:** Verify the `--options` payload before creating — field IDs resolved from `airtable fields list <linked table>` — because the only way to remove a mistake is Airtable's web UI. `airtable fields create` prints this warning on every successful create, and `airtable fields delete` refuses before making a request.

### 5. Checkbox fields need `options.icon` and `options.color`, which the CLI now supplies

**Symptom:** `airtable fields create "Demos" "Unpaced Action Video Recorded" checkbox --base app... --description "..."` failed with 422 `Invalid options for Demos.Unpaced Action Video Recorded: Failed schema validation: Unpaced Action Video Recorded.options is missing`, and the `--options '{}'` workaround failed with `... options.icon is required`.

**Cause:** Airtable's create-field schema requires both `icon` and `color` on a checkbox. The CLI sent no `options` object at all when `--options` was absent, and forwarded an empty object unchanged when it was empty.

**Correct path:** the bare and empty-options forms now work: `fields create` fills in Airtable's defaults `{"icon":"check","color":"greenBright"}` whenever a checkbox create receives no `options`, an empty object, or an object missing either key. Explicit `--options` values win, so `--options '{"icon":"star","color":"red"}'` still creates that exact checkbox:

```bash
airtable fields create "Demos" "Unpaced Action Video Recorded" checkbox \
  --base app... --description "Marks that the first, unpaced action-video take has been recorded."
```

**Scope:** only checkbox creation is defaulted. Other field types still forward `--options` exactly as given, and a checkbox created with the wrong icon or color cannot be corrected later over the API — see issue 4 above.
