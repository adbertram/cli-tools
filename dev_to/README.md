# dev_to CLI

## DESCRIPTION

The `dev_to` CLI provides a command-line interface for the DEV Community API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## API contract

- Base URL: `https://dev.to/api`
- Auth header: `api-key: <key>`
- Accept header: `application/vnd.forem.api-v1+json`
- Article create endpoint: `POST /articles`
- Article visibility-removal endpoint: `PUT /articles/{id}/unpublish`

References:

- Forem API overview: `https://developers.forem.com/api/`
- Forem API v1 article docs: `https://developers.forem.com/api/v1`

## Installation

```bash
cd <cli-tools-root>/dev_to
uv tool install -e . --force --refresh
```

## Authentication

Create an API key from your DEV settings, then authenticate:

```bash
dev_to auth login
dev_to auth status
```

The CLI uses the standard `API_KEY` field managed by the shared auth flow.

## Commands

### `posts list`

List your authenticated DEV articles.

```bash
dev_to posts list
dev_to posts list --limit 10
dev_to posts list --filter "published:eq:true"
dev_to posts list --properties "id,title,url"
dev_to posts list --table
```

### `posts get`

Get one DEV article by ID.

```bash
dev_to posts get 123456
dev_to posts get 123456 --properties "id,title,body_markdown"
dev_to posts get 123456 --table
```

### `posts create`

Create a new DEV article.

```bash
dev_to posts create \
  --title "Hello DEV" \
  --body-file ./post.md \
  --published \
  --tags "python, cli" \
  --description "Short description" \
  --series "CLI Series" \
  --canonical-url "https://example.com/original-post" \
  --main-image "https://example.com/image.png"
```

`posts create` requires exactly one body source:

- `--body-markdown`
- `--body-file`

Supported article fields map directly to the official API payload:

- `title`
- `body_markdown`
- `published`
- `tags`
- `canonical_url`
- `description`
- `series`
- `main_image`

### `posts unpublish`

Remove public visibility from one DEV article.

```bash
dev_to posts unpublish 123456
dev_to posts unpublish 123456 --properties "id,published,url"
dev_to posts unpublish 123456 --table
```

`posts unpublish` uses the documented Forem unpublish operation, not a hard delete.
On DEV, unpublishing returns the article to draft status and removes it from
public view. If the authenticated article is already unpublished, the command
returns that current article record successfully without calling the unpublish
endpoint again. The official Forem article API does not document a hard-delete
endpoint for articles.

## Output

`posts list`, `posts get`, `posts create`, and `posts unpublish` return plain JSON by default.

The normalized article shape includes:

- `id`
- `type_of`
- `title`
- `description`
- `published`
- `slug`
- `path`
- `url`
- `canonical_url`
- `cover_image`
- `published_at`
- `published_timestamp`
- `created_at`
- `edited_at`
- `reading_time_minutes`
- `tag_list`
- `body_markdown`
- `user`
- `organization`

Use `--table` for human-readable output.

## Cache and profiles

The standard shared command groups are also available:

```bash
dev_to cache --help
dev_to auth profiles --help
```
