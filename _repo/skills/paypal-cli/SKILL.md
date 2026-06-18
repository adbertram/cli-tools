---
name: paypal-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute paypal operations using the `paypal` CLI tool.
  CLI interface for PayPal API.
  Triggers: paypal, paypal cli, paypal payouts, send paypal payment, paypal batch payout, pay someone with paypal, paypal payout status, my paypal, paypal auth profiles
---

<objective>
Execute paypal operations using the `paypal` CLI. All paypal interactions should use this CLI.
</objective>

<quick_start>
The `paypal` CLI follows this pattern:
```bash
paypal <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check auth status | `paypal auth status` |
| Send a payout | `paypal payouts create --receiver user@example.com --amount 10.00` |
| Check batch status | `paypal payouts get BATCH_ID` |
| Get payout item | `paypal payouts get-item ITEM_ID` |
| Cancel unclaimed payout | `paypal payouts cancel-item ITEM_ID` |
| Preview a direct capture refund | `paypal refunds create CAPTURE_ID --amount 4.50 --dry-run` |
| Preview a BrickLink refund | `paypal refunds from-bricklink ORDER_ID --amount 4.50 --dry-run` |
| Preview with verified BrickLink order JSON | `paypal refunds from-bricklink ORDER_ID --order-json order-context.json --amount 4.50 --dry-run` |
| Refresh browser session | `paypal auth login -c browser_session --force` |
| List profiles | `paypal auth profiles list --table` |
| Switch profile | `paypal auth profiles set-default production` |

Auth status output uses the shared profile shape: `{"profiles":[{"name":"default","authenticated":true,"credential_types":{...}}]}`. Read `auth profiles[].authenticated` for per-profile status; do not expect a flat top-level `authenticated` field.
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `paypal` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **payouts** -- Manage batch payouts (list, create, get, get-item, cancel-item)
- **refunds** -- Issue full or partial direct capture refunds through the PayPal API, or BrickLink-assisted refunds through the PayPal unified transactions browser session
- **transactions** -- Search PayPal transaction-reporting records
- **auth** -- Authentication commands and nested `auth profiles` management
</principle>

<principle name="Browser-Session Auth Uses PTY-Backed CLI Login">
When PayPal browser auth is missing, expired, CAPTCHA-blocked, or needed for
unified transactions/refunds, run `paypal auth login -c browser_session --force`
from Codex `exec_command` with `tty: true` so the CLI can read its final
confirmation from `/dev/tty`. Let the CLI open a normal Chrome window with no
automation attached. Adam completes PayPal login/CAPTCHA in that window; after
the CLI is waiting for confirmation, send Enter with `write_stdin`.

Do not route this through Computer Use or Terminal.app. Computer Use is not
authorized to control `com.apple.Terminal`, and Terminal control is unnecessary
when Codex can launch a PTY-backed command directly. If PTY allocation fails
before the shell starts, preserve the exact `openpty` error and switch to
another authorized execution surface that can provide an interactive TTY; do not
continue with a non-TTY launch for this browser-session confirmation. Do not
script PayPal credential entry, CAPTCHA navigation, or browser-session capture
with Playwright, browser-harness, or custom Chrome automation outside this auth
command.
</principle>

<principle name="Refunds Use CLI Commands, Not Browser Amount Fields">
PayPal refunds must use `paypal refunds create` for known capture IDs or
`paypal refunds from-bricklink` for BrickLink orders. Start with `--dry-run`,
verify the printed request, then use `--yes` only when the refund is explicitly
approved. `from-bricklink` reads `bricklink order get` by default; use
`--order-json` when a customer-service workflow already has verified BrickLink
order JSON or when the live BrickLink lookup is blocked. It searches PayPal
unified transactions from the saved browser session, verifies buyer
email/name/date/amount/refundability, and posts the refund payload through the
authenticated PayPal page. Do not use PayPal's web refund sheet manually or
`playwright-cli fill` on the refund amount input. PayPal's masked currency
field can preserve or transform existing digits even when automation reports a
successful fill; that can produce an incorrect amount before the final submit
button is clicked.
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
