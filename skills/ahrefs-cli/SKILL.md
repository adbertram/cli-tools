---
name: "ahrefs-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute ahrefs operations using the `ahrefs` CLI tool. CLI interface for Ahrefs SEO platform (browser automation) -- site audits, authentication, profiles, and caching. Triggers: ahrefs, ahrefs cli, site audit, ahrefs site audit, ahrefs SEO, ahrefs crawl, ahrefs login, ahrefs auth profiles, check ahrefs auth, run site audit"
---

<objective>
Execute ahrefs operations using the `ahrefs` CLI. All Ahrefs interactions should use this CLI.
</objective>

<quick_start>
The `ahrefs` CLI follows this pattern:
```bash
ahrefs <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check auth status | `ahrefs auth status` |
| Login to Ahrefs | `ahrefs auth login` |
| List site audit crawls | `ahrefs site-audit list <project_id>` |
| Get full site audit report | `ahrefs site-audit get <project_id>` |
| List profiles | `ahrefs auth profiles list` |
| Clear response cache | `ahrefs cache clear` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `ahrefs` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Authentication commands and nested `auth profiles` management
- **auth** -- Authentication management (login, status, test, logout)
- **cache** -- Manage response cache (clear)
- **site-audit** -- Site audit operations (list crawls, get reports, manage audit cache)
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
