# Pluralsight Author CLI

A browser-backed CLI for the Pluralsight Author opportunities page at `https://app.pluralsight.com/author-home/opportunities/all`.

## Installation

```bash
cd /Users/adam/Dropbox/GitRepos/cli-tools/pluralsight-author
uv tool install --force -e .
```

## Authentication

```bash
pluralsight-author auth login
pluralsight-author auth status
pluralsight-author auth test
```

This tool uses a persisted browser session. Read-only commands validate the saved session with shared browser-authenticated HTTP before opening the headed browser page used for pagination and accessibility snapshots.

## Commands

```bash
pluralsight-author opportunities list
pluralsight-author opportunities list --table
pluralsight-author opportunities list --filter "category:eq:Security"
pluralsight-author opportunities list --properties "id,title,posted_date"
pluralsight-author opportunities get abuse-and-operational-attacks-for-ai-may-05-2026
pluralsight-author opportunities get abuse-and-operational-attacks-for-ai-may-05-2026 --properties "id,title,learning_objectives"
pluralsight-author opportunities apply product-strategy-steering-with-evidence-may-13-2026 --start_date 06/01/2026 --estimated_completion_weeks 8 --experience "Built and shipped security training for engineering teams."
pluralsight-author search query "security"
pluralsight-author search query "security" --table
pluralsight-author search query "security" --properties "id,title,category"
```

## Opportunity Output

`opportunities list` and `search query` records include:

- `id`: CLI-local slug derived from the visible title and posted date
- `title`
- `opportunity_type`
- `category`
- `posted_date`
- `is_new`
- `page_number`

`opportunities get` includes those fields plus:

- `learning_objectives`: ordered list of objective summaries from the opportunity detail page

`opportunities apply` returns:

- `id`
- `title`
- `detail_url`
- `submitted_param_keys`: sorted explicit option names accepted for submission
- `form_markers`: deterministic labels verified after the `Apply` click opens the application UI
- `post_submit_state`: currently `application_form_closed` when the verified form labels and `Send application` button are no longer visible after submission

`opportunities apply` requires all three explicit options:

- `start_date`
- `estimated_completion_weeks`
- `experience`

## Development

```bash
uv run --with pytest pytest
/Users/adam/Dropbox/.agents/skills/cli-tool/scripts/test-cli-tool.sh --cli-name pluralsight-author --verbose
/Users/adam/Dropbox/.agents/skills/cli-tool/scripts/validate-cli-tool.sh pluralsight-author
```

## Cache

```bash
pluralsight-author cache clear
```
