---
name: "create-cli-tool-skill"
description: "MANDATORY: SUPPORTING SKILL for cli-tool-expert. Parent sessions must delegate CLI tool skill generation or refresh work to the cli-tool-expert agent. DO NOT create or update CLI tool skills inline outside cli-tool-expert. When loaded inside cli-tool-expert, creates standardized Codex skills for CLI tools by discovering commands via --help parsing and generating usage.json with usage_instructions. Triggers: create cli skill, cli tool skill, generate cli reference, discover cli commands, document cli."
---

<objective>
Create, update, and list Codex skills for CLI tools. Use deterministic `--help` parsing to discover the full command tree, then add `usage_instructions` that help Codex map user intent to the right commands.
</objective>

<agent_routing>
When this skill is invoked by a parent Codex or Claude session and the current agent is not `cli-tool-expert`, delegate the work to `cli-tool-expert` instead of creating or updating CLI tool skills inline. Pass the complete user request, relevant file paths, constraints, and required validation.

When the current agent is `cli-tool-expert`, follow this skill normally.
</agent_routing>

<quick_start>
Discovery command:

```bash
python3 {baseDir}/scripts/discover-cli.py <tool> --include-examples
```

Generated skills go to the cli-tools repo:

```text
<cli-tools-root>/skills/<tool>-cli/   # SKILL.md + usage.json
```
</quick_start>

<essential_principles>
<principle name="Two-Phase Process">
**Phase 1 (Deterministic):** `scripts/discover-cli.py` parses `--help` output to produce structural JSON with all commands, arguments, options, and examples.
**Phase 2 (AI):** Codex reads the JSON and adds `usage_instructions` at root, group, and leaf levels so future skill invocations have instant command knowledge.
</principle>

<principle name="Generated Skill Structure">
Each generated skill is simple — just two files:
```
<cli-tools-root>/skills/<tool>-cli/
├── SKILL.md       # Frontmatter + quick reference + pointer to usage.json
└── usage.json     # Full command tree with usage_instructions
```
</principle>

<principle name="CLI Tools Location">
All CLI tools live in `<cli-tools-root>/` and are Python Typer apps. The discovery script works with any Typer/Click/Rich CLI tool on PATH.
</principle>

<principle name="Preserve Nested Command Paths">
Discovery and enrichment must preserve the CLI's actual command paths. Do not flatten nested subcommands. If a CLI exposes `auth profiles`, generated `usage.json` and `SKILL.md` content must include `auth profiles ...`, not top-level `profiles ...`.
</principle>

<principle name="AI Instruction Result Awareness">
Generated CLI skills must tell agents how to handle `type: "ai_instruction"` stdout. When usage metadata marks a command as able to return an AI instruction result, preserve that metadata and do not add required pre-action command lists.
</principle>
</essential_principles>

<intake>
What would you like to do?

1. **Create** a skill for a CLI tool
2. **Update** an existing CLI tool skill (re-discover, merge changes)
3. **List** all generated CLI tool skills

If the user's intent is clear (e.g., "create a skill for dropbox"), route directly without asking.
</intake>

<routing>
| Response | Workflow |
|----------|----------|
| 1, "create", "new", "generate", "build" | workflows/create-skill.md |
| 2, "update", "refresh", "re-discover", "sync" | workflows/update-skill.md |
| 3, "list", "show", "which" | workflows/list-skills.md |

**After reading the workflow, follow it exactly.**
</routing>

<reference_index>
**Schema & Writing Guide:** references/json-schema.md — usage.json structure and usage_instructions writing rules
**Template:** templates/SKILL.md.template — Template for generated CLI tool skills
</reference_index>

<workflows_index>
| Workflow | Purpose |
|----------|---------|
| create-skill.md | Discover CLI, generate usage.json + SKILL.md |
| update-skill.md | Re-discover and merge changes into existing skill |
| list-skills.md | List all generated *-cli skills |
</workflows_index>

<known_issues>
<issue name="Root-Level Leaf Commands in usage.json Validation">
**Symptom:** `scripts/validate-usage-json.sh <path>/usage.json` exits before the cross-reference checks after printing `PASS: Command 'record' has usage_instructions` or equivalent for a CLI whose `.commands` object contains root-level leaf commands instead of command groups.
**Cause:** Older validator logic treated every `.commands` entry as a group and ran `jq '.commands["name"].commands | keys[]'`; under `set -e`, `jq` exits nonzero when the leaf command has no child `commands` object.
**Fix:** Keep `validate-usage-json.sh` command-aware: check whether `.commands["name"].commands` is an object before iterating leaves, and validate root-level leaf command `usage_instructions` directly.
**Verification:** Run `scripts/validate-usage-json.sh <cli-tools-root>/skills/<tool>-cli/usage.json` against a CLI skill with a root-level leaf command and confirm the summary is `PASSED: 0 errors, 0 warning(s)`.
**Recurrence Prevention:** Do not reintroduce group-only assumptions in usage validators; generated CLI skills may have either root-level leaf commands or nested command groups.
</issue>
</known_issues>

<success_criteria>
- Discovery script finds all commands and options
- Nested command paths are preserved exactly as discovered, including `auth profiles ...` when present
- usage.json has usage_instructions at every level (root, group, leaf)
- Generated SKILL.md passes validation
- Natural language queries map to correct commands when skill is loaded
</success_criteria>
