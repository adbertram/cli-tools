# Monarch Transaction Review Rules

Persistent memory of Adam's preferences for transaction reviews. The Monarch transaction reviewer workflow (and any other caller doing a Monarch review through this skill) reads this file at the start of every review and updates it whenever Adam gives feedback that establishes a durable rule.

## How this file works

- **READ FIRST.** Before listing categories or transactions, the reviewer reads this file and treats every rule below as the baseline policy for the review. Rules here override default heuristics.
- **WRITE ON FEEDBACK.** When Adam says "always", "never", "from now on", "stop doing X", "don't recommend a rule for Y", or corrects a recommendation with reasoning that generalizes beyond the single transaction, append or update the relevant section BEFORE ending the review.
- **CONFLICT RESOLUTION.** If a new instruction contradicts an existing rule, replace the old rule — do not append duplicates. Note the change inline so the history is visible (`Updated YYYY-MM-DD: ...`).
- **FORMAT.** Each rule is a single bullet under the right section, stated as an imperative, unambiguous, and self-contained (a future reviewer reading only this file must understand the rule without the original conversation).
- **NEVER INVENT.** Only write rules Adam has explicitly stated or unmistakably implied. Do not extrapolate from a single category change into a general rule unless Adam frames it generally.
- **CENTRAL SOURCE.** This file lives at `/Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills/monarch-cli/rules.md`. The repo-owned cli-tools skill bundle is the source of truth for Monarch reviewer scripts and policy.

## Categorization Rules

Rules that determine which Monarch category a transaction belongs in. Each rule should specify the matcher (merchant string, amount range, account) and the target category by name (the reviewer resolves the name → ID at runtime).

- **Vacation budget → Travel & Vacation.** Every transaction whose account or budget is the Vacation budget must be categorized as a vacation expense (default category: `Travel & Vacation`). This covers the obvious cases (hotels, lodging, flights, Airbnb, rental cars, attraction tickets purchased during travel) AND any transaction whose merchant location is outside the Evansville, IN metro area — out-of-area gas, restaurants, groceries, retail, ATMs, etc. all count as travel expenses when the funding account is Vacation. Treat a non-Evansville merchant address on a Vacation-account transaction as positive evidence of travel, not as ambiguous. The only Vacation-account transactions that should NOT be Travel & Vacation are internal transfers and account fees — flag any other suspected exception to Adam before recategorizing.

- **Updated 2026-10-25: Always split matched multi-item Amazon orders, for both default (Adam) and randafaith (Miranda).** Produce one child transaction per item, categorize each from its own item evidence, even if every item happens to share a category. Use verified extended item prices as weights. Item amount equals its price plus its proportional share of the order-level tax/shipping/promotion adjustment; round half up to cents, with the LAST item absorbing the remainder so signed children sum exactly to the original Monarch amount. Missing any item price means no split, keep the original whole and mark needs-input; never fabricate prices. Keep single-item orders whole. Do not create or apply merchant-level Amazon categorization rules to these item splits, consistent with the never-rule-multi-category-merchants policy.

## Rule-Recommendation Rules

Rules that govern WHEN the reviewer should propose creating a Monarch transaction rule vs. only updating a single transaction. Use this section to capture merchants where Adam has declined a rule recommendation or where rule creation is known to be unsafe (e.g., merchant strings that collide across categories).

_(none yet)_

## Evidence-Gathering Rules

Rules about when to fetch external evidence — Amazon order lookup, Apple receipt lookup, Venmo memo lookup. Use this section to capture amount thresholds, merchant exceptions, or "don't bother" cases that save round-trips.

- **Updated 2026-10-25: Amazon evidence must cover both household accounts.** For every Monarch merchant/vendor containing `Amazon`, check `amazon auth status` and verify browser-session authentication for BOTH `default` (Adam) and `randafaith` (Miranda, randafaith@gmail.com). Run `amazon orders match --profile default --amount {amount} --date {date} --limit 1000` AND the same command with `--profile randafaith` before final categorization or approval, even when the first account has a match. With an ISO date and no `--query`, the CLI traverses the complete order history for that year. Omit `--query` for this sweep; use a separate query lookup only as additional evidence. A result limit is not proof of complete traversal. Use `amazon orders get --profile <matched-profile> <line-id>` when needed. Record the source profile/account alongside each order ID, item list, order date, and total in the row description (audit: evidence). Evaluate ambiguity across both accounts. Only report no match after both lookups complete; a missing/unauthenticated account or incomplete traversal is blocked/incomplete evidence, never a clean negative. For multiple plausible orders, no matching order, or an unresolved auth/security gate, mark the row as needing input instead of guessing.
- **Updated 2026-06-14: Venmo classification is deterministic.** For any Monarch transaction whose merchant/vendor contains `Venmo`, run `/Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills/monarch-cli/scripts/classify-venmo.sh` before final categorization or approval. If the classifier returns `needs_account_user`, ask Adam which Venmo account/auth profile should be used before running any Venmo transaction lookup. Do not query every Venmo auth profile to find a match. The classifier may suggest a category only when exactly one Venmo payment matches and exactly one explicit rule in `data/venmo-classification-rules.json` matches the payment evidence.

## Approval Rules

Rules that change the approval flow itself — auto-apply conditions, mandatory hold-for-approval conditions, default batch sizes.

_(none yet)_

## Out-of-Scope / Skip Rules

Rules about which transactions to exclude from review entirely (internal transfers, specific accounts, specific merchants Adam doesn't want surfaced).

_(none yet)_

## Deep-Inspection Vendors

Data-driven mapping of vendor patterns to evidence CLI commands. After the main review table is rendered, the reviewer scans every row for matches against these patterns and (if any match) asks Adam whether to run deep inspection. When approved, the reviewer runs the configured CLI command to look up the order/purchase, identify the items purchased, and use that evidence to refine the Suggested Category for the row.

Format: each entry is `- <vendor-pattern>` (substring match, case-insensitive, against the Monarch merchant name) followed by indented sub-bullets:
  - `command:` CLI command template to run; the reviewer fills `{amount}`, `{date}`, and `{query}` from the Monarch transaction. `{amount}` is the absolute transaction amount. `{query}` is the best available merchant/original-statement/memo text for evidence lookup.
  - `evidence:` what the CLI result should return (e.g. "order item names, order total, order date")
  - `notes:` (optional) caveats — e.g. "multiple orders may match; ask Adam to disambiguate"

The reviewer must ASK before running inspection except for Amazon rows, which are governed by the mandatory Amazon evidence rule above. Adam can decline per-vendor or per-row for optional vendors. Declines for a single session do not persist; durable declines ("never deep-inspect Apple under $20") go under Evidence-Gathering Rules above and override this section.

- Amazon
  - command: for profile in default randafaith; do amazon orders match --profile "$profile" --amount {amount} --date {date} --limit 1000; done
  - evidence: source profile/account, order ID, order item names, order total, order date, shipping address if available
  - notes: mandatory evidence workflow across default (Adam) and randafaith (Miranda); preserve each command's profile provenance and completion status separately before combining evidence
- Apple
  - command: apple purchases match --amount {amount} --date {date} --query {query} --limit 10
  - evidence: purchase/subscription name, receipt date, service vs. app vs. subscription
  - notes: $33.15 Family Checking matches Apple One subscription without inspection
- Venmo
  - command: /Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills/monarch-cli/scripts/classify-venmo.sh --transaction-json {transaction_json}
  - evidence: payment note, counterparty, amount, completion date, resolved auth profile, deterministic category rule if one matches
  - notes: mandatory classifier workflow; if account user/profile is unknown with multiple profiles, ask Adam before any Venmo transaction lookup
