# Update CLI Tool Skill

<required_reading>
- [references/json-schema.md](../references/json-schema.md) — usage.json schema and writing guide
</required_reading>

<process>

## Step 1: Verify Existing Skill

```bash
ls <cli-tools-root>/_repo/skills/<tool>-cli/usage.json
```

If no existing skill, redirect to `workflows/create-skill.md`.

## Step 2: Re-run Discovery

```bash
python3 {baseDir}/scripts/discover-cli.py \
  <tool> --include-examples \
  --output /tmp/<tool>-rediscovery.json
```

## Step 3: Diff Against Existing

Read both files:
- Existing: `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json`
- New: `/tmp/<tool>-rediscovery.json`

Identify:
- **Added commands** — new commands not in existing
- **Removed commands** — commands in existing but not in new discovery
- **Changed commands** — options/arguments that changed
- **Nested command drift** — any discovered nested command that the existing skill flattened or omitted, especially `auth profiles ...`

Report the diff to the user before proceeding.

## Step 4: Merge

For each command in the new discovery:
- **Unchanged** — keep existing `usage_instructions` as-is
- **New** — write fresh `usage_instructions`
- **Changed** — update `usage_instructions` to reflect new options/arguments
- **Removed** — drop from output (mention to user)

Write merged result to `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json`.

## Step 5: Update SKILL.md (if needed)

If command groups changed (added/removed), update the SKILL.md:
- Update `{command_groups}` in essential_principles
- Update `{common_commands}` in quick_start if affected

## Step 6: Validate

```bash
<cli-tools-root>/_repo/skills/create-cli-tool-skill/scripts/validate-usage-json.sh <cli-tools-root>/_repo/skills/<tool>-cli/usage.json
```

## Step 7: Clean Up

```bash
rm /tmp/<tool>-rediscovery.json
```

</process>

<success_criteria>
- Existing usage_instructions preserved for unchanged commands
- New commands have fresh usage_instructions
- Removed commands reported to user and dropped
- Changed commands have updated usage_instructions
- Nested command paths are preserved exactly as re-discovered
- Validation passes
</success_criteria>
