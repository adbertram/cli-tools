---
name: ata-blog-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute ata-blog operations using the `ata-blog` CLI tool.
  CLI for managing ATA Blog (adamtheautomator.com) -- Notion pages, static-site publishing and unpublishing, media uploads, categories, tags, and ad earnings.
  Triggers: ata-blog, ata blog, adamtheautomator, notion page publish, notion page unpublish, blog post, blog media, blog categories, blog tags, blog earnings
---

<objective>
Execute ata-blog operations using the `ata-blog` CLI. All ATA Blog interactions should use this CLI.
</objective>

<quick_start>
The `ata-blog` CLI follows this pattern:
```bash
ata-blog <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List Notion pages | `ata-blog notion-page list` |
| Publish Notion page to the static site | `ata-blog notion-page publish <page_id>` |
| Upload a media file (image, video, or caption file) to the static site media bucket (R2) | `ata-blog media upload <file_path>` |
| Preview taking a published post off the site | `ata-blog notion-page unpublish <page_id|url|slug> --dry-run` |
| List tags or categories from the static site | `ata-blog tags list` / `ata-blog categories list` |
| Check ad earnings for a post | `ata-blog earnings get <slug>` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `ata-blog` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Auth Status Probes">
`ata-blog auth status` can exit `2` while still emitting structured JSON that
reports the active profile with `"authenticated": false` and a message such as
`Not authenticated. Run 'ata-blog auth login' to configure.` When checking
whether auth exists, wrap the command and treat that unauthenticated JSON as an
expected diagnostic result only after validating both the `2` exit status and
`"authenticated": false`. Do not let the expected unauthenticated status surface
as an unhandled tool failure.
</principle>

<principle name="Static Site Is The Source">
Publishing, unpublishing, taxonomy, and earnings post identity all come from the
static site source at `ATABlogger/static-site`. `categories` and `tags` read and
write `src/data/terms.json`; publishing fails on a Notion Category or Tag name
that is not in that file. `notion-page unpublish` removes the post file, then
runs the same build, preview deployment, and production promotion as `publish`
before resetting the Notion page; it is destructive, so preview with `--dry-run`
and pass `--yes` only on an explicit request. `earnings get` takes a post slug.
</principle>

<principle name="Source Change Validation">
This service skill is not the lifecycle owner. For any ata-blog CLI source edit,
testing, or troubleshooting task, use the repo-owned `cli-tool` skill and its
`workflows/test-cli.md` procedure. The ata-blog source project lives at
`<cli-tools-root>/_personal/ata-blog`; do not run ambient `python -m pytest` from
that directory. Focused source tests must use the uv project environment, for
example:

```bash
uv run --project /Users/adam/Dropbox/GitRepos/cli-tools/_personal/ata-blog --with pytest python -m pytest /Users/adam/Dropbox/GitRepos/cli-tools/_personal/ata-blog/tests/test_notion_statuses.py
```
</principle>

<principle name="Command Groups">
- **auth** -- Authentication management (login, logout, status, refresh, test)
- **auth** -- Authentication commands and nested `auth profiles` management
- **cache** -- Response cache management
- **notion-page** -- Notion page management (list, get, create, publish, unpublish, update, search, statuses, comments, content, schema add-property)
- **media** -- Static site media (upload to Cloudflare R2)
- **categories** -- Static site categories from terms.json (list, get, create)
- **tags** -- Static site tags from terms.json (list, get, create)
- **earnings** -- Raptive ad earnings and revenue data (get, list)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
