# pluralsight CLI

Search the **public** Pluralsight catalog (courses, paths, labs, certificates) by keyword and
return JSON, matching standard cli-tools conventions. No account or login required: the
catalog search API is the same public site-search endpoint pluralsight.com/browse uses,
authenticated with a static site key Pluralsight publishes in its own pages.

## DESCRIPTION

`pluralsight` provides keyword search, newest-item listing, single-product lookup, and query
suggestions over the public Pluralsight catalog via its Cludo site-search API. Use it when
you need scriptable, JSON-first access to Pluralsight course metadata (titles, authors,
categories, ratings, publish dates, durations, skill levels) for agents, automation, or
terminal workflows; output is JSON by default or a formatted table with `--table`, and
authentication is not required.

## Command tree

```
pluralsight
├── search <query>    Keyword search (courses/paths/labs/certificates)
├── list              Newest catalog entries across the library
├── get <prodId>      One catalog entry by product id
├── suggestions <q>   Query suggestions for a partial phrase
└── cache             Manage response cache (shared cli-tools cache commands)
```

## Record shape

Every result record contains:

| Field           | Type        | Notes                                            |
|-----------------|-------------|--------------------------------------------------|
| `title`         | string      | Course/path/lab/certificate title                |
| `url`           | string      | pluralsight.com URL                              |
| `category`      | string      | `course`, `skill` (= path), `labs`, `certificate`|
| `subjects`      | string[]    | Subject areas (e.g. `Software Development`)      |
| `catalog`       | string/null | Catalog name (e.g. `Core Tech`, `AI`)            |
| `roles`         | string[]    | Role tags (e.g. `AI Practitioner`)               |
| `tags`          | string[]    | subjects + roles (index has no separate tag set) |
| `authors`       | string[]    | Author names                                     |
| `rating`        | number/null | Average rating                                   |
| `ratingCount`   | int/null    | Number of ratings                                |
| `publishedDate` | date/null   | `YYYY-MM-DD`                                     |
| `updatedDate`   | date/null   | `YYYY-MM-DD`                                     |
| `duration`      | string/null | e.g. `1h 46m`                                    |
| `skillLevel`    | string/null | Beginner / Intermediate / Advanced               |
| `prodId`        | string/null | Product id used by `get`                         |
| `numberOfLabs`  | int/null    | Attached hands-on labs                           |
| `numberOfCourses`| int/null   | Courses in a path                                |
| `retired`       | bool        | Whether the item is retired                      |

## Commands

### search

```
pluralsight search "agentic ai"
pluralsight search "docker fundamentals" --limit 10 --category course --table
pluralsight search "kubernetes" -c course -c certificate --sort newest
pluralsight search "agentic ai" --full          # adds total count + facets wrapper
pluralsight search "agentic ai" --filter "category:eq:course" -p title,url,rating
pluralsight search "agentic ai" --page 2 --limit 20
```

Options:

- `--limit/-l` (default 20): results per page; applied server-side (`perPage`)
- `--page/-P` (default 1): page number
- `--category/-c` (repeatable): `course`, `path`, `labs`, `certificate`, `all`.
  Omitting it uses the same defaults as pluralsight.com/browse (courses, labs,
  certificates, paths/skills). `path` and `skill` both map to the index token
  `skill`; `all` searches every indexed type (blogs, resources, etc.).
- `--sort`: `relevance` (default) or `newest`
- `--filter/-f` (repeatable): client-side output filters, `field:op:value`
- `--table/-t`: table output (default columns: title, category, Skill Level, duration, rating)
- `--properties/-p`: comma-separated fields to include
- `--full`: wrap results with `{query, page, perPage, total, results[], facets{}}`

Default JSON output is the array of records.

### list

Newest entries first (server-side sort by publish date).

```
pluralsight list --limit 5
pluralsight list --category labs --table
pluralsight list --full
```

Supports the same options as `search` except query/sort.

### get

```
pluralsight get docker-developers-docker-foundations
pluralsight get generative-ai-foundations-agentic-ai --properties authors,duration,publishedDate
```

Looks up one entry by product id (the slug at the end of a pluralsight.com course URL).
Exits 1 with an informational message when nothing matches.

### suggestions

```
pluralsight suggestions "agentic"
```

Returns the engine's suggestion strings for a partial phrase as a JSON array.

## Configuration

Non-secret configuration lives in `~/.local/share/cli-tools/pluralsight/.env`:

```
BASE_URL=https://api-us1.cludo.com/api/v3/10000847/10001278
CACHE_ENABLED=true
```

There are no credentials. The `Authorization: SiteKey ...` header value is a static public
site key embedded in Pluralsight's own web pages and is hardcoded in the client.
