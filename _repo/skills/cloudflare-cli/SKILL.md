---
name: cloudflare-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute cloudflare operations using the `cloudflare` CLI tool.
  CLI interface for Cloudflare API — manage zones, DNS records, cache, IP access rules, zone traffic analytics, and Workers scripts.
  Triggers: cloudflare, cloudflare cli, cloudflare dns, cloudflare zones, cloudflare cache, cloudflare access rules, manage dns records, purge cloudflare cache, cloudflare ip rules, block ip cloudflare, cloudflare analytics, zone traffic, page views, top paths, cloudflare workers, worker scripts, upload worker
---

<objective>
Execute cloudflare operations using the `cloudflare` CLI. All cloudflare interactions should use this CLI.
</objective>

<quick_start>
The `cloudflare` CLI follows this pattern:
```bash
cloudflare <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List zones | `cloudflare zones list --table` |
| Get zone details | `cloudflare zones get ZONE_ID` |
| List DNS records | `cloudflare dns records list ZONE_ID --table` |
| Create DNS record | `cloudflare dns records create ZONE_ID --type A --name sub.example.com --content 1.2.3.4` |
| Purge cache | `cloudflare cache purge ZONE_ID` |
| List access rules | `cloudflare access-rules list ZONE_ID --table` |
| Block an IP | `cloudflare access-rules create ZONE_ID --target ip --value 1.2.3.4 --mode block` |
| Set Under Attack mode | `cloudflare zones update ZONE_ID --security-level under_attack` |
| Traffic totals for a date range | `cloudflare analytics summary example.com --start 2026-06-01 --end 2026-06-30` |
| Top pages by HTML page views | `cloudflare analytics top-paths example.com --limit 5 --table` |
| List Workers scripts | `cloudflare workers list` |
| Download a Worker script | `cloudflare workers get my-worker > worker.js` |
| Upload a Worker script | `cloudflare workers upload my-worker --file ./worker.js` |
| Delete a Worker script | `cloudflare workers delete my-worker --force` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `cloudflare` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** — Manage authentication (login, logout, status, refresh, test)
- **auth** -- Authentication commands and nested `auth profiles` management
- **zones** — Manage Cloudflare zones (list, get, update security settings)
- **cache** — `cache purge ZONE_ID` purges the Cloudflare CDN edge cache for a zone; `cache clear` removes the local CLI response cache for a profile. These are different caches.
- **access-rules** — Manage IP access rules (whitelist, block, challenge IPs/ranges/ASNs/countries)
- **dns** — Manage DNS with sub-groups: `dns zones` (list/get zones) and `dns records` (full CRUD on DNS records)
- **analytics** — Zone traffic analytics via the GraphQL Analytics API: `analytics summary` (totals for a date range) and `analytics top-paths` (top pages by HTML page views). Zone argument accepts a zone name or zone ID. Requires the `Analytics: Read` zone permission on the API token.
- **workers** — Account-level Workers script management: `workers list`, `workers get SCRIPT_NAME` (raw source to stdout or `--output FILE`), `workers upload SCRIPT_NAME --file ./worker.js [--format modules|service-worker] [--compatibility-date YYYY-MM-DD] [--bindings '<json-array>']`, and `workers delete SCRIPT_NAME --force`. All four take an optional ACCOUNT argument (name or ID); omit it when the token sees exactly one account. Requires `Account > Workers Scripts > Read` (list/get) or `Account > Workers Scripts > Edit` (upload/delete) on the API token.
- **workers routes** — Zone-scoped Worker routes: `workers routes list ZONE`, `workers routes get ZONE ROUTE_ID`, `workers routes create ZONE --pattern ... --script ...`, and `workers routes delete ZONE ROUTE_ID --force`. Requires `Zone > Workers Routes > Read` (list/get) or `Zone > Workers Routes > Edit` (create/delete).
- **pages** — Account-level Cloudflare Pages management with three sub-groups:
  - `pages projects` — `list`, `get PROJECT_NAME`, `create`, `update`, `delete`, `purge-build-cache`, `get-upload-token`. Projects are addressed by NAME, not ID.
  - `pages deployments` — `list PROJECT`, `get PROJECT DEPLOYMENT_ID`, `create` (pass `--directory PATH` for full direct-upload deploys: hashes the tree, uploads missing assets, ships the site; pass `--manifest '{json}'` only for advanced manual creates), `retry`, `rollback`, `delete`.
  - `pages domains` — `list PROJECT`, `get PROJECT DOMAIN`, `create` (add), `update` (reprovision/retry validation), `delete`.
  - All Pages commands take an optional ACCOUNT argument (name or ID). Requires `Pages Read` (list/get) or `Pages Write` (mutations) on the API token.
</principle>

<principle name="Optional Capability Probes">
`usage.json` is the command contract. If a needed Cloudflare API area is absent from `usage.json` (for example rulesets/header transforms for HSTS discovery), do not run a bare guessed command and let `No such command` fail the workflow. Either report the missing CLI capability and route a deliberate CLI-extension task, or wrap any exploratory `cloudflare <group> --help` probe so expected absence prints an explicit unsupported marker and exits 0. Do not mutate Cloudflare configuration while probing capability.
</principle>
</essential_principles>

<known_issues>
<issue name="Reads succeed but every write returns 403 'Authentication error' (token scope)">
**Symptom.** Read commands work and return correct data:

```
cloudflare zones list --table
cloudflare dns records list <zone_id> --limit 200
```

Every write fails with exit 1 and a 403:

```
cloudflare dns records delete <zone_id> <record_id> --force
Error: API request failed (403): Authentication error
```

The failure hits every record and every zone identically.

**Cause.** The stored credential is a scoped Cloudflare **User API Token**, not
a Global API Key; the CLI authenticates with `Authorization: Bearer <token>`
using the API token stored in the CLI-tools secret manager as `cloudflare-api-key`. That token carries only Read permission groups. Cloudflare returns
HTTP 403 with the generic message `Authentication error` for an out-of-scope
token, which reads like a broken or expired credential and sends diagnosis down
the wrong path.

**This is not a header-shape bug.** `CloudflareClient._update_headers` builds
`Authorization: Bearer <token>` once in `__init__`, and `_make_request` sends
that same header for every HTTP method. Reads and writes are authenticated
identically. Do not go looking for an `X-Auth-Key`/`X-Auth-Email` branch or a
per-method code path; there is none, and
`cloudflare/tests/test_write_path_auth.py` locks that in.

**`cloudflare auth test` cannot detect this.** Its handler issues
`GET /zones`, so a read-only token returns `authenticated: true` and
`api_test: passed` while every write still fails. Never treat a green
`auth test` or `auth status` as proof that writes will work.

**How to confirm the credential is a token, not a Global API Key.** A Global API
Key is 37 hex characters. An API token is longer, mixed-case, and starts with
`cfut`. `auth status` shows the masked prefix. `GET /user/tokens/verify` with the
`Authorization: Bearer` header returns 200 and
`"This API Token is valid and active"` for a token; a Global API Key fails that
endpoint under Bearer. A valid `verify` plus a 403 write proves scope, not
validity.

**Fix (Adam must mint the token; an agent cannot).** Create a replacement API
token in the Cloudflare dashboard at
https://dash.cloudflare.com/profile/api-tokens with **Edit** permission for each
area the CLI must write, then store it in the secret manager:

| CLI command group | Permission group required |
|-------------------|---------------------------|
| `dns records create/update/delete` | Zone > DNS > Edit |
| `access-rules create/update/delete` | Zone > Firewall Services > Edit |
| `cache purge` | Zone > Cache Purge > Purge |
| `zones update` (security level) | Zone > Zone Settings > Edit |
| `zones list/get` | Zone > Zone > Read |
| `analytics summary/top-paths` | Zone > Analytics > Read |
| `workers list/get` | Account > Workers Scripts > Read |
| `workers upload/delete` | Account > Workers Scripts > Edit |

Set Zone Resources to include every zone the CLI manages, then rotate:

```bash
<cli-tools-root>/_repo/_secret-manager/secrets.sh set cloudflare-api-key
```

Verify the new scope with a real write against a low-risk zone
(`atademos.com`, `1bb82acebb2c9cc1e8c334e599db915d`) — create a throwaway TXT
record, confirm it, then delete it. Never test writes against
`actionblogger.com`, `adamtheautomator.com`, or `brickbuddy.io`.

**CLI behavior since the fix.** `_make_request` now routes any 403 through
`build_forbidden_error`, so the CLI names the refused method and endpoint, the
exact permission group required, the fact that working reads prove missing Edit
scope rather than an expired token, the `auth test` false-green warning, and the
`secrets.sh set` rotation command. A bare
`API request failed (403): Authentication error` from this CLI now means the
error path itself regressed.
</issue>

<issue name="API key is sourced from a CLI-tools secret (auth login cannot re-prompt it)">
The `cloudflare` credential type is `api_key`, and the active profile stores it as a
`secret://cloudflare-api-key` placeholder resolved from the CLI-tools secret
manager. Because the API key lives in the secret manager, `cloudflare auth login`
and `cloudflare auth login --force` cannot prompt for it interactively — they now
print an actionable notice naming the secret and the exact command to set/rotate it,
then re-validate the existing credential. This is expected, not an error.

To change or rotate the API key, update the secret directly (never edit the profile
`.env` or paste the key into a prompt):

```bash
<cli-tools-root>/_repo/_secret-manager/secrets.sh set cloudflare-api-key
```

If `auth login` reports `Missing secret 'cloudflare-api-key'`, the referenced
secret is absent from the secret manager. Set it with the command above; do not
attempt to re-enter the key through `auth login`.

This pattern applies to any api_key/PAT/username_password CLI whose sensitive fields
are stored as `secret://<name>` placeholders: rotate the value with
`secrets.sh set <secret-name>`, not through interactive `auth login`.
</issue>
</known_issues>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
