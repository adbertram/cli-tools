---
name: "chrome-webstore"
description: "MANDATORY: Use this skill for ALL Chrome Web Store listing creation and review operations. DO NOT draft CWS listing fields, write extension store descriptions, or prepare listing assets without loading this skill first. Triggers: \"chrome web store listing\", \"publish chrome extension\", \"webstore listing\", \"create extension listing\", \"chrome web store\", \"cws listing\", \"submit extension to chrome web store\", \"extension store assets\", \"promo tile\", \"marquee tile\"."
---

<objective>
Create or review Chrome Web Store listing content, assets, and compliance fields using the local listing spec as the source of truth for limits, required fields, and dashboard sections.
</objective>

<quick_start>
1. Identify whether the task is listing creation, listing review, field-spec lookup, or another Chrome Web Store request.
2. Read `references/listing-spec.yaml` before quoting any field limit, required flag, or asset dimension.
3. Route creation work to `workflows/create-listing.md` and review work to `workflows/review-listing.md`.
4. Use `references/search-optimization.md` only when copy or discoverability guidance is needed.
5. Use `references/official-docs.md` when the user challenges or asks to verify a spec.
</quick_start>

<essential_principles>
## How This Skill Works

### Principle 1: Data-driven field specs
All character limits, asset dimensions, formats, and required/optional flags live in `references/listing-spec.yaml`. Read the YAML — never recite limits from memory. When Google updates the requirements, only the YAML changes.

### Principle 2: Two listing surfaces, four dashboard tabs
A CWS submission has two deliverable groups: (1) listing **content** (text + images on the public store page) and (2) **compliance** metadata (privacy, distribution, test instructions). The dashboard splits these into four tabs — Store Listing, Privacy, Distribution, Test Instructions — all must be complete before "Submit for Review" is enabled.

### Principle 3: Assets first, copy second
Image assets have hard pixel dimensions and a review pass of their own. Produce assets to spec before writing descriptions so copy can reference what's shown in screenshots.

### Principle 4: Single purpose is the spine
Every field (title, summary, description, permissions justification, category) must reinforce one narrow purpose. Google rejects or delays extensions whose listing suggests multiple purposes.
</essential_principles>

<intake>
What would you like to do?

1. Create a new Chrome Web Store listing (full workflow — text + assets + compliance)
2. Review / audit an existing listing against requirements
3. Look up a specific field spec (character limit, image dimension, etc.)
4. Something else

**Wait for response before proceeding.**
</intake>

<routing>
| Response | Workflow / Action |
|----------|-------------------|
| 1, "create", "new listing", "publish" | workflows/create-listing.md |
| 2, "review", "audit", "check listing" | workflows/review-listing.md |
| 3, "what is", "limit", "dimension", "spec" | Read `references/listing-spec.yaml` and answer directly |
| 4, other | Clarify, then select |

**After reading the workflow, follow it exactly.**
</routing>

<reference_index>
**Specs:** `references/listing-spec.yaml` — field-by-field source of truth (limits, dimensions, required flags, guidance)
**Search & discoverability:** `references/search-optimization.md` — ranking signals, keyword/copy rules, localization leverage, pre-launch checklist
**Source docs:** `references/official-docs.md` — URLs to authoritative Google docs (fetch when user questions a spec)
</reference_index>

<workflows_index>
| Workflow | Purpose |
|----------|---------|
| create-listing.md | End-to-end: assets → Store Listing tab → Privacy tab → Distribution tab → submit |
| review-listing.md | Audit an in-progress or draft listing against every requirement in listing-spec.yaml |
</workflows_index>

<success_criteria>
A successful invocation:
- Reads `references/listing-spec.yaml` before quoting any limit or dimension
- Routes to the correct workflow based on user intent
- Produces listing content that satisfies every "required" field in the spec
- Flags every "recommended" field the user has not addressed
- Never guesses a character limit or pixel dimension from memory
</success_criteria>
