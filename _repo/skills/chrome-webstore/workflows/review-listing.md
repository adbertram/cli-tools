# Workflow: Review / audit an existing Chrome Web Store listing

**Preload:** `references/listing-spec.yaml`, `references/search-optimization.md`.

Audit an in-progress or submitted listing against every requirement in the spec. Produce a report with PASS / FAIL / FIX-NEEDED for each field.

## 1. Collect the listing artifacts

Ask the user for:
- Listing URL (if published) or screenshots of each dashboard tab
- Paths to the uploaded assets (icon, promo tiles, screenshots)
- `manifest.json` of the current package
- Privacy policy URL

## 2. Check each field against the spec

Walk `listing-spec.yaml` top-to-bottom. For each field, record the observed value, the spec, and the verdict:

| Field | Observed | Spec | Verdict |

Required checks:

- [ ] **Title** — short, descriptive, no keyword stuffing
- [ ] **Summary** — exact character count ≤ 132; no superlatives; no competitor mentions
- [ ] **Description** — overview paragraph present; feature list present; no repeated keywords
- [ ] **Category** — single, matches the declared single purpose
- [ ] **Icon** — 128×128 PNG, 96×96 artwork with 16 px transparent padding; readable at 32px; works on light and dark
- [ ] **Small promo tile** — 440×280 exactly; brand-first, not a screenshot
- [ ] **Marquee promo tile** — 1400×560 exactly (if present)
- [ ] **Screenshots** — 1–5 files; each 1280×800 or 640×400 exactly; full bleed, square corners; demonstrates actual UX
- [ ] **Single purpose** — narrow, one sentence; matches title/summary/description
- [ ] **Permissions justification** — one entry for every permission in manifest.json; no over-declared permissions
- [ ] **Host permissions justification** — one entry per host pattern (if declared)
- [ ] **Remote code** — "No" for MV3 unless justified
- [ ] **Data use disclosures** — checkboxes match actual data handling in code
- [ ] **Privacy policy URL** — resolves; describes collect/use/disclose; aligns with disclosures
- [ ] **Distribution visibility** — matches user intent (public / unlisted / private)
- [ ] **Country availability** — correct
- [ ] **Package size** — ≤ 2 GB
- [ ] **Account published count** — ≤ 20 (themes excluded)

## 3. Check search/discoverability

From `references/search-optimization.md`:

- [ ] Summary uses most of the 132 chars, leads with core use case
- [ ] Title/summary/description reinforce one narrow purpose
- [ ] No keyword stuffing anywhere
- [ ] No superlatives, no competitor references
- [ ] ≥ 3 screenshots demonstrating the core flow
- [ ] Icon works at small sizes on both backgrounds
- [ ] Localization in place for every declared locale

## 4. Check alignment between surfaces

This is where most rejections happen:

- [ ] Permissions declared in manifest.json match those justified in Privacy tab
- [ ] Data collected in the code matches the data-use checkboxes
- [ ] Privacy policy URL's disclosures match the Privacy tab's disclosures
- [ ] Single-purpose sentence describes what the extension *actually* does
- [ ] Screenshots show real UI, not mockups

## 5. Deliver the report

Produce a table of findings with severity:

- **BLOCKER** — will cause rejection (missing required field, wrong asset dimensions, mismatched disclosures)
- **HIGH** — hurts ranking or trust (keyword stuffing, low-quality promo tile, missing privacy policy sections)
- **LOW** — polish (summary length not maxed out, missing optional marquee tile)

For each finding, cite the exact clause in `listing-spec.yaml` or `search-optimization.md` and propose the fix.