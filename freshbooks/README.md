# FreshBooks CLI Guide

## DESCRIPTION

The `freshbooks` CLI provides a command-line interface for FreshBooks accounting API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Overview

The FreshBooks CLI provides access to:
- **Invoices** - Manage invoices (list, get, create, send, update, delete, mark-paid, download)
- **Customers** - Manage clients (list, get, find, create, update)

## Authentication

Authentication is handled via OAuth2 credentials in a runtime profile.

### Prerequisites

Create or update a FreshBooks authentication profile with these OAuth2 fields:
- `FRESHBOOKS_ACCOUNT_ID`
- `FRESHBOOKS_CLIENT_ID`
- `FRESHBOOKS_CLIENT_SECRET`
- `FRESHBOOKS_ACCESS_TOKEN`
- `FRESHBOOKS_REFRESH_TOKEN`

---

## Invoice Commands

Manage FreshBooks invoices.

### List Invoices

```bash
freshbooks invoice list                         # List all invoices
freshbooks invoice list                 # List as formatted table
freshbooks invoice list --status sent           # Filter by status
freshbooks invoice list --unpaid        # List unpaid invoices
freshbooks invoice list --limit 10              # Limit results
freshbooks invoice list --from 2024-01-01 --to 2024-12-31  # Filter by date range
```

**Options:**
| Option | Description |
|--------|-------------|
| `-s, --status` | Filter by status (draft, sent, viewed, paid, overdue) |
| `-u, --unpaid` | Filter to show only unpaid invoices (sent, viewed, overdue) |
| `-l, --limit` | Maximum number of invoices to return (default: 100) |
| `--from` | Filter invoices created on or after this date (YYYY-MM-DD) |
| `--to` | Filter invoices created on or before this date (YYYY-MM-DD) |

### Get Invoice Details

```bash
freshbooks invoice get <invoice-id>
```

### Create Invoice

```bash
freshbooks invoice create -c <customer-id> -d "Service" -a 100.00
freshbooks invoice create -c 12345 -d "Consulting" -a 500.00 -n "Notes" -p "PO-123"
freshbooks invoice create -c 12345 -d "Contract Work" -a 1000.00 -f ./contract.pdf
freshbooks invoice create -c 12345 -d "Consulting" -a 500.00 --due-days 60
```

**Options:**
| Option | Description |
|--------|-------------|
| `-c, --customer-id` | **(Required)** Customer ID to invoice |
| `-d, --description` | **(Required)** Line item description |
| `-a, --amount` | **(Required)** Line item amount (e.g., '500.00') |
| `-q, --quantity` | Line item quantity (default: 1) |
| `-n, --notes` | Invoice notes |
| `-p, --po-number` | Purchase order number/reference |
| `-f, --attachment` | Path to file to attach (PDF or image) |
| `--due-days` | Number of days until invoice is due (default: 30) |

### Send Invoice

```bash
freshbooks invoice send <invoice-id>
freshbooks invoice send <invoice-id> --email client@example.com
freshbooks invoice send <invoice-id> --force
```

**Options:**
| Option | Description |
|--------|-------------|
| `-e, --email` | Override recipient email address |
| `-F, --force` | Skip confirmation prompt |

### Mark Invoice Paid

```bash
freshbooks invoice mark-paid <invoice-id> --amount 500.00
freshbooks invoice mark-paid <invoice-id> -a 500.00 -d 2024-01-15
```

**Options:**
| Option | Description |
|--------|-------------|
| `-a, --amount` | **(Required)** Payment amount |
| `-d, --date` | Payment date (YYYY-MM-DD, default: today) |

### Delete Invoice

```bash
freshbooks invoice delete <invoice-id>
freshbooks invoice delete <invoice-id> --force
```

**Options:**
| Option | Description |
|--------|-------------|
| `-F, --force` | Skip confirmation prompt |

### Update Invoice

```bash
freshbooks invoice update <invoice-id> -f ./contract.pdf
freshbooks invoice update <invoice-id> -n "Updated notes"
freshbooks invoice update <invoice-id> -f ./receipt.pdf -n "Added receipt"
```

**Options:**
| Option | Description |
|--------|-------------|
| `-f, --attachment` | Path to file to attach (PDF or image) |
| `-n, --notes` | Update invoice notes |
| `-p, --po-number` | Update purchase order number/reference |

### Download Invoice PDF

```bash
freshbooks invoice download <invoice-id>
freshbooks invoice download <invoice-id> -o ~/Downloads/invoice.pdf
freshbooks invoice download <invoice-id> --output ./my-invoice.pdf
```

**Options:**
| Option | Description |
|--------|-------------|
| `-o, --output` | Output file path (default: invoice_{number}.pdf in current directory) |

---

## Customer Commands

Manage customers/clients.

### List Customers

```bash
freshbooks customer list
freshbooks customer list
freshbooks customer list --filter "Acme"
freshbooks customer list --limit 10
freshbooks customer list --properties id,organization,email
```

**Options:**
| Option | Description |
|--------|-------------|
| `-f, --filter` | Filter by name, organization, or email (case-insensitive) |
| `-l, --limit` | Maximum number of customers to return (default: 100) |
| `-p, --properties` | Comma-separated list of properties to display |

### Get Customer Details

```bash
freshbooks customer get <customer-id>
```

### Find Customer by Email

```bash
freshbooks customer find client@example.com
```

### Create Customer

```bash
freshbooks customer create -e john@acme.com -f John -l Doe -o "Acme Corp"
```

**Options:**
| Option | Description |
|--------|-------------|
| `-e, --email` | **(Required)** Customer email address |
| `-f, --first-name` | **(Required)** Contact first name |
| `-l, --last-name` | **(Required)** Contact last name |
| `-o, --organization` | **(Required)** Organization/company name |

### Update Customer

```bash
freshbooks customer update <customer-id> --email new@example.com
freshbooks customer update <customer-id> -o "New Org Name"
```

**Options:**
| Option | Description |
|--------|-------------|
| `-e, --email` | New email address |
| `-f, --first-name` | New first name |
| `-l, --last-name` | New last name |
| `-o, --organization` | New organization name |

## Cache

```bash
freshbooks cache status
freshbooks cache clear
```
