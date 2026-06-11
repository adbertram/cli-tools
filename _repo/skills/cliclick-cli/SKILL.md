---
name: cliclick-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute cliclick operations using the `cliclick` CLI tool.
  CLI wrapper for cliclick mouse/keyboard automation on macOS.
  Triggers: cliclick, cliclick cli, mouse click, keyboard automation, click coordinates, type text, mouse position, drag and drop, screen automation, macOS mouse control
---

<objective>
Execute cliclick operations using the `cliclick` CLI. All cliclick interactions should use this CLI.
</objective>

<quick_start>
The `cliclick` CLI follows this pattern:
```bash
cliclick <command-group> <action> [arguments] [options]
```

Do not pass native cliclick tokens directly to the wrapper. Commands such as
`cliclick c:100,200` are invalid here and fail because `c:100,200` is parsed as
a top-level command. For a simple click, use `cliclick mouse click 100 200`.
For native cliclick syntax, wrap the full sequence with `cliclick exec run
"c:100,200"`.

| Task | Command |
|------|---------|
| Click at coordinates | `cliclick mouse click 100 200` |
| Double-click | `cliclick mouse double-click 100 200` |
| Get mouse position | `cliclick mouse position` |
| Type text | `cliclick keyboard type "Hello World"` |
| Press key | `cliclick keyboard press return` |
| Run raw commands | `cliclick exec run "c:100,200 w:500 t:hello"` |
| Create script | `cliclick scripts create my-script --content "c:100,200 w:500"` |
| Run script | `cliclick scripts run my-script --var x=100` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `cliclick` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Check cliclick availability and macOS Accessibility permissions
- **mouse** -- Click, double-click, right-click, triple-click, move, drag, position, color-at
- **keyboard** -- Type text, press keys, hold/release modifier keys
- **scripts** -- Create, list, get, run, delete reusable automation scripts
- **exec** -- Execute raw cliclick native command strings and wait
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
