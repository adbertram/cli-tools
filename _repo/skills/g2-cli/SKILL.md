---
name: g2-cli
description: >-
  MANDATORY: Execute G2 operations using the `g2` CLI. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. Execute g2 operations using the `g2` CLI tool.
  CLI interface for G2 API. Triggers: g2, g2 cli, g2 products, g2 reviews, g2 negative reviews, search g2 products, search g2 reviews, g2 product reviews, g2 auth, g2 profiles
---

<objective>
Execute G2 operations using the `g2` CLI. All G2 product and review discovery should use this CLI.
</objective>

<quick_start>
The `g2` CLI follows this pattern:
```bash
g2 <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check authentication status | `g2 auth status` |
| Save or refresh a personal access token | `g2 auth login` |
| Search products | `g2 products search QUERY` |
| Get one product by slug | `g2 products get PRODUCT_SLUG` |
| List negative reviews for a product | `g2 reviews list PRODUCT_SLUG --stars 1 --stars 2` |
| Search review text for a product | `g2 reviews search PRODUCT_SLUG QUERY --stars 1 --stars 2` |
| Get one accessible review by ID, survey response ID, or slug | `g2 reviews get REVIEW_ID` |
| Clear cached responses | `g2 cache clear` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `g2` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `g2` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload. Run `verification_commands` or `follow_up_commands` only after completing the instructed AI work; they are not required commands for performing the handoff.
</principle>

<principle name="Command Groups">
- **products** -- Find G2 products, inspect one product by slug, and search normalized product output fields.
- **reviews** -- List negative reviews for a product slug, inspect one accessible review from Data Solutions review data, and search normalized review output fields. Review commands require the token to be entitled for review data.
- **auth** -- Save, clear, test, and inspect G2 personal access token profiles.
- **cache** -- Remove cached API responses.
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
