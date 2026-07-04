---
name: upwork-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Upwork operations using the `upwork` CLI tool.
  CLI interface for Upwork.
  Triggers: upwork, upwork cli
---

<objective>
Execute Upwork operations using the `upwork` CLI. All Upwork interactions should use this CLI.
</objective>

<quick_start>
The `upwork` CLI follows this pattern:
```bash
upwork <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Authenticate (all creds) | `upwork auth login` |
| Authenticate OAuth API only | `upwork auth login --credential-type oauth_authorization_code` |
| Check auth | `upwork auth status` |
| Search jobs (GraphQL API) | `upwork jobs list --filter "query:eq:python" --limit 20` |
| Filter jobs by skills, sort | `upwork jobs list --filter "skills:eq:python\|automation" --sort recency` |
| Get one job posting | `upwork jobs get <id-or-ciphertext>` |
| List supported profile fields | `upwork profile list --table` |
| Read profile attributes | Disabled: `upwork profile get` returns a Cloudflare/non-headed automation error |
| Show one field definition | `upwork profile get bio` |
| Preview a profile update | `upwork profile update --dry-run --set title="..."` |
| Apply a profile update | Disabled: `upwork profile update --yes ...` returns a Cloudflare/non-headed automation error |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `upwork` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `upwork --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Authentication management (login, logout, status, test, refresh) and nested `auth profiles`. Two credential types: `browser_session` (profile commands) and `oauth_authorization_code` (the `jobs` GraphQL API). Use `--credential-type` to scope login to one.
- **cache** -- Local response cache management
- **profile** -- Freelancer profile field metadata, profile reads, and guarded profile updates (browser session; live reads/writes disabled behind Cloudflare)
- **jobs** -- Search Upwork marketplace job postings via the official GraphQL API (`marketplaceJobPostingsSearch`). Requires the `oauth_authorization_code` credential. `jobs list` supports `--filter/-f` (query, skills, category, client_location, job_type, experience_level, fixed_min/max, hourly_min/max, posted_after), `--sort` (recency|relevance), `--limit/-l`, `--table/-t`, `--properties/-p`; `jobs get <id|ciphertext>` returns full detail.
</principle>

<principle name="Profile Safety">
- `upwork profile list` and `upwork profile fields list` are metadata commands and can run before login.
- `upwork profile get FIELD` returns field metadata without login; bare `upwork profile get` is disabled because Upwork's Cloudflare challenge blocks non-headed automation.
- `upwork profile update --dry-run` validates field names and values without login; applying changes with `--yes` is disabled for the same Cloudflare/non-headed automation reason.
- Editable common fields are `title`, `overview`, `hourly_rate`, `skills`, `categories`, `availability`, and `languages`; `name`, `location`, and `profile_url` are read-only.
</principle>

<principle name="Cloudflare And Browser Surfaces">
Upwork can return a Cloudflare "Just a moment" page to the CLI's non-interactive
browser profile. Treat that as a browser-surface blocker, not as permission to
open a local headed browser.

- The CLI uses the shared `cli_tools_shared.BrowserAutomation` CDP/browser-harness backend with a persistent profile, stealth launch flags, and `navigator.webdriver` masking.
- Do not tell agents to set `HEADLESS=false`, launch local Chrome/CDP, or use Computer Use when Adam says not to use a headed browser or not to interrupt him.
- Non-interrupting options are: reuse the authenticated saved browser profile, clear stale CLI cache and retry once, use an internal/API or authenticated in-page fetch path if the CLI already exposes one, connect only to an already-running approved CDP endpoint, or run the headed/CDP handoff on a remote/non-watched browser host.
- Real system Chrome over CDP is the known avoidance surface for managed Cloudflare challenges, but local real Chrome is a GUI action and requires explicit current approval.
- Never solve, click through, refresh around, or pay a service to solve a human-verification challenge. If the Cloudflare/Turnstile challenge persists on all allowed non-interrupting paths, report the blocker and the browser surface that needs approval.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`upwork --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
