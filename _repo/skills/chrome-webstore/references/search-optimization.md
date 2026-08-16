# Chrome Web Store Search & Discoverability

Source: https://developer.chrome.com/docs/webstore/best-listing

## Named ranking signals

Google's best-listing doc names these signals that affect ranking:

| Signal | Lever you control |
|--------|-------------------|
| User ratings | Respond to reviews; fix reported bugs quickly |
| Downloads vs. uninstalls over time | Reduce uninstalls — polish onboarding, avoid surprise behavior |
| Design quality | Icon, promo tile, screenshots all reviewed for visual polish |
| Clear purpose that fills a real user need | Align title + summary + description to one narrow purpose |
| Onboarding / setup intuitiveness | First-run experience matters for retention |
| Ease of use | Reduce friction in the extension's core flow |

Not named (do not assume): featured badges, update frequency, locale count, support responsiveness, publisher age.

## Text-field optimization

**Title** — clear, descriptive, concise, unique. Short + catchy beats long + keyword-stuffed.

**Summary (132 chars)** — the snippet shown on homepage, category pages, and search results. Put the most important words first. This is the single highest-leverage search-visible field.

**Description** — lead with an overview paragraph, follow with a feature list. Use keywords that represent real features. Do NOT repeat keywords for ranking — Google explicitly warns this "can result in an item being suspended."

## Hard rules

- No keyword stuffing anywhere. Repetitive/irrelevant keywords can trigger suspension.
- No superlatives ("best extension ever").
- No competitor references in the summary.
- No misleading claims in promo tiles (including status claims).

## Localization leverage

- `chrome.i18n` + `_locales/<locale>/messages.json` localizes title, summary, description.
- Screenshots can be provided per locale.
- Promo tiles (small + marquee) are NOT locale-specific — one set serves all markets.
- A single extra locale with real translation (not machine) expands the search footprint to that market's query graph.

## Pre-launch discoverability checklist

- [ ] Title and summary both mention the core use case in plain terms
- [ ] Summary uses the full 132 characters (or close) — no wasted snippet space
- [ ] Description opens with a one-sentence value statement, then a feature list
- [ ] At least 3 screenshots (1280x800 full-bleed) demonstrating the core flow
- [ ] Icon is recognizable at 32px and works on dark + light backgrounds
- [ ] Small promo tile (440x280) communicates brand, not screenshot
- [ ] Category matches the single declared purpose
- [ ] Privacy tab reflects reality — mismatched claims hurt trust and trigger review