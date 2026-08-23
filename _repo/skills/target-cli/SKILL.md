---
name: target-cli
description: >-
  MANDATORY: Execute Target operations using the `target` CLI tool. Search
  products and manage browser-backed Target workflows through the existing CLI.
  Do not use raw browser automation or ad hoc scripts when this CLI covers the
  task. Triggers: target, target cli, target search, target products, target auth
---

<objective>
Execute Target operations using the `target` CLI. All Target interactions should use this CLI.
</objective>

<quick_start>
The `target` CLI follows this pattern:
```bash
target <command-group> <action> [arguments] [options]
```

Consult `usage.json` before running any command.
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `target` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Browser Authentication">
Use `target auth login` and `target auth status` for the persistent browser session. Do not hand-roll selectors or browser scripts for actions already exposed by the CLI.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against `usage.json`
</success_criteria>
