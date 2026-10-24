# LinkedIn CLI

## DESCRIPTION

The `linkedin` CLI lets you create and manage LinkedIn personal and page posts.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## What It Supports

- Create, update, and delete member posts through `/rest/posts`
- Create, update, and delete organization or showcase-page posts through `/rest/posts`
- List, get, and search member posts through `/rest/posts`
- List, get, and search organization or showcase-page posts through `/rest/posts`
- Client-side wildcard search on normalized post output
- Create video posts (MP4, optional SRT captions and thumbnail) through the Videos API and `/rest/posts`
- Resolve a company page vanity name to its organization URN

## Scope Requirements

LinkedIn enforces different scopes by author type and operation:

- `w_member_social`: member `create`, `update`, `delete`
- `r_member_social`: member `list`, `get`, `search`
- `w_organization_social`: page `create`, `update`, `delete`
- `r_organization_social`: page `list`, `get`, `search`

If a required scope is missing, the CLI fails through the API permission path
with the exact scope LinkedIn denied.

## Author Resolution

The CLI does not invent author URNs.

Member commands resolve the author in this order:

1. `--person`
2. `LINKEDIN_PERSON_URN`
3. `/v2/me`
4. `/v2/userinfo`

If your token cannot call `/v2/me` or `/v2/userinfo`, set
`LINKEDIN_PERSON_URN` or pass `--person`.

Page commands resolve the author in this order:

1. `--page`
2. `LINKEDIN_PAGE_URN`

## Installation

```bash
cd <cli-tools-root>/linkedin
uv tool install -e . --force --refresh
```

## Configuration

```env
CLIENT_ID=your-linkedin-client-id
CLIENT_SECRET=your-linkedin-client-secret
REDIRECT_URI=http://localhost:8000/callback
LINKEDIN_SCOPES=w_member_social
LINKEDIN_VERSION=202604
LINKEDIN_PAGE_URN=urn:li:organization:123456
LINKEDIN_PERSON_URN=urn:li:person:123456
BASE_URL=https://api.linkedin.com/rest
```

`LINKEDIN_VERSION=202604` is the current live default. On May 18, 2026, live
validation against `https://api.linkedin.com/rest/posts` accepted `202604` and
rejected `202605` with HTTP 426.

## Authentication

```bash
linkedin auth login
linkedin auth login --force
linkedin auth status
linkedin auth test
linkedin auth readiness --table
linkedin auth logout
linkedin auth profiles list
linkedin auth profiles create affiliate-magic-page
linkedin auth login --profile affiliate-magic-page --force
```

`linkedin auth status` and `linkedin auth test` validate the saved OAuth token
through LinkedIn token introspection. `linkedin auth readiness` reports whether
the current token and scopes are sufficient for each post command group.

## Commands

### User Posts

```bash
# Create a member post with an explicit person URN
linkedin user posts create "Hello from the LinkedIn CLI" --person urn:li:person:8675309

# Create a member post using LINKEDIN_PERSON_URN or authenticated-member identity lookup
linkedin user posts create "Hello from the LinkedIn CLI"

# List posts for a member author
linkedin user posts list --limit 20
linkedin user posts list --person urn:li:person:8675309 --limit 20
linkedin user posts list --profile default --limit 20

# Filter and table output
linkedin user posts list --filter "visibility:eq:PUBLIC" --table
linkedin user posts list --properties "id,commentary,published_at"

# Create a member video post (see "Video Posts" below)
linkedin user posts create "Watch this" --video clip.mp4 --video-title "Clip" --captions clip.srt

# Get a post
linkedin user posts get urn:li:share:1234567890123456789
linkedin user posts get urn:li:share:1234567890123456789 --person urn:li:person:8675309

# Update post commentary
linkedin user posts update urn:li:share:1234567890123456789 "Updated commentary"
linkedin user posts update urn:li:share:1234567890123456789 "Updated commentary" --person urn:li:person:8675309

# Delete a post
linkedin user posts delete urn:li:share:1234567890123456789
linkedin user posts delete urn:li:share:1234567890123456789 --person urn:li:person:8675309

# Search output client-side
linkedin user posts search "launch*" --limit 25
linkedin user posts search "launch*" --person urn:li:person:8675309 --limit 25
```

### Page Posts

```bash
# Create a post for a specific organization page URN
linkedin page posts create "Organization update" --page urn:li:organization:123456

# Create a page video post (see "Video Posts" below)
linkedin page posts create "Watch this" --page urn:li:organization:123456 \
  --video clip.mp4 --video-title "Clip" --captions clip.srt

# Resolve a company page vanity name (linkedin.com/company/<vanity>) to its URN
linkedin page lookup --vanity atalearning

# Create a post using LINKEDIN_PAGE_URN from the active profile
linkedin page posts create "Organization update"
linkedin page posts create "Organization update" --profile affiliate-magic-page

# List posts for an organization or showcase page
linkedin page posts list --page urn:li:organization:123456 --limit 20
linkedin page posts list
linkedin page posts list --profile affiliate-magic-page --limit 20

# Filter and table output
linkedin page posts list --page urn:li:organization:123456 --filter "visibility:eq:PUBLIC" --table
linkedin page posts list --page urn:li:organization:123456 --properties "id,commentary,published_at"

# Get a post
linkedin page posts get urn:li:share:1234567890123456789 --page urn:li:organization:123456

# Update post commentary
linkedin page posts update urn:li:share:1234567890123456789 "Updated commentary" --page urn:li:organization:123456

# Delete a post
linkedin page posts delete urn:li:share:1234567890123456789 --page urn:li:organization:123456

# Search output client-side
linkedin page posts search "launch*" --page urn:li:organization:123456 --limit 25
```

### Video Posts

`user posts create` and `page posts create` accept these options. Without
`--video` the command creates the same text-only post as before.

| Option | Meaning |
|---|---|
| `--video PATH` | MP4 to upload. Triggers the video flow. |
| `--video-title TEXT` | Media title on the post. |
| `--captions PATH` | SRT file uploaded as English closed captions. |
| `--thumbnail PATH` | Custom thumbnail image. |
| `--video-timeout SECONDS` | How long to wait for processing (default 600). |

The command runs the Videos API sequence: `initializeUpload` (owner is the post
author URN), `PUT` each part collecting ETags, upload captions/thumbnail,
`finalizeUpload`, then polls `GET /rest/videos/{urn}` every 2 seconds until `AVAILABLE`. It exits
non-zero on `PROCESSING_FAILED` or when the timeout elapses, before any post
is created. Only then does it create the post with `content.media`.

`--video-title`, `--captions`, and `--thumbnail` require `--video`.
Output includes `id` (post URN), `url`
(`https://www.linkedin.com/feed/update/<urn>/`), `video` (video URN), and
`captions_attached`.

### Cache

```bash
linkedin cache clear
```

## Request Behavior

- Every HTTP request has a finite timeout (60 seconds; 300 seconds for video part,
  thumbnail, and caption uploads).
- Only idempotent requests are retried (GET and PUT, up to 3 retries with
  backoff on 429/5xx and connection errors). POST requests, including
  `POST /rest/posts`, are sent once and fail with the error, so a transient
  failure never publishes a duplicate post.

## Output Notes

- `create` returns the new post URN plus the requested author and content values.
  Video posts also return `url`, `video`, and `captions_attached`.
- `page lookup` returns `urn`, `id`, `vanity_name`, `name`, and `website`. It calls
  the `/v2/organizations?q=vanityName` finder, which works with
  `w_organization_social`/`r_organization_social`; the `/rest/organizations`
  vanityName finder needs `rw_organization_admin`.
- `update` and `delete` return the post URN plus a success flag.
- `list`, `get`, and `search` return normalized post records with:
  `id`, `author`, `commentary`, `visibility`, `lifecycle_state`,
  `feed_distribution`, `content_type`, `is_reshare_disabled_by_author`,
  `created_at`, `published_at`, and `last_modified_at`.

## Scope Examples

Use the default member-write scope:

```env
LINKEDIN_SCOPES=w_member_social
```

If your app is approved for member reads:

```env
LINKEDIN_SCOPES=w_member_social r_member_social
```

If your app uses OIDC for authenticated-member lookup:

```env
LINKEDIN_SCOPES=w_member_social openid profile
```

If your app is approved for organization writes and reads:

```env
LINKEDIN_SCOPES=w_member_social openid profile w_organization_social r_organization_social
```
