# Recommend a Monarch Rule

When the reviewer is about to propose a category change for a single transaction, also evaluate whether that change should become a Monarch rule so the same merchant is auto-categorized in the future. This workflow defines the decision and the rule shape.

## Core decision

**Recommend a rule whenever you believe the proposed category should apply to this merchant ALWAYS — not just to this transaction.** Default to recommending. Suppress the recommendation only when one of the suppressors below applies.

This is intentional: Adam wants the reviewer to surface the rule recommendation early and let him decline what shouldn't become a rule, rather than wait for N occurrences. False recommendations cost a "no"; missed recommendations cost forever-manual categorization.

## Suppressors — DO NOT recommend a rule when ANY of these is true

1. **Noisy merchant string.** The merchant contains per-transaction identifiers that won't repeat: order numbers, store IDs, dates, locations encoded into the string, random suffixes. Examples: `AMZN Mktp US*A8M93H02`, `SQ *MERCHANT 12345`, `PAYPAL *INST XFER 8492`. A rule on this string will match exactly one future transaction. → Recommend only if you can also recommend a stable matcher (see "Use original statement" below).

2. **Merchant has multiple legitimate categories at different amounts.** A charge from this merchant means category A at one amount range and category B at another. Examples: Apple — IAPs vs. subscriptions vs. hardware; Amazon — household vs. electronics vs. groceries (depending on which Whole Foods integration); Costco — gas vs. groceries. → Either recommend a rule with an `--amount between:` criterion (see "Amount criterion" below), or skip the recommendation entirely if you can't draw a clean boundary.

3. **Adam previously declined a rule for this merchant.** Check `/Users/adam/Dropbox/GitRepos/Agents/skills/monarch-cli/rules.md` (Rule-Recommendation Rules section) before proposing. If the merchant is listed there as declined, skip — do not re-surface.

4. **An existing Monarch rule already covers this merchant.** Run `monarch rules list --filter 'setCategoryAction.id:eq:<category-id>'` or scan rules whose `merchantCriteria` contains the merchant token before proposing. If a rule already fires for this merchant + category combo, the category mismatch on this transaction is a Monarch sync lag or a one-off override — flag it as a one-off, don't propose a duplicate rule.

5. **Refund / reversal.** Refunds usually appear as positive amounts (or negative, depending on account type) with a merchant string that mirrors the original purchase. Do not recommend a rule from a refund — the rule should be derived from the original positive-spend transaction. Flag refunds as "Apply once" only.

6. **Internal transfer.** Never recommend rules for transfers between Adam's own accounts. These should never reach the rule-recommendation stage; they are out-of-scope per the reviewer's transfer-handling logic.

7. **Single-occurrence with no shape match.** This is NOT a recurrence-threshold check (Adam chose "recommend on first occurrence"). It IS a sanity check: if the merchant has appeared exactly once AND the merchant string is unique-looking (no recognizable brand, looks like a one-off purchase from an obscure vendor), the rule will fire for one transaction and never again. → Recommend `Apply once` instead of `Apply + create rule`.

## Amount criterion — when to add `--amount`

Use AI judgment. Heuristics:

- **DON'T add an amount criterion** when the merchant means the same category at any amount. Subscriptions, streaming services, single-line restaurants, single-purpose retailers. Default to no amount filter.
- **DO add `--amount between:X:Y`** when the merchant has multiple legitimate categories AND you can draw a clean boundary. Example: Apple charges between $0.99 and $19.99 → "Subscriptions / Apps & Software"; Apple charges $99+ → leave for one-off classification. The rule then only fires for the subscription range.
- **DO add `--amount gt:X` or `--amount lt:X`** for known thresholds (e.g., "Costco purchases over $100 are almost always groceries; under $100 are usually gas/snacks").
- **DON'T split into two rules from a single observation.** If past data shows a bimodal distribution (e.g., $10 and $100 clusters), recommend ONE rule for the cluster matching the current transaction and surface the other cluster in the row's evidence so Adam can decide whether to add a second rule manually.

## Account scope

**Never scope to a single account.** Recommended rules omit `--account-id`. Merchant-based rules should fire on every account that ever sees this merchant. This matches Adam's preference and how subscription billing typically works.

Exception: if the merchant string is identical across a business card and a personal card AND the categories differ (rare), surface the conflict as a Needs Review row instead of recommending a rule. Do not silently pick one.

## Merchant matcher: `contains` vs. `equals` vs. `--use-original-statement`

Choose ONE based on the merchant string:

| Situation | Recommendation |
|---|---|
| Cleaned merchant is a clean brand (`Spotify`, `Netflix`, `Whole Foods Market`) | `--merchant equals:"Spotify"` |
| Cleaned merchant has a stable prefix with trailing noise (`Amazon Web Services US East`) | `--merchant contains:"Amazon Web Services"` |
| Cleaned merchant is generic (`SQ *`, `PAYPAL *`, `TST*`, `DD *DOORDASH`) and the real identity is in the bank statement | `--merchant contains:"<stable-substring-from-original-statement>" --use-original-statement` |
| Multiple distinct vendors collapse to the same cleaned name | `--merchant contains:"<distinctive-substring>" --use-original-statement` |

Default to `equals` when possible; fall back to `contains` when the cleaned merchant has trailing junk; only reach for `--use-original-statement` when the cleaned merchant is genuinely ambiguous.

## Retroactive apply

**Default: do NOT pass `--apply-to-existing`.** The reviewer is already processing this transaction; the rule only needs to cover future occurrences. Recommend `--apply-to-existing` only when Adam asks to retroactively fix historical miscategorizations of this merchant.

If you do recommend retroactive apply, surface the count of historical matches in the recommendation evidence so Adam knows the blast radius before approving.

## Rule shape template

When the reviewer surfaces a rule recommendation in its action table, include both the human-readable shape and the exact CLI command. Format:

```
RULE RECOMMENDATION:
  Match:    merchant equals "<merchant>"  [+ amount <op> <value>]  [+ use-original-statement]
  Action:   set category → "<category-name>"  (id: <category-id>)
  Scope:    all accounts
  Retroactive: no
  CLI:      monarch rules create \
              --merchant equals:"<merchant>" \
              --set-category <category-id>
```

If you propose a tag action alongside the category, add `--add-tag <tag-id>` to the CLI and include the tag name in the human-readable shape.

## Approval flow integration

In the action table, distinguish three approval states per row:

- **Apply once** — category change on this single transaction only. No rule.
- **Apply + create rule** — category change PLUS create the Monarch rule shown.
- **Skip** — Adam declines; reviewer must add the merchant to `rules.md` Rule-Recommendation Rules with the reason ("declined because <X>") so future reviews don't re-surface it.

When Adam approves rule creation, run the exact CLI command shown. Then verify with `monarch rules get <new-rule-id>` and surface the new rule id in the work summary.

## Capabilities NOT exposed by `monarch rules create`

The Monarch rule data model supports more actions than the CLI currently creates: splitTransactions, setHideFromReports, reviewStatus, sendNotification, needsReviewByUser, unassignNeedsReviewByUser, linkGoal. The CLI's `create` only wires `--set-category`, `--set-merchant`, `--add-tag`.

If a rule recommendation logically needs one of the unsupported actions (e.g., "hide all internal Apple Cash payments from reports"), surface it as a Needs Review row with a note that the CLI cannot create that rule shape today — do not silently downgrade to a category-only rule.
