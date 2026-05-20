# List Generated CLI Skills

<process>

## Step 1: Find All CLI Skills

```bash
for dir in <cli-tools-root>/skills/*-cli/; do
  if [ -f "$dir/usage.json" ]; then
    tool=$(python3 -c "import json; d=json.load(open('$dir/usage.json')); print(d.get('tool','?'), d.get('total_commands','?'), d.get('discovered_at','?')[:10])")
    echo "$tool"
  fi
done
```

## Step 2: Display as Table

| Skill | Tool | Commands | Discovered |
|-------|------|----------|------------|
| (populated from discovery) | | | |

</process>

<success_criteria>
- All *-cli skills with usage.json listed
- Table shows tool name, command count, and discovery date
</success_criteria>
