---
name: shopify-cli
description: >-
  Execute shopify operations using the `shopify` CLI tool.
  CLI interface for Shopify API.
  Triggers: shopify, shopify cli, shopify items, shopify auth, shopify cache, search shopify, list shopify items, shopify data, my shopify, list shopify products, search shopify items
---

<objective>
Execute shopify operations using the `shopify` CLI. All shopify interactions should use this CLI.
</objective>

<quick_start>
The `shopify` CLI follows this pattern:
```bash
shopify <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Get details for a specific item. | `shopify items get` |
| List items. | `shopify items list` |
| Search items with wildcard pattern matching. Supports * wildcards for pattern matching across all string fields. | `shopify items search` |
| Configure authentication credentials. Prompts for required credentials based on the tool's authentication type. For OAuth authorization code flows, opens a browser for user consent. | `shopify auth login` |
| Clear stored credentials. | `shopify auth logout` |
| Create a new profile from .env.example template. | `shopify auth profiles create` |
| Delete a profile and its data. | `shopify auth profiles delete` |
| Get details for a specific profile. | `shopify auth profiles get` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `shopify` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `shopify` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **items** -- Manage shopify items
- **auth** -- Manage shopify authentication
- **cache** -- Manage response cache
</principle>
</essential_principles>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
