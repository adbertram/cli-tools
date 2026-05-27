---
name: "dribbble-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute dribbble operations using the `dribbble` or `dribble` CLI tool. CLI interface for Dribbble public shot search, public shot image downloads, and authenticated owner shots. Triggers: dribbble, dribbble cli, dribble, dribble cli, search dribbble, dribbble public shots, dribbble designs, download dribbble shots, list dribbble shots, get dribbble shot, my dribbble, dribbble auth profiles"
---

<objective>
Execute Dribbble operations using the `dribbble` CLI. All Dribbble interactions should use this CLI.
</objective>

<quick_start>
The `dribbble` CLI follows this pattern:
```bash
dribbble <command-group> <action> [arguments] [options]
```

`dribble` is an installed alias for the same CLI.

| Task | Command |
|------|---------|
| Search public shots | `dribbble designs search "mobile app" --limit 10` |
| Get a public shot | `dribbble designs get 24911825 --properties "id,title,author,html_url,image_url"` |
| Download public shot images | `dribbble designs download 24911825 --output-dir ./downloads` |
| List authenticated user's shots | `dribbble designs list --limit 10` |
| Check auth status | `dribbble auth status` |
| Start OAuth login | `dribbble auth login` |
| Force OAuth login | `dribbble auth login --force` |
| List profiles | `dribbble auth profiles list --table` |
| Clear cache | `dribbble cache clear` |

Auth status output uses the shared profile shape: `{"profiles":[{"name":"default","authenticated":true,"credential_types":{...}}]}`. Read `auth profiles[].authenticated` for per-profile status; do not expect a flat top-level `authenticated` field.
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `dribbble` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Public vs Owned Shots">
Use `dribbble designs search`, `dribbble designs get`, and `dribbble designs download` for public Dribbble shots. Use `dribbble designs list` only when the user asks for shots owned by the authenticated Dribbble account.
</principle>

<principle name="Command Groups">
- **designs** -- Search public Dribbble shots, get public shot details, download public shot images, and list the authenticated user's own shots.
- **auth** -- Manage Dribbble OAuth login, status, logout, tests, and nested `auth profiles`.
- **cache** -- Clear cached Dribbble read responses.
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
