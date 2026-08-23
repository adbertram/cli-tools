# Jira CLI

## DESCRIPTION

The `jira` CLI provides a command-line interface for Jira API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Installation

```bash
cd <cli-tools-root>/jira
uv tool install -e . --force --refresh
jira --version
```

## Authentication

The CLI now exposes explicit Jira auth profile types. Create a profile first, then log into that profile.

### 1. Classic site basic auth

Uses your Atlassian account email plus a classic API token against `https://<site>.atlassian.net/rest/api/3/...`.

```bash
jira auth profiles create basic-site --auth-type site_basic
jira auth login --profile basic-site
```

### 2. OAuth 2.0 3LO

Uses an Atlassian Developer Console OAuth 2.0 authorization-code app and calls Jira through `https://api.atlassian.com/ex/jira/{cloudId}/...`.

```bash
jira auth profiles create jira-3lo \
  --auth-type oauth_authorization_code \
  --auth-param BASE_URL=https://example.atlassian.net
jira auth login --profile jira-3lo
```

During login, the CLI prompts for:

- `CLIENT_ID`: Atlassian OAuth app client ID
- `CLIENT_SECRET`: Atlassian OAuth app client secret
- `REDIRECT_URI`: redirect URI configured in the app, for example `http://localhost`

The profile `BASE_URL` binds login to that Jira Cloud site before the CLI resolves and stores the matching `cloudId`.

### 3. Scoped Atlassian API token

Uses Atlassian account email plus a scoped API token, but calls Jira through the platform gateway `https://api.atlassian.com/ex/jira/{cloudId}/...`.

```bash
jira auth profiles create jira-scoped \
  --auth-type scoped_api_token \
  --auth-param CLOUD_ID=1324a887-45db-1bf4-1e99-ef0ff456d421
jira auth login --profile jira-scoped
```

### Auth management

```bash
jira auth status
jira auth test
jira auth refresh --profile jira-3lo
jira auth logout --profile basic-site
jira auth profiles list --table
jira auth profiles select basic-site
```

Secrets are stored through the CLI-tools secret-manager profile flow. Depending on the auth type, the CLI stores:

- `site_basic`: `USERNAME`, `PASSWORD`
- `oauth_authorization_code`: `CLIENT_ID`, `CLIENT_SECRET`, `ACCESS_TOKEN`, `REFRESH_TOKEN`, `REDIRECT_URI`, `CLOUD_ID`
- `scoped_api_token`: `USERNAME`, `PASSWORD`, `CLOUD_ID`

### Direct Python probes

If you inspect Jira config directly in Python, use the installed CLI
interpreter and pass the profile explicitly:

```bash
launcher="$(command -v jira)"
interpreter="$(head -1 "$launcher" | sed 's/^#!//')"
"$interpreter" -c "from jira_cli.config import get_config; print(get_config(profile='devolutions').env_file_path)"
```

Do not rely on `JIRA_PROFILE=...` for ad-hoc probes. Jira profile resolution
for direct imports comes from `get_config(profile='...')` /
`Config(profile='...')`, not an ambient shell environment variable.

## Commands

### Projects

```bash
# List visible projects
jira projects list --profile basic-site --limit 25 --table

# Search projects by key or name
jira projects list --profile basic-site --query Eng --table

# Filter and restrict project fields
jira projects list --profile basic-site --filter "key:eq:ENG" --properties "key,name,lead"

# Get one project
jira projects get ENG --profile basic-site
```

### Tickets

```bash
# List recent tickets in a project
jira tickets list --profile basic-site --filter "project:ENG" --limit 25

# List with JQL and table output
jira tickets list --profile basic-site --jql "project = ENG ORDER BY updated DESC" --table

# Filter tickets with shared filter syntax
jira tickets list --profile basic-site --filter "status:eq:To Do" --filter "project:ENG"

# Restrict output fields
jira tickets list --profile basic-site --filter "project:ENG" --properties "key,summary,status,assignee"

# Get one ticket
jira tickets get ENG-1 --profile basic-site

# Create a ticket
jira tickets create --profile basic-site --project ENG --issue-type Bug --summary "Broken workflow" --description "Details here"

# Update a ticket
jira tickets update ENG-1 --profile basic-site --summary "Updated summary"

# Delete a ticket
jira tickets delete ENG-1 --profile basic-site

# Delete a ticket and its subtasks
jira tickets delete ENG-1 --profile basic-site --delete-subtasks

# Add a comment
jira tickets comment ENG-1 --profile basic-site --body "Looking into this now"

# List available transitions
jira tickets transitions ENG-1 --profile basic-site --table

# Apply a transition
jira tickets transition ENG-1 --profile basic-site --transition-id 31 --comment "Resolved"
```

### Cache

```bash
jira cache clear
jira --no-cache tickets list --filter "project:ENG" --limit 10
```

## Output

JSON is the default output. Add `--table` / `-t` for table output where supported.

Default ticket rows include:

| Field | Description |
|-------|-------------|
| `id` | Jira issue id |
| `key` | Jira issue key |
| `summary` | Ticket summary |
| `status` | Current status name |
| `issue_type` | Issue type name |
| `project` | Project key |
| `assignee` | Assignee display name or `Unassigned` |
| `reporter` | Reporter display name |
| `priority` | Priority name |
| `created` | Jira creation timestamp |
| `updated` | Jira update timestamp |
| `labels` | Ticket labels |

Default project rows include:

| Field | Description |
|-------|-------------|
| `id` | Jira project id |
| `key` | Jira project key |
| `name` | Project name |
| `project_type` | Jira project type key when available |
| `style` | Jira project style |
| `simplified` | Whether the project uses a simplified workflow |
| `category` | Project category name |
| `lead` | Project lead display name |
| `total_issue_count` | Insight issue count when Jira returns it |
| `last_issue_update_time` | Latest issue update timestamp from project insight |

## Notes

- `jira tickets list` uses `/rest/api/3/search/jql`, the current enhanced JQL search endpoint.
- `jira projects list` uses `/rest/api/3/project/search`, Jira's paginated project discovery endpoint.
- `jira projects get` uses `/rest/api/3/project/{projectIdOrKey}`.
- The Devolutions Jira tenant rejects unbounded enhanced JQL searches. Smoke tests should include a search restriction such as `project = ENG`, `status = "To Do"`, or `assignee = currentUser()` before `ORDER BY`.
- `jira tickets create`, `update`, `delete`, `comment`, and `transition` use Jira Cloud API v3 issue endpoints.
- `site_basic` calls the Jira site root directly; `oauth_authorization_code` and `scoped_api_token` call `https://api.atlassian.com/ex/jira/{cloudId}`.
- Descriptions and comments are sent as Atlassian Document Format plain-text paragraphs.
- Forge and Connect app authentication are not implemented in this standalone CLI because those flows depend on Atlassian app frameworks and app-managed auth, not user-managed CLI credential profiles.
