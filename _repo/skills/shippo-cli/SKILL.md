---
name: "shippo-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute shippo operations using the `shippo` CLI tool. CLI interface for Shippo shipping API - Create USPS labels, compare rates, track packages. Triggers: shippo, shippo cli, shipping label, create label, shipping rates, track package, shippo shipment, compare shipping, USPS label, shipping address"
---

<objective>
Execute shippo operations using the `shippo` CLI. All shipping label and tracking interactions should use this CLI.
</objective>

<quick_start>
The `shippo` CLI follows this pattern:
```bash
shippo <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List addresses | `shippo addresses list --table` |
| Create shipment | `shippo shipments create ...` |
| View rates | `shippo rates list SHIPMENT_ID --table` |
| Purchase label | `shippo labels create RATE_ID` |
| Download label | `shippo labels download LABEL_ID` |
| Track package | `shippo tracking get TRACKING_NUMBER` |
| List carriers | `shippo carriers list --table` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `shippo` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **addresses** -- Manage saved addresses (list, get, create, validate)
- **shipments** -- Create shipments, view rates (list, get, create)
- **rates** -- View and compare shipping rates (list, get, estimate)
- **labels** -- Purchase and manage labels (list, get, create, download, print, void)
- **tracking** -- Track shipments (list, get, register)
- **carriers** -- Manage carrier accounts (list, get)
- **auth** -- Manage authentication (login, logout, status, refresh, test)
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
