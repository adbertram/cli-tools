# Create CLI Tool Skill

<required_reading>
- [references/json-schema.md](../references/json-schema.md) — usage.json schema and usage_instructions writing guide
- [templates/SKILL.md.template](../templates/SKILL.md.template) — Generated skill template
</required_reading>

<process>

## Step 1: Identify and Verify CLI Tool

1. Get the tool name from the user (or from context)
2. Verify it's callable:
   ```bash
   <tool> --help
   ```
3. If it fails, check if it needs installation:
   ```bash
   <cli-tools-root>/<tool>/install.sh
   ```

## Step 2: Check for Existing Skill

```bash
ls <cli-tools-root>/_repo/skills/<tool>-cli/ 2>/dev/null
```

- If exists: use `request_user_input` in Plan mode to ask the user to choose **update** (preserves existing usage_instructions) or **overwrite** (fresh start)
- If update: switch to `workflows/update-skill.md`
- If overwrite or doesn't exist: continue

## Step 3: Run Discovery

```bash
python3 {baseDir}/scripts/discover-cli.py \
  <tool> --include-examples \
  --output /tmp/<tool>-discovery.json
```

Review the output:
- Check total_commands count is reasonable
- Verify key commands were discovered
- Note any commands that may have been missed
- Verify nested command paths were preserved. If the CLI has auth profile support, confirm `auth profiles list`, `auth profiles get`, `auth profiles create`, `auth profiles select`, and `auth profiles delete` are present; do not replace them with top-level `profiles` commands.

## Step 4: Add usage_instructions (AI Enrichment)

Read the discovery JSON and the `references/json-schema.md` writing guide.

Add `usage_instructions` to every node:
1. **Root level** — when to use this tool, general patterns, common options
2. **Each command group** — what this group handles
3. **Each leaf command** — specific guidance on when/how to use it, important flags

Rules:
- Be specific and actionable
- Include both --long and -short flag forms
- Mention defaults when they matter
- Note positional vs optional arguments
- Reference related commands
- Keep each to 1-3 sentences

Write the enriched JSON to the skill directory:
```
<cli-tools-root>/_repo/skills/<tool>-cli/usage.json
```

## Step 5: Generate SKILL.md

Read `templates/SKILL.md.template` and fill in:

| Placeholder | Source |
|-------------|--------|
| `{tool_name}` | CLI tool name |
| `{skill_name}` | `<tool>-cli` |
| `{description}` | From discovery JSON `description` field |
| `{common_commands}` | 5-8 most useful commands as a markdown table |
| `{command_groups}` | List of available command groups with descriptions |
| `{natural_triggers}` | Natural language trigger phrases (see below) |

### Generating `{natural_triggers}`

Generate 5-10 natural language phrases a user would say when wanting this tool. Include:
- **Command group names** as triggers: `{tool_name} files`, `{tool_name} orders`, `{tool_name} account`
- **Common action phrases**: `list files in {tool_name}`, `search {tool_name}`, `download from {tool_name}`, `upload to {tool_name}`
- **Data-oriented phrases**: `files in {tool_name}`, `{tool_name} data`, `my {tool_name}`

The goal is to match how users naturally describe tasks. A user saying "list files in dropbox" should trigger the `dropbox-cli` skill — not just "dropbox" or "dropbox cli".

Write to `<cli-tools-root>/_repo/skills/<tool>-cli/SKILL.md`.

## Step 6: Create Skill Directory

```bash
mkdir -p <cli-tools-root>/_repo/skills/<tool>-cli
```

Runtime user-level skill entries should be symlinks to this repo-owned directory. Do not keep separate generated skill copies.

Then write both `SKILL.md` and `usage.json` to the directory.

## Step 7: Validate

```bash
<cli-tools-root>/_repo/skills/create-cli-tool-skill/scripts/validate-usage-json.sh <cli-tools-root>/_repo/skills/<tool>-cli/usage.json
```

Fix any errors or warnings before declaring success.

## Step 8: Clean Up

```bash
rm /tmp/<tool>-discovery.json
```

</process>

<success_criteria>
- Discovery script ran successfully and found all commands
- Nested command paths were preserved exactly, including `auth profiles ...` when present
- usage.json has usage_instructions at root, group, and leaf levels
- SKILL.md has correct frontmatter, quick_start, and reference pointer
- Validation passes with zero errors
- Generated skill directory contains exactly: SKILL.md + usage.json
</success_criteria>
