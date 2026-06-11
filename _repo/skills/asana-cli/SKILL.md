---
name: asana-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute asana operations using the `asana` CLI tool.
  CLI interface for Asana API -- manage tasks, projects, sections, custom fields, users, and workspaces.
  Triggers: asana, asana cli, asana tasks, asana projects, list asana tasks, create asana task, my asana tasks, search asana, asana workspace, asana sections
---

<objective>
Execute asana operations using the `asana` CLI. All Asana interactions should use this CLI.
</objective>

<quick_start>
The `asana` CLI follows this pattern:
```bash
asana <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List my tasks | `asana tasks list --assignee me` |
| Search tasks | `asana tasks search "query*"` |
| Create a task | `asana tasks create "Task name" --project <id>` |
| Complete a task | `asana tasks complete <task_id>` |
| List projects | `asana projects list` |
| List sections in project | `asana sections list --project <id>` |
| Check auth | `asana auth status` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `asana` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Authentication management (login, logout, status)
- **projects** -- List and view projects
- **tasks** -- Full task CRUD plus search and complete
- **custom-fields** -- List and view custom fields with enum options
- **users** -- List workspace users and get user details
- **workspaces** -- List and view workspaces
- **sections** -- List and view project sections
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
