---
name: lastpass-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute lastpass operations using the `lastpass` CLI tool.
  LastPass password manager CLI wrapper for retrieving passwords, usernames, vault entries, and safe field metadata.
  Triggers: lastpass, lastpass cli, lastpass password, lastpass vault, get password from lastpass, lastpass credentials, lastpass login, list lastpass entries, lastpass fields, search lastpass, lastpass username
---

<objective>
Execute lastpass operations using the `lastpass` CLI. All lastpass interactions should use this CLI.
</objective>

<quick_start>
The `lastpass` CLI follows this pattern:
```bash
lastpass <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check auth status | `lastpass auth status` |
| List vault entries | `lastpass items list --table` |
| List entries in folder | `lastpass items list Work --table` |
| List payment cards | `lastpass items list --filter "name:like:%hsa%" --category "Payment Cards" --table` |
| Search entries (case-insensitive) | `lastpass items list --filter "name:like:%github%" --limit 0` |
| Get entry details | `lastpass items get <id-or-name>` |
| Inspect field names without values | `lastpass items fields <id-or-name>` |
| Get password only | `lastpass items password <id-or-name>` |
| Copy password to clipboard | `lastpass items password <id-or-name> --clip` |
| Get username only | `lastpass items username <id-or-name>` |
</quick_start>

Vault search uses `lastpass items list --filter`, not `lastpass items search`;
the adjacent `usage.json` has no `items search` command leaf.

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `lastpass` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage LastPass authentication (login, logout, status, sync)
- **items** -- Manage vault entries (list, get, fields, password, username)
</principle>

<principle name="Safe field discovery">
Use `lastpass items fields <id-or-name>` when automation needs to determine
whether a custom, OTP, or TOTP-related field exists. It returns an ordered JSON
array of `{"name", "sensitive"}` records and never prints field values.
Synthetic header metadata (`id`, `full_path`, `group`, `name`) is excluded.
Ambiguous names retain the standard metadata-only JSON response and exit `3`.
</principle>

<principle name="Searching the vault (avoid false negatives)">
`items list` returns metadata only, so `--filter` works **only** on `id`, `name`, `group`, `full_path`.
- **`name:like`/`ilike` is case-insensitive** -- `name:like:%google%` matches an entry named "Google". Use `%term%` for a contains-style search.
- **Filtering on a non-metadata field errors.** `Username:`/`URL:` (or any unsupported field) exits non-zero listing supported fields -- it never returns an empty result. To search by username/url, you cannot filter; fetch the entry with `items get`/`items username`.
- **`--limit` defaults to 50** and silently truncates the ~1000-entry vault. For any real search, pass **`--limit 0`** (unlimited) so a match past the 50th entry is not missed; a truncation notice is printed to stderr when capped. Never conclude an entry is absent from a default-limited or single-field-filtered listing.
- **`--category` is not a broad search.** Category filtering inspects each candidate with `lpass show --field=NoteType` and refuses more than 50 candidates. Always narrow first with a group argument or metadata `--filter`; never run category-only scans such as `lastpass items list --category "Payment Cards" --limit 0`.
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
