---
name: cli-tool-testing
description: >-
  MANDATORY: Use this skill when Adam asks to test multiple cli-tools,
  run cli-tool test coverage across a named set of CLI tools, or ensure all
  tests pass for provided CLI tools. DO NOT test a multi-CLI set inline when
  independent cli-tool-expert subagents can run in parallel. Triggers: test
  these cli tools, test each cli tool, ensure all tests pass, parallel CLI
  testing, cli-tool-testing.
---

<objective>
Launch independent cli-tool-expert subagents in parallel to test each provided
CLI tool and drive each one to passing tests unless a true human-only
authentication blocker prevents completion.
</objective>

<quick_start>
1. Parse the invocation context for the exact CLI tool names Adam provided.
2. Load `/Users/adam/Dropbox/.agents/skills/agent-expert/references/global-standards.md`.
3. Spawn one independent `cli-tool-expert` subagent per CLI tool in the same parent turn when the tools are independent.
4. Use the prompt template below for every subagent, with only the tool-specific values changed.
5. Wait for every subagent result, preserve the full user-facing results, and report pass/fail/blocker status per CLI.
</quick_start>

<required_inputs>
- One or more CLI tool names.
- Optional scope such as a specific command group, regression, branch, or test command.
</required_inputs>

<routing>
If no CLI tool names are provided, ask Adam for the tool names before spawning
subagents. Do not infer tool names from vague wording.

If one CLI tool is provided, still use `cli-tool-expert` for the work.

If multiple CLI tools are provided, use parallel subagents unless the requested
tools share a known write target or one tool's result is required before another
can start.
</routing>

<workflow_index>
- `workflows/test-cli-tools.md` - Parallel CLI testing workflow.
</workflow_index>

<reference_index>
- `references/delegation.md` - Subagent prompt and authentication policy.
</reference_index>

<delegation_rules>
- Use Codex `spawn_agent` with agent `cli-tool-expert`.
- Do not use `fork_context`.
- Each prompt must be self-contained and include the repo path, tool name,
  constraints, authentication policy, and expected output.
- Every prompt must explicitly reference
  `/Users/adam/Dropbox/.agents/skills/agent-expert/references/global-standards.md`.
- Before interrupting or closing a slow subagent, use the available status
  mechanism and request current results once if appropriate.
- Do not close an active subagent only because it is slow.
</delegation_rules>

<subagent_prompt_template>
Use this prompt for each CLI tool:

```text
You are the cli-tool-expert subagent. Apply the global custom-agent standards
from /Users/adam/Dropbox/.agents/skills/agent-expert/references/global-standards.md.

Task: test the <TOOL_NAME> CLI tool in /Users/adam/Dropbox/GitRepos/cli-tools and ensure all tests pass.

Scope:
- CLI tools root: /Users/adam/Dropbox/GitRepos/cli-tools
- Tool name: <TOOL_NAME>
- Optional requested scope: <REQUESTED_SCOPE_OR_NONE>

Required workflow:
1. Load and follow /Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills/cli-tool/SKILL.md.
2. Use the repo-owned CLI test workflow and scripts, especially
   /Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name <TOOL_NAME>.
3. Use the installed launcher or the tool's own uv interpreter for smoke tests.
4. Fix implementation failures at the source. Do not weaken tests, skip failures,
   add fallback logic, or work around broken APIs.
5. Re-run the relevant tests until there are zero failures and zero errors, or
   until a true human-only authentication blocker prevents completion.

Authentication policy:
- If auth fails and browser authentication is required, use Computer Use with
  the visible browser/authentication flow to create the required authenticated
  browser state.
- Use available credential and message tools when needed, including LastPass,
  Gmail, and iMessage CLI, to obtain passwords, codes, or account context that
  are available without Adam's live intervention.
- Skip only tests that absolutely require a human action outside the computer,
  such as approving MFA on another device. Report those skipped tests as blocked
  with the exact human action required.
- Do not mark the CLI as passing if required tests were skipped for auth.

Expected output:
- Overall status: passed, fixed-and-passed, or blocked.
- Test commands run and final results.
- Files changed, if any.
- Authentication work performed, if any.
- Exact blockers and next human action for any test that could not run.
- Issues encountered, or "No issues encountered".
```
</subagent_prompt_template>

<parent_summary>
After all subagents return, relay each subagent's complete user-facing result.
Then provide a compact rollup:

| CLI | Status | Final verification | Blocker |
| --- | --- | --- | --- |
| `<tool>` | passed/fixed-and-passed/blocked | `<command/result>` | `<none or exact action>` |

Do not compress away artifacts, failures, exact blockers, or verification
commands the subagents reported.
</parent_summary>

<success_criteria>
- Every provided CLI tool was assigned to an independent `cli-tool-expert` subagent.
- Parallelizable tools were tested in parallel.
- Each subagent prompt was self-contained and referenced the global standards file.
- Authentication failures were handled through Computer Use and available credential/message tools before declaring a blocker.
- The final response preserves each subagent's result and identifies every remaining human-only auth blocker.
</success_criteria>
