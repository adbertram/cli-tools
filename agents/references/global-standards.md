# Global Agent Standards

This is the single source of truth for shared custom-agent and subagent behavior in the cli-tools repo. Individual agent files and task skills may point here, but they must not copy these global standards into role-specific instructions. Keep agent files focused on domain purpose, task workflow, output schema, and role-specific constraints.

## Scope

These standards apply to user-level and project-level Codex custom agents and to skills that spawn or orchestrate subagents.

Do not place project-specific domain knowledge here unless that knowledge is explicitly a shared standard for a family of agents. If a standard applies only to one agent, keep it in that agent. If a standard applies to one project-specific family, place it in this file under a clearly scoped section and point that project family at this reference.

## Delegation

- Use Codex `spawn_agent` for subagent delegation.
- Do not carry forward Claude Task-tool wording into Codex instructions.
- Do not use `fork_context` when spawning typed subagents. Pass all required context in the subagent prompt instead.
- Subagent prompts must be self-contained and include task scope, file paths, constraints, expected output, and verification requirements.
- A parent agent should do setup work before spawning a subagent when that setup is required for the subagent to operate independently.
- Subagents are black boxes: they receive an input task and return a result. They must not depend on hidden parent-session phases or unspoken conversation state.
- Skills that orchestrate domain phases may specify which agent to spawn and what prompt to pass, but they must not redefine these global delegation standards.

### Parallel Delegation

- Identify independent tasks that can run in parallel when planning or orchestrating work.
- A task is parallelizable only when it does not read another pending task's output, does not modify a file another pending task modifies, and execution order does not affect correctness.
- Good candidates include independent file edits, separate test files for different components, separate documentation updates, and isolated refactors.
- Do not parallelize steps that share a write target, depend on ordered state, require a previous generated artifact, or need one agent's output before another can start.
- For each parallel task, assign a clear owner or agent type, file scope, expected output, and verification command.
- Spawn independent subagents in the same parent turn when the work is authorized and materially advances the task.

## Agent File Boundaries

- Put trigger text and routing examples in `description`.
- Put role-specific behavior, workflow, output format, and validation requirements in `developer_instructions`.
- Keep global delegation, evidence, work-summary, and learning policy in this reference, not in each agent file.
- Move reusable domain knowledge into a skill or reference file and preload or point to it; do not turn an agent TOML into a handbook.
- Hook behavior belongs in hook configuration (`hooks.json` or inline `[hooks]` in an active config layer), not in custom-agent prompt text or ad hoc agent metadata. Current Codex CLI 0.130.0 testing confirms repo/user `SessionStart` hooks fire for spawned subagent threads, but hook payloads do not expose the invoked agent role and inline hooks in `agents.<name>.config_file` did not run as verified agent-scoped hooks. For deterministic behavior tied to one specific custom agent invocation, use explicit parent orchestration around `spawn_agent` and `wait_agent`.
- Use the lightest sandbox that satisfies the task: read-only for analysis, workspace-write for implementation, and danger-full-access only when the environment requires it.

## Evidence And Verification

- Do not ship findings, recommendations, proposals, or fix directions that are based on guesses.
- Every claim in a final report must be backed by evidence gathered in the current task: file reads, grep results, command output, logs, measurements, test results, reproduced failures, or direct source documentation.
- Read every file referenced by path.
- Search for every symbol, dependency, call site, test name, or pattern that supports a claim.
- Trace relevant execution paths end to end instead of stopping at the first hop.
- Verify framework, SDK, and library assumptions against the installed version or current primary documentation.
- Run commands whose output would change the conclusion.
- If a claim depends on a condition being true, verify that condition before reporting it.
- When a condition cannot be verified because it depends on inaccessible production state, timing, credentials, or an external system, label that part `UNVERIFIED` and explain the blocker.
- Hedging words such as "likely", "probably", "may", "might", "seems to", and "appears to" are not acceptable in final findings. Replace them with evidence or mark the item `UNVERIFIED`.

## Work Summary

Every custom agent final response must include the outcome details needed by the caller:

- What was accomplished.
- Artifacts created or changed, with paths when applicable.
- Verification performed, including commands or direct checks.
- Issues encountered, or `No issues encountered`.
- Unresolved blockers with exact next action when the agent could not complete a required step.

Role-specific agents may define additional summary fields, tables, JSON paths, or artifact formats, but they must not duplicate this generic work-summary policy.

## Continuous Learning

When an agent encounters missing instructions, incorrect procedures, better workflows, or new reusable edge cases:

1. Complete the assigned task first unless continuing would cause incorrect or destructive work.
2. Fix the source problem when the agent has authority and access.
3. Verify the source fix.
4. Add durable learning only after the fix is verified, and only to the owning instruction source.
5. Update skills for reusable workflow or domain knowledge.
6. Update agent files only for role-specific behavior, routing, or handoff expectations.
7. Preserve Codex/Claude parity when a counterpart artifact exists.
8. Mention source fixes and instruction updates in the work summary.

Do not add bug diaries, workaround notes, or duplicate warnings as a substitute for source fixes.

## Build Product Agent Standards

This section applies only to CourseCraft/build-product agents and other agents explicitly described as build-product educational content agents.

### Response Format

- Start directly with the complete build product artifact.
- Do not add chatty preamble, process narration, or "based on the information..." setup text before the artifact.
- Return the complete, verbatim build product content that would be saved to the database or file.
- Do not provide summaries, excerpts, condensed versions, ellipses, or "key highlights" in place of the full build product.
- After the artifact, include only essential metadata such as fields updated, status changes, artifact path, or database record updated.
- When answering a question instead of creating a build product, answer directly and concisely.

### Hidden Expert Hook Formula

Educational hooks should validate the learner's existing expertise and bridge that recognition into the lesson:

1. Validate an existing mindset: "You already [think/act/recognize] like someone who [desired skill/outcome]."
2. Prove it with specific micro-behaviors that begin with "You [verb]..."
3. Bridge to the lesson: "Here's [how to express that/what that looks like/how to use that] in [specific tool/context]."

Use relatable professional behaviors, avoid talking down to learners, and keep hooks within the word limits defined by the owning course or build-product workflow.

### Build Product Workspaces

- Every build-product agent uses an isolated workspace for temporary files, scripts, and artifacts.
- Project-level workspace: `agent_workspaces/[agent-name]/`.
- User-level workspace: the runtime-provided user agent workspace for `[agent-name]`.
- Create the workspace before file operations.
- Use the exact custom-agent name as the workspace directory.
- Save review artifacts in the workspace using `{build-product-type}_{YYYYMMDD_HHMMSS}.md`.
- Include artifact frontmatter with agent name, timestamp, build product type, target course element, and status.

### Database Updates

- Build-product agents that create database-backed deliverables update the database after creating and saving the artifact unless a higher-priority project instruction explicitly requires human approval first.
- Use the project-approved CLI or script for database updates.
- Report the database record updated and artifact path in the final response.
- Do not stop after only creating local content when the task requires a database-backed build product.

### Student Perspective Review

Agents that create educational content must perform the configured student-perspective review before finalizing. Use the owning project skill or workflow for the concrete review steps, coverage, and exemptions.

### Record Identification

- Verify database records by the canonical name or ID field before updating.
- Do not assume the first search result is correct.
- If multiple records match and no exact canonical match exists, ask for clarification.
