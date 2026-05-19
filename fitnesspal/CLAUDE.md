# Fitnesspal CLI - Claude Instructions

Always read the README.md file first when working with this CLI tool. It contains:

- Installation and setup instructions
- Available commands and usage examples
- Environment variable configuration
- API documentation references

## Auth Architecture

- `auth login` runs Playwright CDP, saves cookies to `.profiles/default/browser-data/session.json`
- `has_credentials()` and `test_connection()` must check `session.json`, NOT the system browser cookie jar
- The `myfitnesspal.Client()` library uses `browser_cookie3` by default -- always pass the saved cookiejar explicitly via `_load_cookiejar()`

## n8n Node

- Node package lives at `~/Dropbox/GitRepos/n8n-nodes/fitnesspal/`
- Source: `nodes/Fitnesspal/Fitnesspal.node.ts`
- Find source with: `Glob('**/*.node.ts')`, NOT `Glob('**/*.ts')` (avoids node_modules)
- The node has a bundled CLI copy at `cli/` -- changes to the main CLI require syncing to `cli/` and redeploying with `n8n nodes deploy fitnesspal`
- Deploy with: `n8n nodes deploy fitnesspal --skip-auth-check` (auth is handled by local login + redeploy, not server-side check)
