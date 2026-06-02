# Monarch Transaction Review Rules

Persistent repo-local rules for Monarch transaction reviews. Keep this file generic: do not store personal names, addresses, locations, account names, family information, or private merchant/category preferences here.

## How this file works

- **READ FIRST.** Before listing categories or transactions, the reviewer reads this file and treats every rule below as the baseline policy for the review. Rules here override default heuristics.
- **WRITE ON FEEDBACK.** When the user says "always", "never", "from now on", "stop doing X", "don't recommend a rule for Y", or corrects a recommendation with reasoning that generalizes beyond the single transaction, append or update the relevant section BEFORE ending the review.
- **CONFLICT RESOLUTION.** If a new instruction contradicts an existing rule, replace the old rule — do not append duplicates. Note the change inline so the history is visible (`Updated YYYY-MM-DD: ...`).
- **FORMAT.** Each rule is a single bullet under the right section, stated as an imperative, unambiguous, and self-contained (a future reviewer reading only this file must understand the rule without the original conversation).
- **NEVER INVENT.** Only write rules the user has explicitly stated or unmistakably implied. Do not extrapolate from a single category change into a general rule unless the user frames it generally.
- **NO PRIVATE DATA.** If a durable rule would require personal or account-specific details, store it in the user's private runtime memory instead of this repository file.

## Categorization Rules

Rules that determine which Monarch category a transaction belongs in. Each rule should specify the matcher (merchant string, amount range, account type) and the target category by name (the reviewer resolves the name to ID at runtime).

_(none)_

## Rule-Recommendation Rules

Rules that govern WHEN the reviewer should propose creating a Monarch transaction rule vs. only updating a single transaction. Use this section to capture merchants where the user has declined a rule recommendation or where rule creation is known to be unsafe (e.g., merchant strings that collide across categories).

_(none yet)_

## Evidence-Gathering Rules

Rules about when to fetch external evidence — Amazon order lookup, Apple receipt lookup, Venmo memo lookup. Use this section to capture amount thresholds, merchant exceptions, or "don't bother" cases that save round-trips.

- **Updated 2026-05-30: Venmo classification is deterministic.** For any Monarch transaction whose merchant/vendor contains `Venmo`, run `_repo/skills/monarch-cli/scripts/classify-venmo.sh` before final categorization or approval. If the classifier returns `needs_account_user`, ask the user which Venmo account/auth profile should be used before running any Venmo transaction lookup. Do not query every Venmo auth profile to find a match. The classifier may suggest a category only when exactly one Venmo payment matches and exactly one explicit rule in `data/venmo-classification-rules.json` matches the payment evidence.

## Approval Rules

Rules that change the approval flow itself — auto-apply conditions, mandatory hold-for-approval conditions, default batch sizes.

_(none yet)_

## Out-of-Scope / Skip Rules

Rules about which transactions to exclude from review entirely (internal transfers, specific account types, or specific merchants the user does not want surfaced).

_(none yet)_

## Deep-Inspection Vendors

Data-driven mapping of vendor patterns to evidence CLI commands. After the main review table is rendered, the reviewer scans every row for matches against these patterns and (if any match) asks the user whether to run deep inspection. When approved, the reviewer runs the configured CLI command to look up the order/purchase, identify the items purchased, and use that evidence to refine the Suggested Category for the row.

Format: each entry is `- <vendor-pattern>` (substring match, case-insensitive, against the Monarch merchant name) followed by indented sub-bullets:
  - `command:` CLI command template to run; the reviewer fills `{amount}`, `{date}`, and `{query}` from the Monarch transaction. `{amount}` is the absolute transaction amount. `{query}` is the best available merchant/original-statement/memo text for evidence lookup.
  - `evidence:` what the CLI result should return (e.g. "order item names, order total, order date")
  - `notes:` (optional) caveats — e.g. "multiple orders may match; ask the user to disambiguate"

The reviewer must ASK before running inspection except for Amazon rows, which are governed by the mandatory Amazon evidence rule above. the user can decline per-vendor or per-row for optional vendors. Declines for a single session do not persist; durable declines ("never deep-inspect Apple under $20") go under Evidence-Gathering Rules above and override this section.

- Amazon
  - command: amazon orders match --amount {amount} --date {date} --query {query} --limit 10
  - evidence: order item names, order total, order date, shipping address if available
  - notes: marker only; use the mandatory amazon-browser agent workflow instead of this CLI command
- Apple
  - command: apple purchases match --amount {amount} --date {date} --query {query} --limit 10
  - evidence: purchase/subscription name, receipt date, service vs. app vs. subscription
  - notes: $33.15 Family Checking matches Apple One subscription without inspection
- Venmo
  - command: _repo/skills/monarch-cli/scripts/classify-venmo.sh --transaction-json {transaction_json}
  - evidence: payment note, counterparty, amount, completion date, resolved auth profile, deterministic category rule if one matches
  - notes: mandatory classifier workflow; if account user/profile is unknown with multiple profiles, ask the user before any Venmo transaction lookup
