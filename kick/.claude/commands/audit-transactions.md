---
description: Audit transactions to ensure correct counterparty assignments
model: claude-opus-4-5-20251101
argument-hint: [limit]
---

Audit Kick transactions to identify counterparty (client) assignment issues and provide fixes.

## Step 1: Fetch Transaction Data

Fetch recent transactions (default 500, or use provided limit):
```bash
kick transactions list --limit ${1:-500}
```

This returns JSON with transaction data including:
- `id` - Transaction ID
- `displayDescription` - Cleaned description shown in UI
- `bankDescription` - Raw bank description (contains source patterns)
- `counterparty` - Object with `id` and `name` (null if not assigned)
- `counterpartyId` - UUID of assigned client (null if none)
- `financialAccount.name` - Which account (e.g., "Product Basket, LLC")

## Step 2: Get Available Clients

Fetch the client list for reference:
```bash
kick clients list --limit 200
```

## Step 3: Identify Issues

Analyze transactions for these issue types:

### Issue Type 1: Missing Counterparty
Transactions where `counterparty` is null. Filter by checking:
- Exclude transfers/withdrawals (these legitimately have no client)
- Flag transactions that appear to be purchases or income but lack a client

### Issue Type 2: Mismatched Counterparty by Description Pattern
Look for transactions where `bankDescription` contains a pattern that indicates a specific client, but a different (or no) counterparty is assigned:

**Known patterns to check:**
- "BrickLink Order" → should be "Bricklink"
- "Brick Owl Order" → should be "Brick Owl"  
- "PayPal Fee" associated with a specific vendor → should match parent transaction vendor
- Any "Payment from [Name]" pattern → verify [Name] matches counterparty

For each transaction, compare:
1. The `bankDescription` field for identifying patterns
2. The `displayDescription` for context
3. The current `counterparty.name` assignment

## Step 4: Report Findings

Present findings in a table:
| ID | Date | Bank Description | Display Description | Current Client | Expected Client | Issue |
|----|------|------------------|---------------------|----------------|-----------------|-------|

Group by issue type and provide counts.

## Step 5: Provide Fix Commands

For each mismatched transaction, show the fix command:

**To update a single transaction counterparty:**
```bash
kick transactions update TRANSACTION_ID --counterparty-id CLIENT_UUID
```

**To find a client UUID:**
```bash
kick clients list --filter "name:ClientName"
```

## Step 6: Suggest Rules for Recurring Patterns

If a pattern appears multiple times, suggest creating a rule:
```bash
kick rule-groups rules list  # Show existing rules
```

Note: The CLI `rules add` command only supports counterparty-based matching. For description-based rules (like "BrickLink Order" → Bricklink), use the Kick web UI or the Python API directly with `description_includes` condition type.

**Example rule conditions supported by API:**
- `entity` - Match by business entity
- `counterparty` - Match by existing counterparty
- `financial_accounts` - Match by account
- `description_includes` - Match if description contains text
- `description_is` - Exact description match
- `amount` - Match by amount range
- `date` - Match by date range

## Summary Output

End with:
1. Total transactions audited
2. Number with missing counterparty
3. Number with potentially wrong counterparty
4. Recommended actions (bulk fixes or rules to create)
