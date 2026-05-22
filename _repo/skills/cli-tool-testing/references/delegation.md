# Delegation Reference

## Subagent Owner

Use `cli-tool-expert` for every CLI tool test run. The parent session owns
orchestration, parallelism, status checks, and final rollup. The subagent owns
testing, fixing, authentication work, and verification for one CLI tool.

## Required Prompt Fields

Every subagent prompt must include:

- `/Users/adam/Dropbox/.agents/skills/agent-expert/references/global-standards.md`
- `/Users/adam/Dropbox/GitRepos/cli-tools`
- the exact CLI tool name
- the requested scope or `none`
- the command `/Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name <tool>`
- the authentication policy
- the expected final output fields

## Authentication Policy

If browser authentication is required, use Computer Use to complete the visible
browser flow and create the required authenticated browser state. Use available
credential and message tools, including LastPass, Gmail, and iMessage CLI, for
codes or account context available without Adam's live intervention.

Skip only a test that requires a human action outside the computer, such as
approving MFA on another device. Report that as blocked and name the exact next
human action.
