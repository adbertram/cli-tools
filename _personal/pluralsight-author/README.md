# Pluralsight Author CLI

## DESCRIPTION

A browser-backed CLI for Pluralsight Author opportunities and a local-cache CLI for the Pluralsight Author Kit PNG library.
Use it to list, search, inspect, and apply for opportunities, or to query and download Author Kit icon assets without launching Chrome.

## Installation

```bash
cd /Users/adam/Dropbox/GitRepos/cli-tools/_personal/pluralsight-author
uv tool install --force -e .
```

## Authentication

```bash
pluralsight-author auth login
pluralsight-author auth status
pluralsight-author auth test
```

Opportunity commands use persisted browser sessions and an `opportunities` auth profile. Icon commands do not require browser authentication; `--profile` selects the archive namespace only.

```bash
pluralsight-author auth profiles create author-kit --auth-type author_kit
pluralsight-author auth profiles select author-kit
```

Opportunity commands validate the saved session before opening the browser page used for pagination and DOM extraction.
Icon commands read an Author Kit PNG archive from the selected profile data.
Run `icons import` to set that archive.
Refresh it from the current Inky Blue package linked on the Author Kit Downloads page.
The September 2026 package uses the supported eight-color PNG layout; icon downloads remain PNGs.
Use the Highlighter library only for courses explicitly using that brand.

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
pluralsight-author icons import /path/to/Pluralsight_Icon_library_2026-09.zip
pluralsight-author icons list
pluralsight-author icons list --filter "color:eq:Blue"
pluralsight-author icons list --filter "tag:contains:azure"
pluralsight-author icons list --properties "id,name,download_url"
pluralsight-author icons search "python"
pluralsight-author icons search "branch"
pluralsight-author icons get server-upload_Blue
pluralsight-author icons download server-upload_Blue --output ./server-upload_Blue.png
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

## Icon Output

`icons list`, `icons search`, and `icons get` records include:

- `id`: ZIP member basename without the `.png` extension
- `name`: title derived from the archive filename
- `category`: empty because the archive has no metadata file
- `color`: one of the eight supplied color folder names
- `tags`: lowercase words derived from the archive filename
- `download_url`: ZIP member reference such as `zip://Blue/server-upload_Blue.png`
- `thumbnail_url`
- `source_url`
- `file_type`

Get the current package from [Author Kit Downloads](https://authors.pluralsight.com/downloads/), download its ZIP, then run `pluralsight-author icons import <downloaded.zip> --profile author-kit`. Re-import after a library update before rebuilding slides.

`icons import` accepts the supplied PNG archive format.
The archive must contain matching PNG sets in `Blue`, `Green`, `InkyBlue`, `Orange`, `Pink`, `Purple`, `White`, and `Yellow`.
Icon commands fail with an import instruction when the archive is missing.
Icon filters support `name`, `category`, `color`, `tag`, and `tags`.
Use `--color pink` or `--color blue` for a color variant.

`icons search` matches its query as a single literal, case-insensitive substring across each icon's id, name, category, color, and tags. It does not tokenize the query, so a single keyword like `branch` or `lightbulb` matches many icons, but a multi-word phrase such as `isolate parallel work with branches` usually matches nothing. To find an icon for a multi-word concept, search individual keywords separately and combine the results, or search one salient term and narrow with `--filter`/`--color`. That substring behavior is specific to `icons search`. `icons list --filter` uses the shared filter module, where `like` is SQL LIKE and anchors the whole value, so `name:like:branch` matches only an icon named exactly `branch`. For substring matching on `icons list`, use `name:contains:branch` or `name:like:%branch%`.

`icons download` requires a `.png` output filename (or an existing directory) and writes the selected asset and returns the icon record plus:

- `output`
- `bytes`
- `content_type`

## Development

```bash
uv run --with pytest pytest
/Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name pluralsight-author --verbose
/Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills/cli-tool/scripts/validate-cli-tool.sh pluralsight-author
```

## Cache

```bash
pluralsight-author cache clear
```

`cache clear` removes response-cache files.
It preserves the imported Author Kit ZIP in the selected profile data.
