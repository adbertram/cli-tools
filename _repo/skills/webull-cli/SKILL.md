---
name: webull-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Webull operations using the `webull` CLI tool.
  CLI interface for Webull.
  Triggers: webull, webull cli
---

<objective>
Execute Webull operations using the local `webull` CLI, built on the official Python SDK for TickSmith and standalone use. The separately published upstream Webull Go CLI has a different command and output contract and is not a drop-in replacement.
</objective>

<project_overrides>
Before acting on this skill, run:

```bash
~/.agents/skills/skill-expert/scripts/load-skill-overrides.sh webull-cli
```

Apply any printed instructions alongside this skill's own workflow: they extend it and
never repeal its limits. No output means no project override is in effect. A non-zero
exit means the project's override file is broken -- report it and stop rather than
silently running unmodified.
</project_overrides>

<quick_start>
The `webull` CLI follows this pattern:
```bash
webull <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Get an account's full balance response | `webull account balance <ACCOUNT>` |
| Get an account's full balance response | `webull account get <ACCOUNT>` |
| List accounts, preserving every API field by default | `webull account list` |
| List account positions | `webull account positions <ACCOUNT>` |
| Configure authentication credentials | `webull auth login` |
| Clear stored credentials | `webull auth logout` |
| Create a new profile from .env.example template | `webull auth profiles create <NAME>` |
| Delete a profile and its data | `webull auth profiles delete <NAME>` |
| Get details for a specific profile | `webull auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `webull auth profiles list` |
| Delete a profile and its data | `webull auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `webull auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `webull auth profiles select <NAME>` |
| Check authentication status across profiles | `webull auth status` |
| Test authentication by verifying credentials work across profiles | `webull auth test` |
| Save an access token from a hidden terminal prompt or piped stdin | `webull auth token` |
| Get full futures history bar responses | `webull futures bars <SYMBOL>` |
| Emit JSONL tick, disconnect and error events until interrupted | `webull futures stream <SYMBOL>` |
| Cancel one broker order by caller-defined client order ID | `webull order cancel <ACCOUNT> <CLIENT_ORDER_ID>` |
| Get the full broker response for a client order ID | `webull order get <ACCOUNT> <CLIENT_ORDER_ID>` |
| Get one page of history with exact API cursor and date filters | `webull order history <ACCOUNT>` |
| Get one page of working orders; caller follows the unchanged cursor | `webull order list <ACCOUNT>` |
| Get one page of working orders; caller follows the unchanged cursor | `webull order open <ACCOUNT>` |
| Preview caller-defined orders without sending | `webull order place <ACCOUNT> --orders-json - --dry-run` |
| Preview caller-defined replacements without sending | `webull order replace <ACCOUNT> --orders-json - --dry-run` |
</quick_start>

<essential_principles>
<principle name="Authorization and Order Outcomes">
Read-only account inspection is the authentication smoke test. Never place orders merely to check authentication. Order mutations require an authorized trading request and exactly one of `--yes` or `--dry-run`; the CLI does not enforce TickSmith's strategy or account risk policy. Sandbox is the default. Production access additionally requires `--environment live --confirm-live`, before the command group, and an authorized access token.

Every order keeps its caller-supplied client_order_id. A write error with `kind=unknown` must be reconciled by that ID before any resend. `kind=rejected` means a definite broker HTTP 3xx/4xx response. `kind=not_sent` means the local send deadline prevented transport. Other process failures must never be treated as proof the broker rejected a write.
</principle>

<principle name="Credential Storage and Streaming">
Use `webull auth login` for hidden app key/secret prompts and `webull auth token` for a hidden token prompt or securely piped input. Reusable credentials live in the CLI-tools secret manager, never raw `.env` values or command arguments.

REST output preserves full broker JSON by default. Order open/history return one unchanged page; the caller follows its cursor. `futures stream` emits JSONL tick, disconnect, and error events until interrupted. Every disconnect invalidates previously buffered prices; error events require explicit recovery rather than silent continuation.
</principle>

<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `webull` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `webull --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **account** -- Inspect Webull accounts (subcommands: balance, get, list, positions)
- **auth** -- Manage webull authentication (subcommands: login, logout, profiles, status, test, token)
- **futures** -- Read futures market data (subcommands: bars, stream)
- **order** -- Inspect and manage broker orders (subcommands: cancel, get, history, list, open, place, replace)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`webull --help` and subcommand `--help`** -- Live installed command tree and option list.
**[Webull CLI README](../../../webull/README.md)** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
