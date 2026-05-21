<process>
## Step 1: Verify CLI Exists

Confirm the target CLI tool exists:

```bash
ls <cli-tools-root>/<name>
ls -la ~/.local/bin/<name>
```

If the directory does not exist, inform the user and stop.

## Step 2: Show What Will Be Removed

Present the user with what will be removed:
- Directory: `<cli-tools-root>/<name>/`
- Symlink: `~/.local/bin/<name>` (if exists)
- cli_tools.md table entry

**Use AskUserQuestion** to confirm:
- Question: "The following will be permanently removed for '<name>'. Proceed?"
- Options:
  - "Yes, remove everything" - Continue with removal
  - "Cancel" - Abort the operation

**Wait for user confirmation before proceeding.**

## Step 3: Run Removal Script

```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/remove-cli-tool.sh "<name>"
```

## Step 4: Update cli_tools.md

Edit `<cli-tools-root>/_repo/docs/cli_tools.md` to remove the table row for `<name>` from the CLI tools table.

## Step 5: Verify Removal

Confirm:
```bash
# Directory should be gone
ls <cli-tools-root>/<name> 2>&1
# Symlink should be gone
ls -la ~/.local/bin/<name> 2>&1
```

Report removal status to user.
</process>

<success_criteria>
Removal is complete when:
- [ ] User confirmed the removal
- [ ] CLI tool directory deleted
- [ ] Symlink removed (if it existed)
- [ ] cli_tools.md table entry removed
- [ ] Verification confirms all artifacts gone
</success_criteria>
