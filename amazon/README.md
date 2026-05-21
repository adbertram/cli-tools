# Amazon CLI

Read-only Amazon order evidence lookup using a persistent browser session from
`cli-tools-shared`.

## Installation

```bash
cd <cli-tools-root>/amazon
pip install -e .
```

## Authentication

```bash
amazon auth login
amazon auth status
amazon auth test
amazon auth logout
```

## Profiles

```bash
amazon auth profiles list
amazon auth profiles get default
amazon auth profiles create work
amazon auth profiles select work
amazon auth profiles delete work
```

## Orders

```bash
amazon orders list
amazon orders list --limit 25 --table
amazon orders list --filter "text:ilike:%keyboard%" --properties id,text

amazon orders get line-1
amazon orders get line-1 --table

amazon orders match --amount 33.15
amazon orders match --date 2026-05-16
amazon orders match --query "USB cable" --limit 5 --table
amazon orders match --amount 33.15 --query "Amazon" --properties id,text,score
```

## Cache

```bash
amazon cache clear
amazon cache stats
amazon --no-cache orders match --amount 33.15
```

## Output Contract

`orders list` and `orders match` return JSON arrays of evidence records.

| Field | Description |
|-------|-------------|
| `id` | Stable line id such as `line-1` |
| `line` | Visible text line number |
| `text` | Visible page text |
| `url` | Page URL inspected |
| `title` | Page title inspected |
| `score` | Match score for `orders match` |
| `matched_amount` | Whether the requested amount was found |
| `matched_terms` | Date or query terms found |

## Requirements

- Python 3.11+
- `cli-tools-shared`
- `browser-harness` through `cli-tools-shared`
