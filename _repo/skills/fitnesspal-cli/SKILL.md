---
name: fitnesspal-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute fitnesspal operations using the `fitnesspal` CLI tool.
  MyFitnessPal CLI -- view diary, exercises, measurements, reports, food search, recipes, and meals.
  Triggers: fitnesspal, fitnesspal cli, myfitnesspal, food diary, calorie diary, fitness diary, fitnesspal exercises, fitnesspal measurements, fitnesspal recipes, fitnesspal food search
---

<objective>
Execute fitnesspal operations using the `fitnesspal` CLI. All MyFitnessPal interactions should use this CLI.
</objective>

<quick_start>
The `fitnesspal` CLI follows this pattern:
```bash
fitnesspal <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| View food diary | `fitnesspal diary list --table` |
| View exercises | `fitnesspal exercises list --table` |
| View measurements | `fitnesspal measurements list --table` |
| View reports | `fitnesspal reports list --table` |
| Search food | `fitnesspal food list --table` |
| List recipes | `fitnesspal recipes list --table` |
| List meals | `fitnesspal meals list --table` |
| Check auth | `fitnesspal auth status` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `fitnesspal` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **diary** — View food diary entries (list, get)
- **exercises** — View exercise entries (list, get)
- **measurements** — View body measurements (list, get)
- **reports** — View nutrition and fitness reports (list, get)
- **food** — Search and view food items (list, get)
- **recipes** — Manage saved recipes (list, get, create, delete)
- **meals** — View saved meals (list, get)
- **auth** — Manage authentication (login, logout, status, refresh, test)
- **cache** — Manage response cache (clear)
- **auth** -- Authentication commands and nested `auth profiles` management
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
