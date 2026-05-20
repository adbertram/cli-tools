# N8nCliToolNodeConverter CLI - Claude Instructions

Always read the README.md file first when working with this CLI tool. It contains:

- Installation and setup instructions
- Available commands and usage examples
- Environment variable configuration
- API documentation references

## Quick Reference

### CLI Invocation
Always activate the venv first: `source .venv/bin/activate && n8n <command>`
Never use `python -m n8n_cli` (no __main__.py).

### Key Workflow IDs
- Susan: U7cK5XlQqmgG9CWlrB6wM

### n8n Node Type Naming
Community node types use camelCase after the package prefix. Example:
- Package: `n8n-nodes-n8n-manager`
- Node type: `n8n-nodes-n8n-manager.n8NManager` (note lowercase 'n8n', uppercase 'M')
- Always verify with: `n8n nodes list --type community`

### Node Package Naming
- `nodes create` takes CLI tool name (directory name under cli-tools/), NOT package name
  - Example: `n8n nodes create n8n --name n8n-manager --force` (source=n8n, package=n8n-manager)
- `nodes deploy` takes short package name: `n8n nodes deploy n8n-manager` (NOT `n8n-nodes-n8n-manager`)
- Generated packages output to the configured converter output directory.

### Server-Side Paths (adam-server)
- Community nodes installed at: `~/.n8n/nodes/node_modules/<npm-package-name>/`
- Custom node sources are passed explicitly to deploy commands.
- n8n startup takes 30-60s after restart; use `n8n server restart` CLI command if available (has built-in wait)

### n8n Execution Data
- `n8n executions get` requires `--include-data` flag to get run data (without it, `data` is null)
- Always inspect data shape with `jq 'keys'` before writing complex jq queries

### AI Agent Tool Nodes
- Empty `$fromAI()` descriptions cause tools to receive empty inputs (especially with Gemini)
- Every tool node connected to an AI agent MUST have descriptive `$fromAI()` params
- If a node has no configurable parameters, add at least one optional param to avoid empty schema issues

### Common Gotchas
- `n8n nodes list` (no --type) returns a flat JSON array of locally generated packages, not a keyed object
- `n8n workflows update` requires `--file` flag (not positional)
- `n8n workflows node connect` supports `--type ai_tool` for AI agent tool connections
- `n8n workflows node update` can patch node params in-place (deep merge)
- `nodes create --force` regenerates the entire package, overwriting manual edits. Fix the generator source first, then regenerate.
- `--output-format stream-json` requires `--verbose` and `--include-partial-messages` flags to get `content_block_delta` events (auto-added by the Claude Code node)
- n8n Chat Trigger defaults to non-streaming (`lastNode` mode) unless `responseMode: "streaming"` is explicitly set in options
- Community node deploys need `--legacy-peer-deps` to avoid duplicate `@langchain/core` installations that break prototype identity checks
- Streaming only works via webhook/production URL, not the editor's manual test chat panel
