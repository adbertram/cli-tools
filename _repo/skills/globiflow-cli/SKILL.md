---
name: "globiflow-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute globiflow operations using the `globiflow` CLI tool. CLI interface for Globiflow automation platform (browser automation) -- manage flows, steps, triggers, and search items. Triggers: globiflow, globiflow cli, globiflow flows, globiflow triggers, list globiflow flows, create globiflow flow, globiflow automation, globiflow steps, search globiflow"
---

<objective>
Execute globiflow operations using the `globiflow` CLI. All globiflow interactions should use this CLI.
</objective>

<quick_start>
The `globiflow` CLI follows this pattern:
```bash
globiflow <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List all flows | `globiflow flows list --table` |
| Get flow details | `globiflow flows get FLOW_ID --table` |
| Create a flow | `globiflow flows create --app-id ID --trigger C --name "Name"` |
| View flow logs | `globiflow flows logs FLOW_ID --table` |
| List flow steps | `globiflow flows steps list --flow-id FLOW_ID --table` |
| Add a step to a flow | `globiflow flows steps add FLOW_ID --action "Add Comment" --comment "text"` |
| List trigger types | `globiflow triggers list --table` |
| Search items | `globiflow search query "keyword" --table` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `globiflow` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Browser-based authentication (login, status, test, logout)
- **search** -- Search and browse Globiflow items (query, item, list)
- **flows** -- Manage automation flows (list, create, get, logs, delete, steps)
- **triggers** -- View available trigger types for flow creation (list, get)
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
