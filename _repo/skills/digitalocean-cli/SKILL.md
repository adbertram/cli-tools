---
name: digitalocean-cli
description: >-
  Execute digitalocean operations using the `digitalocean` CLI tool.
  CLI interface for Digitalocean API.
  Triggers: digitalocean, digitalocean cli, digitalocean droplets, digitalocean auth, digitalocean cache, list digitalocean droplets, get digitalocean droplet
---

<objective>
Execute digitalocean operations using the `digitalocean` CLI. All digitalocean interactions should use this CLI.
</objective>

<quick_start>
The `digitalocean` CLI follows this pattern:
```bash
digitalocean <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List droplets | `digitalocean droplets list` |
| Get details for a specific droplet | `digitalocean droplets get DROPLET_ID` |
| Search droplets with wildcard pattern matching. Supports * wildcards for pattern matching across all string fields | `digitalocean droplets search "*prod*"` |
| Configure authentication credentials. Prompts for required credentials based on the tool's authentication type. For OAuth authorization code flows, opens a browser for user consent | `digitalocean auth login` |
| Clear stored credentials and browser sessions | `digitalocean auth logout` |
| Check authentication status across profiles | `digitalocean auth status --table` |
| Refresh OAuth access token using stored refresh token | `digitalocean auth refresh --table` |
| Test authentication by verifying credentials work across profiles | `digitalocean auth test --table` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `digitalocean` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="AI Instruction Results">
After every `digitalocean` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output. Use the allowed tools, context, constraints, and success criteria in the payload.
</principle>

<principle name="Command Groups">
- **droplets** -- Manage DigitalOcean droplets
- **auth** -- Manage digitalocean authentication
- **cache** -- Manage response cache
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
