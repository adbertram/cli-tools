---
name: jira-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute Jira ticket operations using the `jira` CLI tool.
  CLI interface for Jira Cloud tickets and projects: list, get, create, update, comment, and transition tickets, plus project discovery.
  Triggers: jira, jira cli, jira tickets, jira ticket, jira projects, list jira tickets, list jira projects, create jira ticket, update jira ticket, transition jira ticket
---

<objective>
Execute Jira Cloud ticket and project operations using the `jira` CLI. All Jira ticket and Jira project interactions should use this CLI.
</objective>

<quick_start>
The `jira` CLI follows this pattern:
```bash
jira <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Show CLI version | `jira --version` |
| List projects | `jira projects list --profile basic-site --query Eng --table` |
| Get a project | `jira projects get ENG --profile basic-site` |
| List tickets | `jira tickets list --profile basic-site --filter "project:ENG" --limit 25` |
| Search with JQL | `jira tickets list --profile basic-site --jql "project = ENG ORDER BY updated DESC"` |
| Get a ticket | `jira tickets get ENG-1 --profile basic-site` |
| Create a ticket | `jira tickets create --profile basic-site --project ENG --summary "Title"` |
| Update a ticket | `jira tickets update ENG-1 --profile basic-site --summary "New title"` |
| Add a comment | `jira tickets comment ENG-1 --profile basic-site --body "Comment text"` |
| List transitions | `jira tickets transitions ENG-1 --profile basic-site` |
| Transition a ticket | `jira tickets transition ENG-1 --profile basic-site --transition-id 31` |
| Check auth | `jira auth status` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `jira` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Bounded Enhanced JQL">
Jira Cloud enhanced JQL can reject unbounded searches in the Devolutions tenant with `HTTP 400: Unbounded JQL queries are not allowed here. Please add a search restriction to your query.`

For smoke tests and exploratory list commands, include at least one real restriction such as `project = ENG`, `status = "To Do"`, or `assignee = currentUser()` before `ORDER BY`. Do not smoke-test the Devolutions profile with only `ORDER BY updated DESC`.
</principle>

<principle name="Authentication">
Jira auth is profile-typed, not one ambiguous default:

- `site_basic` uses Atlassian account email + classic API token against `https://<site>.atlassian.net/rest/api/3/...`
- `oauth_authorization_code` uses an Atlassian Developer Console 3LO app and calls Jira through `https://api.atlassian.com/ex/jira/{cloudId}/...`
- `scoped_api_token` uses Atlassian account email + scoped API token and also calls Jira through `https://api.atlassian.com/ex/jira/{cloudId}/...`

Create the profile first, then log into it:

```bash
jira auth profiles create basic-site --auth-type site_basic
jira auth login --profile basic-site
```

For OAuth 2.0 3LO profiles, bind the target Jira Cloud site during profile
creation so login can choose the correct resource when the OAuth grant includes
multiple Jira sites:

```bash
jira auth profiles create devolutions \
  --auth-type oauth_authorization_code \
  --auth-param BASE_URL=https://devolutions.atlassian.net
jira auth login --profile devolutions
```

For ad-hoc Python probes of Jira config, use the installed Jira CLI interpreter
and pass the profile explicitly:

```bash
launcher="$(command -v jira)"
interpreter="$(head -1 "$launcher" | sed 's/^#!//')"
"$interpreter" -c "from jira_cli.config import get_config; print(get_config(profile='devolutions').env_file_path)"
```

Do not expect `JIRA_PROFILE=...` to affect direct imports. Jira's ad-hoc Python
config resolution uses `get_config(profile='...')` / `Config(profile='...')`,
while normal CLI commands use `--profile` and command-specific runtime
resolution.
</principle>

<principle name="Command Groups">
- **auth** -- Authentication management.
- **cache** -- Response cache management.
- **projects** -- Project discovery and detail lookup.
- **tickets** -- Ticket list, get, create, update, comment, transitions, and transition.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error.
- Output is displayed in requested format.
- Correct command and flags used, verified against `usage.json`.
</success_criteria>
