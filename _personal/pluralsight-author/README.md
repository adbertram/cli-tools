# Pluralsight Author CLI

## DESCRIPTION

A browser-backed CLI for Pluralsight Author opportunities, whole slide-deck templates, and the Pluralsight Author Kit PNG library.
Use it to inspect opportunities, identify and download the latest authors-portal presentation template, or query and download Author Kit icon assets.

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

Opportunity commands use persisted browser sessions and an `opportunities` auth profile. Slide-deck download commands use the authenticated `author_kit` profile. Icon commands do not require browser authentication; `--profile` selects the archive namespace only.

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
pluralsight-author slide-deck list
pluralsight-author slide-deck get latest
pluralsight-author slide-deck download latest --output ./Pluralsight_PowerPoint_Template.zip
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

## Slide-deck templates

`slide-deck list` returns every whole PowerPoint template download found on the
authenticated Author Kit Downloads page.

`slide-deck get latest` reads the authenticated Author Kit Downloads page and returns
the newest whole PowerPoint template link:

- `version`: normalized `YYYY.MM.<letter>` value
- `filename`
- `url`
- `title`

`slide-deck download latest --output <file-or-directory>` downloads that template.
Pluralsight currently publishes a ZIP containing the `.potx`; direct `.potx` and
`.pptx` links remain supported. The command validates the PowerPoint package,
returns the same metadata plus `output`, `bytes`, and `content_type`, and uses the
authenticated browser request context so protected download links do not become
403 responses. Use `--profile author-kit` when that profile is not already active.

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

## Module submission

`pluralsight-author modules inspect 21958 --module-order 1 --profile default` reads
current portal module, clip and asset IDs without exposing signed download links.
`pluralsight-author modules submit --manifest /absolute/manifest.json --profile default`
uploads the module deck, uploads or replaces edited clips in manifest order, sets
canonical titles through the Author Dashboard's authoritative content service,
verifies the remote bytes and displayed names, and submits the module for review.
Authentication uses the existing CLI browser profile headlessly.

Manifest JSON requires `course_title`, `module_order` (one-based), `module_title`,
`deck_path` (existing PPTX), and ordered `clips` with `record_id`, `title`, and `path`
(existing `.edited.mp4`). Optional numeric `course_id` skips title discovery. Without
it, exactly one in-progress Author Home card must match the course title. Course and
module titles are confirmed against the portal API before any upload. The module
holds one slide deck. While the module accepts uploads (`in_progress`,
`updates_required`, `available_for_updates`), an existing deck under another file
name (for example `m4_approved.pptx` when the manifest names `m4_print.pptx`) is
replaced in place with the manifest's deck, even when the bytes match, so the portal
deck always carries the manifest's file name; no second deck is added. A module under
review is read-only: a deck file name mismatch there fails before any write.

The result contains `ok`, `course_id`, `course_title`, `module_id`, `module_guid`,
`module_title`, `module_order`, `status`, `deck`, `clips`, `display_titles`, and `already_submitted`.
`modules submit --manifest ... --plan` writes nothing and reports the deck as
`unchanged`, `replace`, or `upload`, and each clip as `unchanged`, `new_version`, or
`new_clip`, with the clip's current portal `version`. Run it before every
resubmission. A plan's `deck_path` may name a deck its submitter builds at
submission time and that does not exist yet; such a deck is reported as `replace`
or `upload`, never `unchanged`. A real submission requires the deck on disk.

When Pluralsight asks for edits (module status `updates_required` or
`available_for_updates`), an edited clip is added as a new version of its existing
portal clip, the same call as the portal's "Replace clip" button
(`PUT /content/api/v1/clip/{guid}/video`), and the clip's version number goes up by
one. No clip is ever added in these states: a manifest clip with no matching portal
clip fails before any write, and `--plan` reports `ok: false` for it. The receipt
lists each clip's `action`, `version_before`, and `version`, and the module is
submitted with `updates-submit-move-to-qa`.

Retries inspect existing uploads and compare bytes before creating or replacing
anything. A module already under review is read-only: exact matches return its
receipt, while changed bytes, names, or order fail explicitly. Modified modules in
an update state replace the existing clip instead of adding duplicates. The API
and selectors were discovered from the production Author Dashboard on November 5,
2026. No public author-upload API is used; JSON and multipart requests follow the
portal's internal API. Source footage is never accepted.

Before submission, the complete ordered clip set is renamed through the same
`PUT /content/api/v1/clip/{guid}` operation used by the portal's Save control,
with the exact `{title}` payload. Legacy numeric-ID clip writes are not used:
they can temporarily change the legacy projection without changing the title
stored by the content service. Module reads use the authoritative content-service
module endpoint. Verification rereads each clip by GUID and reloads the target
module's actual table, checking the complete ordered clip IDs and displayed
names before submitting. After submission, both checks run again and the receipt
is rebuilt from fresh reads. A post-submission mismatch fails explicitly; it
never returns cached pre-submission names or changes a locked module.
