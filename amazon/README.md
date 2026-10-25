# Amazon CLI

## DESCRIPTION

The `amazon` CLI provides a command-line interface for Amazon (browser automation).

Use it when you need repeatable access to amazon workflows that are only available through a signed-in website.

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

Login and headless reads use the installed Chrome user agent so Amazon can
recognize the saved session across browser restarts. `BROWSER_USER_AGENT`
can explicitly override that identity.

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

An ISO `--date YYYY-MM-DD` without `--query` scans all order-history pages
for that year and returns complete matching order cards, including order id,
order date, total, and item text. Amount and date are independent evidence
signals: inspect `matched_amount` before treating a date match as a charge match.
Amount evidence requires a currency marker (such as `$25`) or cents (`25.00`);
bare dates, quantities, and order numbers do not count as monetary matches.

The saved session can encounter Amazon's one-button **Continue shopping**
page during repeated use. The CLI follows that verified continuation control
only when its form has no image, frame, or visible input. A real CAPTCHA
remains a human verification gate.

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
