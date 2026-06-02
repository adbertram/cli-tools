---
name: wordpress-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute wordpress operations using the `wordpress` CLI tool.
  CLI interface for WordPress API -- manage posts, pages, media, categories, and tags.
  Triggers: wordpress, wordpress cli, wordpress posts, wordpress pages, wordpress page, update wordpress page, edit wordpress page, wordpress media, create wordpress post, upload wordpress image, wordpress categories, wordpress tags, publish blog post, wordpress blog, wordpress site
---

<objective>
Execute wordpress operations using the `wordpress` CLI. All wordpress interactions should use this CLI.
</objective>

<quick_start>
The `wordpress` CLI follows this pattern:
```bash
wordpress <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List posts | `wordpress posts list --table` |
| Get a post | `wordpress posts get POST_ID` |
| Create from Markdown | `wordpress posts create --from-markdown file.md` |
| Create from DOCX | `wordpress posts create --from-docx file.docx` |
| Publish a draft | `wordpress posts update POST_ID --status publish` |
| List pages | `wordpress pages list --table` |
| Get a page (raw HTML) | `wordpress pages get PAGE_ID --raw` |
| Find page by slug | `wordpress pages list --filter slug:eq:my-slug` |
| Update page content | `wordpress pages update PAGE_ID --content-file page.html` |
| Upload media | `wordpress media upload image.png` |
| List categories | `wordpress categories list --table` |
| List tags | `wordpress tags list --table` |
| List plugins | `wordpress admin plugins list --table` |
| Upgrade plugin | `wordpress admin plugins upgrade PLUGIN` |
| Save WordPress.com OAuth credentials | `wordpress org token save-credential --client-id ... --client-secret ... --username ... --password ... --site ...` |
| Refresh WordPress.com token | `wordpress org token` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `wordpress` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Authentication commands and nested `auth profiles` management
- **auth** — Authentication: login, logout, status, refresh, test
- **posts** — Full post lifecycle: list, get, create (from DOCX/Markdown), update, delete
- **pages** — Page lifecycle: list, get, create (from DOCX/Markdown), update (supports --content-file), delete. Pages support `parent`, `menu_order`, `template` (no tags/categories/format).
- **media** — Media library: list, get, upload, delete
- **categories** — Category management: list, get, create, update, delete
- **tags** — Tag management: list, get, create, update, delete
- **admin** — WordPress admin maintenance, including plugin list/get/activate/deactivate/delete/install/upgrade
- **org** — WordPress.com OAuth token commands used by Jetpack plugin updates
</principle>
</essential_principles>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
