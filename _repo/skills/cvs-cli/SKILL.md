---
name: cvs-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute cvs operations using the `cvs` CLI tool.
  CLI interface for CVS Health -- prescriptions, orders, and refills.
  Triggers: cvs, cvs cli, cvs prescriptions, cvs orders, cvs refills, check my prescriptions, prescription status, refill eligibility, cvs pharmacy, my cvs prescriptions, cvs order status
---

<objective>
Execute cvs operations using the `cvs` CLI. All CVS pharmacy interactions should use this CLI.
</objective>

<quick_start>
The `cvs` CLI follows this pattern:
```bash
cvs <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List all prescriptions | `cvs prescriptions list --table` |
| Get prescription details | `cvs prescriptions get <rx_id>` |
| Check refill eligibility | `cvs refills check --table` |
| List order history | `cvs orders list --table` |
| Get order details | `cvs orders get <order_id>` |
| Check auth status | `cvs auth status` |
| Login (browser) | `cvs auth login` |
</quick_start>

<browser_auth_login>
`cvs auth login` is an interactive visible-browser handoff. It opens a normal
browser window with no automation attached and then waits for terminal input so
the user can confirm that login, OTP, and any CAPTCHA are complete before the
CLI captures the session. **Do not run `cvs auth login` as a foreground
non-PTY Hermes terminal command**; without an interactive `/dev/tty` the command
can wait until the tool timeout after printing guidance such as `Device not
configured: '/dev/tty'`.

For Hermes/Codex, use a PTY-capable interactive surface (`terminal(...,
pty=true)` / `exec_command` with `tty: true`, then send Enter only after the
user-visible login is complete) or an explicitly approved visible-browser
handoff that provides terminal input. Do not script CVS credential entry,
CAPTCHA, OTP, or browser-session capture with browser automation; the safe
automation boundary is launching the CLI and handing the normal browser window
to the user.
</browser_auth_login>

<expected_status_probes>
`cvs auth status` may legitimately return a non-zero status when it reports
unauthenticated live state (for example `authenticated: false` or
`browser_session: false`). When auth state is being investigated, do not run
`cvs auth status --table` as a bare terminal command. Wrap it so the command
output is preserved as evidence and the wrapper exits 0 for expected
unauthenticated states; reserve non-zero exits for command/runtime failures or
final validation that requires an authenticated session.
</expected_status_probes>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `cvs` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **prescriptions** -- View prescriptions across all linked family members (drug info, fill history, prescriber, refill status)
- **orders** -- View CVS order history (pickup/delivery status, cost breakdown)
- **refills** -- Check which prescriptions are eligible for refill or renewal
- **auth** -- Manage authentication (browser-based login with CAPTCHA/OTP)
- **cache** -- Manage cached API responses
- **auth** -- Authentication commands and nested `auth profiles` management
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
