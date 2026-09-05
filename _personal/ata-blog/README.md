# ATA Blog CLI

## DESCRIPTION

The `ata-blog` CLI provides a unified command-line interface for managing the Adam The Automator blog post production pipeline.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows to manage Notion-backed post metadata, WordPress publishing, Raptive ad settings, and Rank Math schema markup.

## Commands

```bash
ata-blog auth status
ata-blog auth test --verbose
ata-blog auth profiles list
ata-blog notion-page list --table
ata-blog notion-page get PAGE_ID
ata-blog notion-page update PAGE_ID --status "Draft"
ata-blog wordpress-post list --table
ata-blog wordpress-post get POST_ID
ata-blog wordpress-post create --status draft --title "Title"
ata-blog wordpress-post update POST_ID --content-file post.html
ata-blog wordpress-post schedule POST_ID --auto-schedule
ata-blog wordpress-page list --table
ata-blog wordpress-menu list --table
ata-blog wordpress-menu get MENU_ID --table
ata-blog wordpress-menu items --menu MENU_ID --table
ata-blog wordpress-menu add-page PAGE_ID --menu MENU_ID
ata-blog media upload image.png
ata-blog categories list --table
ata-blog tags list --table
ata-blog wordpress-admin plugins list --table
ata-blog wordpress-admin themes list --table
ata-blog wordpress-admin themes file-push active-theme ./front-page.php front-page.php --remote-root /srv/www/site --host wp-host --dry-run
ata-blog cache clear
ata-blog raptive status POST_ID
ata-blog raptive status PAGE_ID --type page
ata-blog schema list --limit 10
ata-blog earnings list --limit 10
ata-blog shoutouts list POST_ID
ata-blog shoutouts site get --table
ata-blog shoutouts site set --text 'Audit AD with <a href="https://example.com">Example</a>.'
ata-blog shoutouts site set --logo 27000 --link https://example.com/product
ata-blog shoutouts site set --no-display --no-cache-clear
```

### Body shoutouts vs the site shoutout

`ata-blog shoutouts list|get|add|remove` manage `wp:quote` blocks inside one
post body. `ata-blog shoutouts site get|set` manage the sponsor placement that
the theme prints above every post body from the ACF options record
`site_ad_settings`. That placement is site-wide: one record serves every post.

`site set` changes only the options you supply, reads the record back, then
flushes the WP Engine page cache. Pass `--no-cache-clear` to skip the flush.
Get the `--logo` attachment ID from `ata-blog media upload`.

The `site` commands reach WordPress through wp-cli over the WP Engine SSH
connection because acf-to-rest-api 3.3.4 cannot write ACF options on ACF Pro 6.8.
Set these keys in `~/.local/share/cli-tools/ata-blog/.env`:

```
WPENGINE_SSH_HOST=<environment>.ssh.wpengine.net
WPENGINE_SSH_USER=<environment>
WPENGINE_SSH_IDENTITY_FILE=~/.ssh/<key>
WPENGINE_SITE_PATH=/sites/<environment>
```

Authentication is owned by the delegated CLIs:

```bash
wordpress auth login
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
uv run --project . --with pytest python -m pytest tests/test_raptive.py
```
