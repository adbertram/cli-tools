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

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `cvs` command.**
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
