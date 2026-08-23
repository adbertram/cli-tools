---
name: venmo-cli
description: >-
  MANDATORY: Use this skill for ALL Venmo service operations and transaction-history queries. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute venmo operations using the `venmo` CLI tool. Read-only wrapper around the reverse-engineered Venmo private mobile API -- list and look up transaction history, manage auth profiles, and inspect/clear the response cache.
  Triggers: venmo, venmo cli, venmo transactions, list venmo transactions, get venmo transaction, venmo account, venmo history, venmo payment history, venmo activity, venmo transaction list, recent venmo, venmo auth, venmo login, venmo logout, venmo profile, venmo cache, classify venmo transaction.
---

<objective>
Execute venmo operations using the `venmo` CLI. All venmo interactions should use this CLI — do NOT scrape venmo.com, do NOT call the Venmo API directly. Venmo has no public consumer API; this CLI wraps the reverse-engineered `venmo-api` Python library (private mobile API at api.venmo.com) and is read-only by design.
</objective>

<quick_start>
The `venmo` CLI follows this pattern:
```bash
venmo [--no-cache] <command-group> <action> [arguments] [options]
```

Common operations:
```bash
# Authenticate (one-time; reads username/password from keychain, triggers SMS OTP)
venmo auth login
VENMO_OTP=123456 venmo auth login --force          # non-interactive
venmo auth logout                                  # clear saved token/device id

# Verify session is alive (live API round-trip)
venmo auth status
venmo auth test

# Multi-account profiles
venmo auth profiles list
venmo auth profiles create staging
venmo auth profiles set-default adam-bertram
venmo transactions list --profile staging          # query this auth profile without changing the active profile

# Transaction history (data plane is read-only — records are the FULL raw Venmo API payload)
venmo transactions list                            # 50 most recent, JSON envelope, every field Venmo returns
venmo transactions list --table --limit 10         # curated nested columns rendered as a table
venmo transactions list --filter "payment.amount:gt:100"   # dotted-path filters into nested payload
venmo transactions list --filter "note:contains:lego"
venmo transactions list --filter "payment.status:eq:settled"
venmo transactions list --properties payment_id,payment.amount,payment.actor.display_name,note   # dotted-path whitelist
venmo transactions list --before-id 4418053612741823878    # pagination by payment_id
venmo transactions get 4418053612741823878

# Cache management (responses are cached via shared @cached decorator)
venmo --no-cache transactions list                 # bypass cache for this call
venmo cache clear                                  # wipe cache for the active profile
```
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `venmo` command.** It contains the complete command tree, every flag, defaults, and per-command usage instructions. Never guess at command syntax.
</principle>

<principle name="Credentials Come From the Keychain">
The CLI does NOT prompt for a username or password. Both are stored once in the CLI-tools macOS keychain (`cli-tools` service):
```bash
/Users/adam/Dropbox/GitRepos/cli-tools/secret-manager/secrets.sh set venmo-username
/Users/adam/Dropbox/GitRepos/cli-tools/secret-manager/secrets.sh set venmo-password
```
Never store them in `.env`. After `venmo auth login` succeeds, a long-lived access token + trusted device id are persisted to `~/.local/share/cli-tools/venmo/.profiles/<profile>/.env` — they survive across sessions.
</principle>

<principle name="OTP Handling">
First login triggers an SMS OTP from Venmo. Provide it interactively, or pass `VENMO_OTP=<6-digit>` as an environment variable for non-interactive runs. Subsequent logins on the same device skip OTP because the device id is marked trusted on first success. Use `venmo auth login --force` to clear the token and re-trigger the full OTP flow.
</principle>

<principle name="Read-Only Data Plane">
The data plane exposes ONLY `transactions list` and `transactions get`. The CLI does NOT support sending money, requesting money, or modifying any account state — those require Venmo's authenticated mobile flows and are out of scope. If you need to send/request money, do it in the Venmo app. (Admin commands like `auth login/logout/profiles` and `cache clear` exist; they manage the CLI itself, not your Venmo account.)
</principle>

<principle name="auth refresh is a no-op for Venmo">
The `auth refresh` command exists in the shared CLI scaffold but does nothing useful for Venmo — Venmo access tokens are long-lived and don't expire unless explicitly revoked. If `auth status` reports `authenticated: false`, run `venmo auth login --force` to redo the SMS-OTP flow rather than `auth refresh`.
</principle>

<principle name="Output Envelope and Record Shape">
`venmo transactions list` returns `{"cache_hit": <bool>, "results": [...]}`. Iterate records via `jq '.results[]'`. `venmo transactions get` returns the record with `cache_hit` injected at the top level. **Each record is the FULL raw Venmo API payload** (the unmodified `Transaction._json` from the venmo-api library) — no field-dropping, no normalization. The CLI injects one convenience field at the top level: `payment_id` (mirrors `payment.id` — use this with `venmo transactions get` and dotted-path filters). Top-level keys: `id` (story_id, often null), `type`, `note`, `date_created`, `date_updated`, `audience`, `transaction_external_id`, `payment_id`, plus nested objects `payment` (with `id`/`status`/`action`/`amount`/`actor` full user object/`target` (`type`+`user`|`merchant`|`email`|`phone`+`redeemable_target`)/`date_completed` etc.), `app`, `likes`, `reactions`, `comments`, `mentions`, `transfer`, `authorization`. Amounts are USD floats; dates are ISO-8601 strings.
</principle>

<principle name="Dotted-Path Filters and Properties">
Both `--filter` and `--properties` accept dotted paths into the nested record. Use `payment.amount:gt:100` (NOT `amount:gt:100`), `payment.status:eq:settled`, `payment.action:eq:pay`, `payment.actor.username:eq:Adam-Bertram`, `payment.target.user.display_name:contains:Zac`. For `--properties`, the resulting JSON uses the dotted path AS the key (e.g. `"payment.amount": 70.0`).
</principle>

<principle name="AI Instruction Results">
After every `venmo` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. (No `venmo` command currently returns this shape, but the contract is preserved for future commands.)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is in requested format (JSON default, `--table` for human view)
- Correct command and flags used (verified against usage.json)
- Transaction records are the full raw Venmo API payload (nested `payment`, `app`, `likes`, `reactions`, `comments`, `mentions`, `transfer`, `authorization`, etc.) plus top-level `payment_id`
- Dotted-path filters (`payment.amount:gt:N`) and properties (`payment.actor.display_name`) used when navigating nested fields
</success_criteria>

<validated>
Validated on 2026-05-16: full record shape verified live via `venmo transactions list --limit 2` (returns the raw `Transaction._json` payload with top-level `payment_id` injected); table/filter/properties verified with dotted paths.
</validated>
