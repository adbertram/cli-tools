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
- Service skill: `<cli-tools-root>/_repo/skills/<name>-cli/` (if exists)
- Harness config section: `[cli_specific.<name>]` in `<cli-tools-root>/_repo/skills/cli-tool/tests/cli_test_config.toml` (if exists)
- README row: the `<name>` row in `<cli-tools-root>/README.md` (if exists)
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

The script removes the tool directory, the `~/.local/bin/<name>` symlink, the
`_repo/skills/<name>-cli/` service skill, the `[cli_specific.<name>]` section in
`_repo/skills/cli-tool/tests/cli_test_config.toml`, and the tool's row in the root
`README.md`. It also uninstalls the `uv` tool when that tool is installed. Run it
with `--help` for its usage line.

## Step 4: Update cli_tools.md

Edit `<cli-tools-root>/_repo/docs/cli_tools.md` to remove the table row for `<name>` from the CLI tools table. The script prints this exact path when it finishes.

## Step 5: Verify Removal

Confirm:
```bash
# Directory should be gone
ls <cli-tools-root>/<name> 2>&1
# Symlink should be gone
ls -la ~/.local/bin/<name> 2>&1
# Service skill should be gone
ls -d <cli-tools-root>/_repo/skills/<name>-cli 2>&1
# Harness config section should be gone (no output)
grep -n '\[cli_specific\.<name>\]' <cli-tools-root>/_repo/skills/cli-tool/tests/cli_test_config.toml
# README row should be gone (no output)
grep -n '\[`<name>`\](<name>/)' <cli-tools-root>/README.md
```

Report removal status to user.
</process>

<success_criteria>
Removal is complete when:
- [ ] User confirmed the removal
- [ ] CLI tool directory deleted
- [ ] Symlink removed (if it existed)
- [ ] Service skill `_repo/skills/<name>-cli/` deleted
- [ ] `[cli_specific.<name>]` section removed from `_repo/skills/cli-tool/tests/cli_test_config.toml`
- [ ] `<name>` row removed from the root `README.md`
- [ ] cli_tools.md table entry removed
- [ ] Verification confirms all artifacts gone
</success_criteria>
