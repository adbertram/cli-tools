<process>
## Step 1: Run List Script

```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/list-cli-tool.sh
```

## Step 2: Display Results

Present the output with legend:
- **checkmark** = symlinked in `~/.local/bin` (tool is available globally)
- **x** = no symlink (tool not linked, may need `ln -sf` setup)
</process>

<success_criteria>
Listing is complete when:
- [ ] Script executed successfully
- [ ] Results displayed with legend
</success_criteria>
