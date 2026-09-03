---
name: trainee-digital-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute TraineeDigital operations using the `trainee-digital` CLI tool.
  CLI interface for TraineeDigital.
  Triggers: trainee-digital, trainee-digital cli
---

<objective>
Execute TraineeDigital operations using the `trainee-digital` CLI. All TraineeDigital interactions should use this CLI.
</objective>

<quick_start>
The `trainee-digital` CLI follows this pattern:
```bash
trainee-digital <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Configure authentication credentials | `trainee-digital auth login` |
| Clear stored credentials and browser sessions | `trainee-digital auth logout` |
| Create a new profile from .env.example template | `trainee-digital auth profiles create <NAME>` |
| Delete a profile and its data | `trainee-digital auth profiles delete <NAME>` |
| Get details for a specific profile | `trainee-digital auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `trainee-digital auth profiles list` |
| Delete a profile and its data | `trainee-digital auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `trainee-digital auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `trainee-digital auth profiles select <NAME>` |
| Check authentication status across profiles | `trainee-digital auth status` |
| Test authentication by verifying credentials work across profiles | `trainee-digital auth test` |
| Remove all cached responses | `trainee-digital cache clear` |
| Apply to an order | `trainee-digital tasks apply <ORDER_ID>` |
| Get the full detail for a single order | `trainee-digital tasks get <ORDER_ID>` |
| List the open annotation orders on the trainee.digital order feed | `trainee-digital tasks list` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `trainee-digital` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `trainee-digital --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage trainee-digital authentication (subcommands: login, logout, profiles, status, test)
- **cache** -- Manage response cache (subcommands: clear)
- **tasks** -- Manage trainee.digital worker orders (subcommands: apply, get, list)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`trainee-digital --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
