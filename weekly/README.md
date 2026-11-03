# Weekly CLI

## DESCRIPTION

Read Weekly budgets, saved balances, and transaction exports, manage manual spending entries, and split eligible bank-linked expenses. Use it for scriptable access using a privately captured native session.

## Usage

`categories create` creates a Safe-to-Spend category (not a savings fund). It requires explicit `--name`, `--color` and `--emoji` values and refuses an existing name, ignoring case. It leaves all existing categories unchanged. If creation reports an uncertain outcome, check `weekly --no-cache categories list` before retrying.

Weekly's native Firebase session and transaction export settings can be imported from authorized iOS captures. Keep the capture directories private and remove them after import. Select the captured segment with `--flow-file`; the default is `wg-export.flows`. The renewable session and observed export settings are stored in the CLI-tools secret manager. The proxy is not needed after import.

```bash
weekly auth import-capture /private/tmp/ios-cli-LOGIN
weekly auth import-export /private/tmp/ios-cli-EXPORT --flow-file wireguard-1.flows
weekly auth status
weekly auth refresh
weekly cache --help
weekly budget current
weekly weeks list
weekly weeks get WEEK_ID
weekly weeks delete WEEK_ID --dry-run
weekly weeks delete WEEK_ID --yes
weekly weeks create --start-date 2026-10-09 --end-date 2026-10-15 --spending-limit 100.00 --dry-run
weekly balances list
weekly categories list
weekly categories create --name Christmas --color red --emoji '🎄'
weekly transactions list --range all
weekly transactions list --unreviewed
weekly transactions list --range month_to_date --table
weekly transactions get TRANSACTION_ID --range all
weekly transactions create --title "Coffee" --amount 4.50 --category Other
weekly transactions update TRANSACTION_ID --amount 5.00 --title "Coffee and tip"
weekly transactions update TRANSACTION_ID --category Groceries
weekly transactions split TRANSACTION_ID --part '6.00:Groceries' --part '4.00:Other'
```

Transaction list/get output preserves the CSV export's columns. Supported range values are `all` and `month_to_date`; `all` is the default. The captured export's exclusion flags and timezone offset remain in effect. `--timezone-offset` overrides the captured offset. The full CSV is fetched before local filtering and limits; there is no default row limit. `--properties` selects output fields; `get` searches only that selected export range.

`transactions list --unreviewed` lists the current-week review queue (CSV `Target=INITIAL`) using the saved account timezone and current week. The full all-range export is fetched, then the queue filter is applied before any requested filter and limit. It requires `--range all` and cannot be combined with `--timezone-offset`.

`weeks list` and `weeks get` return saved week records with inclusive `startDate` and `endDate`. `allowanceAmount` is the recorded limit on historical weeks; it can be absent on the initial current week, and the CLI does not invent a replacement.

`weeks delete WEEK_ID --dry-run` previews the selected week's dates, recorded limit and current-week impact. `--yes` deletes that one budget record with its server update-time precondition and confirms it is absent. The CLI does not delete transactions or fund contributions, or recalculate later rollover balances. Deleting a current week leaves current-budget and unreviewed-transaction commands without a current week until one covering today exists. An uncertain result must be checked with a fresh `weekly --no-cache weeks list` before retrying. This is a single-document backend operation, not a claim about any native app deletion workflow.

`weeks create` fills in a completed past week using explicit dates and `--spending-limit` (exact cents, including zero). It refuses dates overlapping any saved week and does not impose a seven-day duration. `--dry-run` returns the proposed record without writing; omit it to create the week. The observed historical flow uses no rollover, reads `currentPlan` from the unique current saved week, sums positive signed bank expenses into the historical summary, and leaves transactions, funds, recurring items and user preferences unchanged. Ranges containing reviewed, manual or transfer entries are refused because their historical creation semantics have not been established. Current and upcoming week creation is unsupported; it is rejected explicitly rather than creating a local future plan. If an outcome is uncertain, inspect a fresh `weekly --no-cache weeks list` before retrying.

`budget current` returns the current week, recurring items, funds, and named budget preferences. It does not calculate the app’s safe-to-spend total; `initialWeeklySpendingLimit` is an initial preference. `balances list` returns saved linked-account records, not a bank refresh. Without a filter, an explicit balance limit is applied using Firestore pagination; filtered balance limits apply after local filtering.

`transactions create` requires an existing category name and creates a manual safe-to-spend entry. Positive amounts represent spending. The optional `--date YYYY-MM-DD` defaults to today in the account timezone. New entries use the observed native color `warning`. `transactions update --category` changes the category of a non-transfer safe-to-spend entry, including a bank-linked entry. Amount and title changes remain limited to manual entries; combined updates on bank-linked entries are rejected. Every update uses a server-side update-time precondition.

`transactions split` divides an eligible 10.00 expense in the example above. It accepts only positive, unsplit, bank-linked, non-transfer Safe-to-Spend expenses. Manual entries, refunds, transfers and already-split entries are rejected. Provide at least two `--part AMOUNT:CATEGORY` values with positive amounts in exact cents that total the original amount exactly. Each category must resolve uniquely, without regard to case, among the current account's saved categories (`weekly categories list`). Optional `--table` and `--profile NAME` select the output format and profile.

The first part keeps the source transaction ID; later parts receive new IDs. All parts preserve the original title, date, color and complete bank link. The changes are committed atomically. If an error leaves the outcome uncertain, use the reported transaction IDs to reconcile the result before taking further action; don't blindly retry.

## Recurring bills and income

```bash
weekly bills list
weekly bills list --filter 'category:eq:utilities' --properties id,title,amount,interval
weekly bills get ITEM_ID
weekly bills create --title Electricity --amount 35.75 --interval monthly --category utilities --emoji '💡' --emoji-color blue --next-date 2026-11-15 --dry-run
weekly bills create --title Electricity --amount 35.75 --interval monthly --category utilities --emoji '💡' --emoji-color blue --next-date 2026-11-15
weekly bills create --title Paycheck --amount 1000.00 --kind income --interval weekly --category income --emoji '💰' --emoji-color yellow --dry-run
```

`bills list/get` returns saved recurring bill and income records with their native fields. List supports the standard filter, limit, properties and table options. Reading does not refresh bank transactions.

`bills create` requires an explicit description, positive exact-cent amount, interval, bill category, emoji and emoji background color. The kind defaults to `expense`; `income` uses a positive amount and the native success color. The optional `--next-date YYYY-MM-DD` sets both native next-transaction date fields; omitting it leaves those fields absent. `--dry-run` performs local validation and returns the proposed item without contacting the account. Creation writes only the new recurring item. It does not create a payment or change saved week records. An uncertain response must be reconciled with a fresh bills list before retrying.

All 19 app frequencies, 15 bill categories and 7 emoji backgrounds are supported; `weekly bills create --help` lists their identifiers. `bimonthly` means twice a month, `two_months` means every two months, and `uncategorized` is Other. Kind and category can be chosen independently. `--hide-from-reports` excludes the item from reports; `--archived` creates it archived so it does not affect the weekly spending limit. Both flags are optional.
