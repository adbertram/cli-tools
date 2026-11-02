# Weekly CLI

## DESCRIPTION

Read Weekly budgets, saved balances, and transaction exports, manage manual spending entries, and split eligible bank-linked expenses. Use it for scriptable access using a privately captured native session.

## Usage

Weekly's native Firebase session and transaction export settings can be imported from authorized iOS captures. Keep the capture directories private and remove them after import. Select the captured segment with `--flow-file`; the default is `wg-export.flows`. The renewable session and observed export settings are stored in the CLI-tools secret manager. The proxy is not needed after import.

```bash
weekly auth import-capture /private/tmp/ios-cli-LOGIN
weekly auth import-export /private/tmp/ios-cli-EXPORT --flow-file wireguard-1.flows
weekly auth status
weekly auth refresh
weekly cache --help
weekly budget current
weekly balances list
weekly categories list
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

`budget current` returns the current week, recurring items, funds, and named budget preferences. It does not calculate the app’s safe-to-spend total; `initialWeeklySpendingLimit` is an initial preference. `balances list` returns saved linked-account records, not a bank refresh. Without a filter, an explicit balance limit is applied using Firestore pagination; filtered balance limits apply after local filtering.

`transactions create` requires an existing category name and creates a manual safe-to-spend entry. Positive amounts represent spending. The optional `--date YYYY-MM-DD` defaults to today in the account timezone. New entries use the observed native color `warning`. `transactions update --category` changes the category of a non-transfer safe-to-spend entry, including a bank-linked entry. Amount and title changes remain limited to manual entries; combined updates on bank-linked entries are rejected. Every update uses a server-side update-time precondition.

`transactions split` divides an eligible 10.00 expense in the example above. It accepts only positive, unsplit, bank-linked, non-transfer Safe-to-Spend expenses. Manual entries, refunds, transfers and already-split entries are rejected. Provide at least two `--part AMOUNT:CATEGORY` values with positive amounts in exact cents that total the original amount exactly. Each category must resolve uniquely, without regard to case, among the current account's saved categories (`weekly categories list`). Optional `--table` and `--profile NAME` select the output format and profile.

The first part keeps the source transaction ID; later parts receive new IDs. All parts preserve the original title, date, color and complete bank link. The changes are committed atomically. If an error leaves the outcome uncertain, use the reported transaction IDs to reconcile the result before taking further action; don't blindly retry.
