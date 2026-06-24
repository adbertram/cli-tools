---
name: "monarch-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute monarch operations using the `monarch` CLI tool. CLI for Monarch Money personal finance -- accounts, transactions, budgets, cashflow, categories, tags, institutions, merchants, and transaction rules. Triggers: monarch, monarch cli, monarch money, monarch accounts, monarch transactions, monarch budget, check my finances, my accounts, my transactions, monarch cashflow, monarch categories, monarch rules, monarch transaction rules, create monarch rule, delete monarch rule, list monarch rules"
---

<objective>
Execute monarch operations using the `monarch` CLI. All monarch interactions should use this CLI.
</objective>

<quick_start>
The `monarch` CLI follows this pattern:
```bash
monarch <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check auth status | `monarch auth status` |
| List accounts | `monarch accounts list --table` |
| List transactions (last 30d) | `monarch transactions list --days 30 --table` |
| Search transactions | `monarch transactions list --search "Amazon" --table` |
| Needs-review transactions | `monarch transactions list --needs-review --days 30 --table` |
| Already-reviewed transactions | `monarch transactions list --reviewed --days 30 --table` |
| View budgets this month | `monarch budgets list --month 2024-01 --table` |
| View cashflow summary | `monarch cashflow summary --table` |
| Annual/range income + expense totals | `monarch cashflow summary --start 2025-01-01 --end 2025-12-31 --table` |
| Per-category-group totals for a range | `monarch cashflow list --start 2025-01-01 --end 2025-12-31 --table` |
| Income group total only | `monarch cashflow list --start 2025-01-01 --end 2025-12-31 --filter "group:Income"` |
| List categories | `monarch categories list --table` |
| Sync accounts | `monarch accounts sync --wait` |
| List transaction rules | `monarch rules list --table` |
| Get one rule | `monarch rules get <rule-id>` |
| Create a rule (merchant -> category) | `monarch rules create --merchant contains:amazon --set-category <cat-id>` |
| Update a rule | `monarch rules update <rule-id> --set-category <new-cat-id>` |
| Delete a rule | `monarch rules delete <rule-id> --force` |
| Clear response cache | `monarch cache clear` |
</quick_start>

<essential_principles>
<principle name="Transaction Review Routing">
For requests to review, categorize, recategorize, audit, clean up, or start reviewing Monarch transactions, invoke the `monarch-transaction-reviewer` custom agent instead of performing the review inline.

For these review workflows, do not read `usage.json`, run `monarch` commands, list transactions, load categories, or perform setup in the parent session before spawning the reviewer. The reviewer agent owns those steps.

The subagent prompt must be complete and self-contained, must not use `fork_context`, and must explicitly reference `/Users/adam/Dropbox/.agents/skills/agent-expert/references/global-standards.md`.
</principle>

<principle name="Review Rules Memory">
**MANDATORY: Read `rules.md` at the start of EVERY review — before listing categories or transactions.** It is the persistent memory of Adam's preferences (categorization defaults, rule-recommendation policy, evidence thresholds, skip lists). Apply every rule there as the baseline policy for the run.

**WRITE ON FEEDBACK.** Whenever Adam gives feedback that generalizes — phrased as "always", "never", "from now on", "stop doing X", "don't recommend a rule for Y", or a correction with reasoning that applies beyond the single transaction — append or update the relevant section of `/Users/adam/Dropbox/GitRepos/cli-tools/_repo/skills/monarch-cli/rules.md` BEFORE ending the review. The repo-owned cli-tools skill bundle is the source of truth for Monarch reviewer scripts and policy. Do not create or edit runtime-projected Monarch skill copies for reviewer policy. Mention each rule added or changed in the work summary.

Do not invent rules from a single category change. Only persist what Adam has explicitly stated or unmistakably framed as a durable preference.
</principle>

<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `monarch` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Range / Annual Income & Expense Totals">
To pull income and expense totals for an arbitrary date range (e.g. a full calendar year), use the cashflow aggregates -- they sum the underlying transactions server-side:

- **PRIMARY -- totals:** `monarch cashflow summary --start <YYYY-MM-DD> --end <YYYY-MM-DD>` returns `sumIncome`, `sumExpense`, `savings`, and `savingsRate` for the range. With no dates it summarizes the current month.
- **PRIMARY -- per-group breakdown:** `monarch cashflow list --start <d> --end <d>` returns one row per category group with `id`, `group`, and `sum`. Add `--filter "group:Income"` to isolate the Income group total (income groups are positive; expense groups are negative).
- **FALLBACK / cross-check:** sum `monarch transactions list --category <id> --start <d> --end <d> --limit 5000` across the Income-group categories (Paychecks, Interest, Business Income, Other Income). Use this only to validate the cashflow figure; the cashflow aggregates are the primary source.

**Caveat (self-employed):** the "Business Income" category is gross business deposits, not Schedule C net income. Do not treat the cashflow income total as taxable/net income for a self-employed user -- business expenses are tracked separately and are not netted out here.
</principle>

<principle name="Command Groups">
- **auth** -- Manage authentication (login, logout, status, refresh, test)
- **auth** -- Authentication commands and nested `auth profiles` management
- **accounts** -- Manage accounts (list, get, history, holdings, sync)
- **transactions** -- Manage transactions (list, get, update, recurring)
- **budgets** -- View budgets (list, get)
- **categories** -- Manage categories (list, get)
- **category-groups** -- Manage category groups (list, get)
- **tags** -- Manage tags (list, get)
- **cashflow** -- View cashflow (summary, list, get)
- **institutions** -- Manage linked institutions (list, get)
- **merchants** -- Manage merchants (list, get)
- **rules** -- Manage transaction rules (list, get, create, update, delete)
- **cache** -- Manage response cache (clear)
</principle>
</essential_principles>

<reference_index>
- **`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions for every command.
- **`rules.md`** -- Persistent memory of Adam's review preferences. MANDATORY reading at the start of every transaction review. Update on user feedback.
- **`workflows/recommend-rule.md`** -- Decision criteria for when the reviewer should propose creating a Monarch rule alongside a single-transaction category change. MANDATORY reading whenever the reviewer is about to surface a category-change recommendation.
- **`data/venmo-classification-rules.json`** -- Explicit deterministic Venmo note/counterparty to Monarch category mappings. Do not infer categories outside these rules.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
