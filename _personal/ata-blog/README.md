# ATA Blog CLI

## DESCRIPTION

The `ata-blog` CLI provides a unified command-line interface for managing the Adam The Automator blog post production pipeline.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows to manage Notion-backed post metadata, static-site publishing and unpublishing, media uploads, categories, tags, and ad earnings.

## Commands

```bash
ata-blog auth status
ata-blog auth login
ata-blog auth test --verbose
ata-blog auth profiles list
ata-blog cache clear
ata-blog notion-page list --table
ata-blog notion-page get PAGE_ID
ata-blog notion-page create --title "My Post" --excerpt "Summary" --category "Cloud"
ata-blog notion-page search "powershell"
ata-blog notion-page statuses
ata-blog notion-page update PAGE_ID --status "Draft"
ata-blog notion-page content get PAGE_ID
ata-blog notion-page content set PAGE_ID --file post.md
ata-blog notion-page content append PAGE_ID --file more.md
ata-blog notion-page comments list PAGE_ID
ata-blog notion-page comments get COMMENT_ID
ata-blog notion-page comments add PAGE_ID --body "Looks good"
ata-blog notion-page schema add-property DATABASE_ID --name "Reviewed" --type checkbox
ata-blog notion-page publish PAGE_ID --status draft      # build + preview deployment
ata-blog notion-page publish PAGE_ID --status publish    # build + deploy + promote to production
ata-blog notion-page unpublish PAGE_ID --dry-run
ata-blog notion-page unpublish my-post-slug --yes
ata-blog media upload image.png   # uploads to the static site's R2 media bucket
ata-blog categories list --table
ata-blog categories get 5401
ata-blog categories create "Platform Engineering"
ata-blog tags list --filter "name:eq:PowerShell"
ata-blog tags get 7
ata-blog tags create "Bicep"
ata-blog earnings list --limit 10
ata-blog earnings get my-post-slug --period last7d
```

### Publishing and unpublishing

`notion-page publish` stages the post into the static site source, builds the
site, uploads a Cloudflare Pages preview, and with `--status publish` promotes
that build to production. The result JSON carries `static_url`, `promoted`,
and `deployment_id`.

`notion-page unpublish` is the inverse. It accepts a Notion page ID, a post
URL, or a slug, removes the post file from the static site source, runs the
same build, preview deployment, and production promotion, then resets the
Notion page (status plus Published URL, X Post URL, LinkedIn Post URL, Publish
Date, and Promoted). A failure before the Notion reset rolls production back
to the prior deployment and restores the post file. The removed file is kept
at the `backup_path` in the result. It prompts for confirmation unless `--yes`
is passed; `--dry-run` previews without mutating.

### Categories and tags

Both groups read and write `static-site/src/data/terms.json`, the static
site's taxonomy record. Each term is `{id, name, slug, count}`. `create`
appends a term with the next free id and a slug derived from the name, and
rejects a name that already exists (case-insensitive). Publishing fails on a
Notion Category or Tag name that is not in that file.

### Earnings

`earnings list|get` read Raptive ad data through the `raptive` CLI. Post
identity comes from the static site corpus: `get` takes a post slug,
`--post-title` matches corpus titles, `--exclude-sponsored` drops posts
carrying the Sponsored tag, and `publish_date` / `earnings_per_day` come from
each post's corpus publish date.

### Frozen scheduling windows

Supply both UTC-aware bounds to keep automatic scheduling inside one frozen
interval. The lower bound is inclusive; the upper bound is exclusive:

```bash
ata-blog notion-page publish PAGE_ID --auto-schedule --schedule-after 2026-09-08T20:00:00Z --schedule-before 2026-09-15T20:00:00Z --featured-image featured.png
```

The locked scheduler keeps weekday, daily-capacity, four-hour spacing, and
reservation rules, reading occupied slots from the static publisher's own
records. If no slot fits, it raises an error before reserving or publishing
outside the interval. Both bounds also validate an explicit `--date` and
static transaction replays.

### Authentication

Authentication is owned by the delegated Notion CLI:

```bash
notion auth login
```

## Testing

Run focused source tests through the uv project so pytest, the local package, and
the editable `cli-tools-shared` path dependency resolve from the tool environment.
Do not run ambient `python -m pytest` or a bare/global `pytest` from this source
directory.

```bash
uv run --project /Users/adam/Dropbox/GitRepos/cli-tools/_personal/ata-blog --with pytest python -m pytest /Users/adam/Dropbox/GitRepos/cli-tools/_personal/ata-blog/tests/test_notion_statuses.py
```

For all ata-blog source tests, use the same project-qualified shape:

```bash
uv run --project /Users/adam/Dropbox/GitRepos/cli-tools/_personal/ata-blog --with pytest python -m pytest /Users/adam/Dropbox/GitRepos/cli-tools/_personal/ata-blog/tests
```

From inside this directory, the equivalent focused form is:

```bash
uv run --project . --with pytest python -m pytest tests/test_terms.py
```
