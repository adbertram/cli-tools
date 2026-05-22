<required_reading>
- `../references/delegation.md`
- `/Users/adam/Dropbox/.agents/skills/agent-expert/references/global-standards.md`
</required_reading>

<process>
<step_1>
Extract the exact CLI tool names from the invocation context. If no names are
provided, ask Adam for the names before starting.
</step_1>

<step_2>
For each CLI tool, prepare one self-contained `cli-tool-expert` prompt using
the template in `../references/delegation.md`.
</step_2>

<step_3>
Spawn all independent `cli-tool-expert` subagents in parallel. Do not use
`fork_context`.
</step_3>

<step_4>
Wait for every subagent result. If a subagent is slow, check status and request
current results once before deciding whether it is blocked.
</step_4>

<step_5>
Relay each subagent's complete user-facing result, then add the rollup table
defined in `SKILL.md`.
</step_5>
</process>

<success_criteria>
- Every named CLI tool has a subagent result.
- Every passing claim includes the test command and final result.
- Every auth blocker names the exact human-only action required.
</success_criteria>
