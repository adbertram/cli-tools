# usage.json Schema & Writing Guide

## Schema

```json
{
  "tool": "string — CLI tool name",
  "description": "string — tool description from --help",
  "discovered_at": "string — ISO 8601 timestamp of discovery",
  "total_commands": "number — count of leaf commands",
  "usage_instructions": "string — AI-written: when/how to use this tool",
  "global_options": [
    {
      "name": "--flag",
      "short": "-f",
      "type": "TEXT | INTEGER | FLOAT | PATH | bool",
      "required": false,
      "help": "description from --help",
      "default": "optional default value",
      "env_var": "optional env var name"
    }
  ],
  "commands": {
    "group_name": {
      "help": "description from --help",
      "usage_instructions": "string — AI-written: what this group is for",
      "commands": {
        "leaf_command": {
          "help": "description from --help",
          "usage_instructions": "string — AI-written: when/how to use this command",
          "arguments": [
            {
              "name": "arg_name",
              "type": "TEXT | PATH | INTEGER",
              "required": true,
              "help": "description",
              "default": "optional"
            }
          ],
          "options": [
            {
              "name": "--option",
              "short": "-o",
              "type": "TEXT | INTEGER | bool",
              "required": false,
              "help": "description",
              "default": "optional"
            }
          ],
          "ai_instruction_result": {
            "may_return": true,
            "result_type": "ai_instruction",
            "schema_version": "1.0",
            "notes": "optional; command may return an AI instruction handoff instead of normal data"
          },
          "examples": ["tool cmd arg --flag"]
        }
      }
    }
  }
}
```

## AI Instruction Metadata

Leaf commands may include `ai_instruction_result` when the command can return a first-class AI handoff result. This metadata tells future agents that normal command output is not the only successful result shape.

Required shape when present:

```json
{
  "ai_instruction_result": {
    "may_return": true,
    "result_type": "ai_instruction",
    "schema_version": "1.0",
    "notes": "short explanation of when this command hands work to the AI agent"
  }
}
```

Rules:
1. `ai_instruction_result` belongs on leaf commands only.
2. Do not add `required_commands`, `command_to_run`, or any pre-action command list to this metadata.
3. Verification and follow-up commands belong in the runtime AI instruction payload after the AI work, not in `usage.json`.
4. The command still exits successfully when it returns `type: "ai_instruction"`.

## Writing `usage_instructions`

The `usage_instructions` field is added by Codex after discovery. It exists at three levels:

### Root level
Explain when to reach for this tool and the general pattern:
> "Use for managing Dropbox files and folders. Commands follow `dropbox <group> <action>` pattern. Most list commands support --table, --filter, --limit, and --properties."

### Group level
Explain what this command group handles:
> "File operations — listing, uploading, downloading, moving, copying, and deleting files and folders in Dropbox."

### Leaf command level
Be specific and actionable. Include flag names in descriptions:
> "List files in a Dropbox directory. Use --recursive/-R for subdirectories. Use --long/-l for detailed info (size, modified date). Default limit is 50; increase with --limit. Path is optional — omits for root."

### Writing rules
1. **Be specific** — "Use --recursive/-R to include subdirectories" not "supports recursive listing"
2. **Include flag names** — always mention both --long and -short forms
3. **Mention defaults** — "Default limit is 50" when it matters
4. **Note positional args** — "PATH is optional, defaults to root"
5. **Reference related commands** — "See also: files get for single file info"
6. **Keep it short** — 1-3 sentences per command
7. **Focus on when** — "Use when you need to..." helps Codex match user intent to commands
8. **Preserve command paths** — use the exact discovered path. For shared CLI auth profiles, write `auth profiles list` and related nested commands, not top-level `profiles list`.

## SKILL.md Trigger Phrases

The `Triggers:` line in the SKILL.md description determines when Codex auto-loads the skill. Minimal triggers (e.g., just `dropbox, dropbox cli`) cause missed matches when users use natural language.

**Always generate 5-10 trigger phrases** including:
- Command group names: `{tool} files`, `{tool} orders`, `{tool} account`
- Common action phrases: `list files in {tool}`, `search {tool}`, `download from {tool}`
- Data-oriented phrases: `files in {tool}`, `{tool} data`, `my {tool}`

Match how users naturally describe tasks, not just how commands are named.
