# Workflow: Create a Chrome Web Store listing

**Preload:** `references/listing-spec.yaml`, `references/search-optimization.md`.
All limits/dimensions come from the YAML — never recite from memory.

## 0. Confirm the single purpose

Ask the user one sentence: **"In one sentence, what does this extension do?"**
That sentence becomes the spine of every field. If it names two purposes, stop and ask them to narrow it.

## 1. Gather inputs (ask once, as a batch)

- Extension name / brand
- Single-purpose sentence (from step 0)
- Target category (see category picker in dashboard — single select)
- Default locale; any additional locales to support
- Privacy facts:
  - Does the extension collect user data? If yes, types.
  - Does it execute remote code? (M V3 → should be "No")
  - Privacy policy URL (must exist before submission)
- Distribution: public / unlisted / private? Paid? Country list?
- Support URL and marketing website (optional but recommended)
- Path to the signed `.zip` package (≤ 2 GB)

## 2. Produce assets (spec-exact, before writing copy)

Create a folder `cws-assets/` with the following, matching `listing-spec.yaml` dimensions exactly:

| File | Dimensions | Format | Required |
|------|------------|--------|----------|
| `icon-128.png` | 128×128 canvas, 96×96 artwork, 16 px transparent padding | PNG | Yes |
| `promo-small-440x280.png` | 440×280 | PNG | Yes |
| `promo-marquee-1400x560.png` | 1400×560 | PNG | No (required for featured placement) |
| `screenshot-01.png` … `screenshot-05.png` | 1280×800 (or 640×400) | PNG, full bleed, square corners | ≥ 1, ≤ 5 |

Validate each file's pixel dimensions (e.g. `sips -g pixelWidth -g pixelHeight file.png`) before moving on. A wrong-size asset is the most common rejection.

Localized screenshots: if the user declared additional locales, request one screenshot set per locale.

## 3. Draft the text fields

Draft in order. After each draft, run it against `references/search-optimization.md` — reject anything that keyword-stuffs, uses superlatives, or references competitors.

1. **Title** — clear, descriptive, concise, unique. One line.
2. **Summary** — one sentence, ≤ 132 chars, plain text, leading with the core use case. This is the search-visible snippet; measure it before submitting (`echo -n "$summary" | wc -c`).
3. **Description** — opening overview paragraph, then a bulleted feature list. Every feature ties back to the single-purpose sentence.

Present all three to the user for approval before touching the dashboard.

## 4. Fill the Store Listing tab

At https://chrome.google.com/webstore/devconsole, open the extension → **Store Listing** tab:

- [ ] Title
- [ ] Summary (verify counter shows ≤ 132)
- [ ] Description
- [ ] Category (single)
- [ ] Language (default locale)
- [ ] Upload icon (128×128)
- [ ] Upload small promo tile (440×280)
- [ ] Upload marquee tile (1400×560) — optional
- [ ] Upload 1–5 screenshots (1280×800 preferred)
- [ ] Official support URL (if provided)
- [ ] Official website URL (if provided)
- [ ] Additional locales — add strings + locale-specific screenshots

## 5. Fill the Privacy tab

- [ ] Single-purpose description (paste the spine sentence + 1–2 clarifiers)
- [ ] Permission justification — one entry per permission in `manifest.json`, each ≤ 1000 chars, explaining why the extension cannot deliver the single purpose without it
- [ ] Host permissions justification — one entry per host pattern
- [ ] Remote code: select "No, I am not using remote code" (MV3) unless the user has explicitly justified remote execution
- [ ] Data use disclosures — tick exactly the data types the extension handles; do not over-declare
- [ ] Certification checkboxes (three of them — only check if truthful)
- [ ] Privacy policy URL — must resolve and describe collect/use/disclose

## 6. Fill the Distribution tab

- [ ] Visibility: public / unlisted / private
- [ ] Country availability: all or subset
- [ ] Paid designation + pricing (if applicable)
- [ ] Mature content flag (if applicable)

## 7. (Optional) Test Instructions tab

If the extension requires login or complex setup, paste credentials + step-by-step reviewer instructions. Skipping this without reason can add review time.

## 8. Pre-submission validation

Run the review-listing workflow OR walk this checklist:

- [ ] Every asset file matches its spec dimensions exactly
- [ ] Summary is ≤ 132 characters
- [ ] All permissions in manifest.json have a written justification
- [ ] Privacy tab data-use checkboxes align with what the code actually does
- [ ] Privacy policy URL returns 200 and mentions the declared data types
- [ ] Single-purpose sentence, title, summary, and description all reinforce the same purpose
- [ ] No superlatives, no competitor references, no keyword stuffing
- [ ] `.zip` package ≤ 2 GB
- [ ] Account has < 20 published extensions (themes excluded)

## 9. Submit

Click **Submit for Review**. Offer the defer option (up to 30 days) if the user wants to align with a launch date. Record the submission timestamp — review duration varies by item.

## 10. Post-submission

- Enable "published item" and "staged item" notifications on the Account page
- Monitor the dashboard for pending / approved / rejected status on each promo image and the package itself
- If rejected, read the notice, map each cited issue to a field in `listing-spec.yaml`, fix, resubmit