# Implementation Plan: Fix FreshBooks CLI Compliance

## Summary
The FreshBooks CLI requires compliance fixes including missing infrastructure (install.sh, models/), missing output function (print_info), non-standard force flags (--yes/-y instead of --force/-F), missing command options (--limit, --properties, --from/--to), and client.py retry logic.

## Why This Approach
- Groups changes by file to minimize context switching
- Follows existing template patterns from `_repo/_templates/api/` for retry logic and models
- Prioritizes critical failures (blocking issues) before warnings
- Uses the simplest possible changes that satisfy compliance requirements

## What's NOT Included
- Pydantic models: Marked as missing infrastructure but FreshBooks CLI currently works without them (deferred - optional enhancement)
- API-level --filter conversion: Requires significant refactoring of customer list; current client-side filtering works (deferred)

## Prerequisites
- Python 3.9+ with virtual environment activated
- Access to FreshBooks API for testing

---

## Implementation Steps

### Step 1: Create install.sh

**File:** `<cli-tools-root>/freshbooks/install.sh`
**Action:** Create new file with standard install script content

```bash
#!/bin/bash
# Install script for freshbooks CLI
# Run this script to set up the CLI for the current user

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI_NAME="freshbooks"

echo "Installing $CLI_NAME CLI..."

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not found"
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "$SCRIPT_DIR/venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$SCRIPT_DIR/venv"
fi

# Activate venv and install
echo "Installing package..."
source "$SCRIPT_DIR/venv/bin/activate"

# Upgrade pip first (old versions don't support pyproject.toml editable installs)
pip3 install --upgrade pip --quiet

pip3 install -e "$SCRIPT_DIR" --quiet

# Ensure ~/.local/bin exists
LOCAL_BIN="$HOME/.local/bin"
mkdir -p "$LOCAL_BIN"

# Create symlink
SYMLINK_PATH="$LOCAL_BIN/$CLI_NAME"
VENV_BIN="$SCRIPT_DIR/venv/bin/$CLI_NAME"

if [ -L "$SYMLINK_PATH" ]; then
    rm "$SYMLINK_PATH"
fi

if [ -e "$SYMLINK_PATH" ]; then
    echo "Warning: $SYMLINK_PATH exists and is not a symlink. Skipping."
else
    ln -s "$VENV_BIN" "$SYMLINK_PATH"
    echo "Created symlink: $SYMLINK_PATH -> $VENV_BIN"
fi

# Check if ~/.local/bin is in PATH
if [[ ":$PATH:" != *":$LOCAL_BIN:"* ]]; then
    echo ""
    echo "WARNING: $LOCAL_BIN is not in your PATH"
    echo "Add this to your ~/.zshrc or ~/.bashrc:"
    echo ""
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo ""
fi

echo ""
echo "Installation complete!"
echo ""

# Verify
if command -v $CLI_NAME &> /dev/null; then
    echo "Verified: $($CLI_NAME --version)"
else
    echo "Run 'hash -r' or open a new terminal, then try: $CLI_NAME --version"
fi
```

**Then:** `chmod +x <cli-tools-root>/freshbooks/install.sh`
**Verify:** `ls -la <cli-tools-root>/freshbooks/install.sh` shows executable

---

### Step 2: Add print_info() to output.py

**File:** `<cli-tools-root>/freshbooks/freshbooks_cli/output.py`
**Action:** Add `print_info()` function after `print_success()` (around line 86)

Insert before `handle_error`:
```python
def print_info(message: str):
    """Print informational message to stderr."""
    print(message, file=sys.stderr)
```

**Verify:** `grep -n "print_info" <cli-tools-root>/freshbooks/freshbooks_cli/output.py` shows the function

---

### Step 3: Change --yes/-y to --force/-F in invoice.py

**File:** `<cli-tools-root>/freshbooks/freshbooks_cli/commands/invoice.py`
**Action:** Update 2 locations

**Location 1 - invoice send (lines 207-212):**
Change:
```python
    confirm: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt",
    ),
```
To:
```python
    force: bool = typer.Option(
        False,
        "--force",
        "-F",
        help="Skip confirmation prompt",
    ),
```

Also update usage on line 232: change `if not confirm:` to `if not force:`

**Location 2 - invoice delete (lines 255-260):**
Change:
```python
    confirm: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt",
    ),
```
To:
```python
    force: bool = typer.Option(
        False,
        "--force",
        "-F",
        help="Skip confirmation prompt",
    ),
```

Also update usage on line 279: change `if not confirm:` to `if not force:`

**Verify:** `freshbooks invoice send --help | grep -E "force|yes"` shows `--force/-F`

---

### Step 4: Add --limit/-l to invoice list

**File:** `<cli-tools-root>/freshbooks/freshbooks_cli/commands/invoice.py`
**Action:** Add limit option to invoice_list function

Add new parameter after `status`:
```python
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of invoices to return (default: 100)",
    ),
```

Update call to pass limit:
```python
        invoices = client.get_invoices(status=status_filter, per_page=limit)
```

**Verify:** `freshbooks invoice list --help | grep limit` shows the option

---

### Step 5: Add --limit/-l and --properties/-p to customer list

**File:** `<cli-tools-root>/freshbooks/freshbooks_cli/commands/customer.py`
**Action:** Add limit and properties options to customer_list function

Add new parameters after `filter_text`:
```python
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of customers to return (default: 100)",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of properties to display (e.g., 'id,organization,email')",
    ),
```

Update call to pass limit:
```python
        customers = client.get_clients(per_page=limit)
```

Add property filtering before output:
```python
        # Apply property selection
        if properties:
            prop_list = [p.strip() for p in properties.split(",")]
            formatted = [{k: v for k, v in c.items() if k in prop_list} for c in formatted]
```

Update table output to use dynamic columns if properties specified:
```python
        if table:
            if properties:
                prop_list = [p.strip() for p in properties.split(",")]
                print_table(formatted, columns=prop_list, headers=prop_list)
            else:
                print_table(
                    formatted,
                    columns=["id", "organization", "name", "email"],
                    headers=["ID", "Organization", "Contact", "Email"],
                )
```

**Verify:** `freshbooks customer list --help | grep -E "limit|properties"` shows both options

---

### Step 6: Add --from/--to date filtering to invoice list

**File:** `<cli-tools-root>/freshbooks/freshbooks_cli/commands/invoice.py`
**Action:** Add date filtering options to invoice_list

Add new parameters after limit option:
```python
    date_from: Optional[str] = typer.Option(
        None,
        "--from",
        help="Filter invoices created on or after this date (YYYY-MM-DD)",
    ),
    date_to: Optional[str] = typer.Option(
        None,
        "--to",
        help="Filter invoices created on or before this date (YYYY-MM-DD)",
    ),
```

**File:** `<cli-tools-root>/freshbooks/freshbooks_cli/client.py`
**Action:** Update get_invoices method signature and params

Update method signature:
```python
def get_invoices(
    self,
    status: Optional[List[str]] = None,
    per_page: int = 100,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> List[Dict]:
```

Add date params to the params dict:
```python
        if date_from:
            params["search[date_min]"] = date_from
        if date_to:
            params["search[date_max]"] = date_to
```

Update invoice.py to pass date params:
```python
        invoices = client.get_invoices(
            status=status_filter,
            per_page=limit,
            date_from=date_from,
            date_to=date_to,
        )
```

**Verify:** `freshbooks invoice list --help | grep -E "from|to"` shows date options

---

### CHECKPOINT: Verify command options
**Run:**
```bash
freshbooks invoice list --help
freshbooks invoice send --help
freshbooks invoice delete --help
freshbooks customer list --help
```
**Expected:**
- invoice list: shows --limit/-l, --from, --to
- invoice send: shows --force/-F (not --yes/-y)
- invoice delete: shows --force/-F (not --yes/-y)
- customer list: shows --limit/-l, --properties/-p
**If failing:** Fix the specific command before proceeding

---

### Step 7: Add retry logic to client.py

**File:** `<cli-tools-root>/freshbooks/freshbooks_cli/client.py`
**Action:** Add retry configuration and methods following the template pattern

**7a. Add imports at top of file (after line 4):**
```python
import random
import time
```

**7b. Add retry configuration constants after imports:**
```python
# Retry configuration defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 30.0  # seconds
DEFAULT_JITTER = 0.1  # 10% jitter

# HTTP status codes that trigger retry
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
```

**7c. Update `__init__` method signature to accept retry parameters:**
```python
def __init__(
    self,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    jitter: float = DEFAULT_JITTER,
):
```

**7d. Store retry config in `__init__`:**
```python
        # Retry configuration
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
```

**7e. Add helper methods before `_make_request`:**
```python
def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
    """Calculate delay before next retry using exponential backoff with jitter."""
    if retry_after is not None:
        return min(retry_after, self.max_delay)
    delay = self.base_delay * (2 ** attempt)
    jitter_range = delay * self.jitter
    delay += random.uniform(-jitter_range, jitter_range)
    return min(delay, self.max_delay)

def _is_retryable(self, response: Optional[requests.Response], exception: Optional[Exception]) -> bool:
    """Determine if a request should be retried."""
    if exception is not None:
        return isinstance(exception, (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
        ))
    if response is not None:
        return response.status_code in RETRYABLE_STATUS_CODES
    return False

def _get_retry_after(self, response: requests.Response) -> Optional[float]:
    """Extract Retry-After header value from response."""
    retry_after = response.headers.get("Retry-After")
    if retry_after is None:
        return None
    try:
        return float(retry_after)
    except ValueError:
        return None
```

**7f. Update `_make_request` method to add retry parameter and loop:**

Add `retry: bool = True` parameter to method signature.

Replace the current request/retry logic with a retry loop that:
- Attempts up to `max_retries + 1` times when retry=True
- Handles 401 with token refresh (doesn't count against retry limit)
- Retries on RETRYABLE_STATUS_CODES and connection errors
- Uses exponential backoff with jitter
- Honors Retry-After header

**Verify:** `grep -n "max_retries\|_calculate_retry_delay\|RETRYABLE" <cli-tools-root>/freshbooks/freshbooks_cli/client.py` shows all retry components

---

### Step 8: Create models/ directory (OPTIONAL - deferred)

**Files:**
- `<cli-tools-root>/freshbooks/freshbooks_cli/models/__init__.py`
- `<cli-tools-root>/freshbooks/freshbooks_cli/models/invoice.py`
- `<cli-tools-root>/freshbooks/freshbooks_cli/models/customer.py`

**Action:** Create Pydantic models for Invoice and Customer entities.

**Note:** This is optional as the CLI works without Pydantic models. Can be skipped.

---

### Step 9: Update README.md

**File:** `<cli-tools-root>/freshbooks/README.md`
**Action:** Update documentation to reflect changes

1. Change `--yes/-y` to `--force/-F` in Send Invoice and Delete Invoice sections
2. Add `--limit/-l`, `--from`, `--to` to List Invoices section
3. Add `--limit/-l`, `--properties/-p` to List Customers section

**Verify:** Review README.md to ensure all new options are documented

---

### CHECKPOINT: Full verification
**Run:**
```bash
# Test install script exists and is executable
ls -la <cli-tools-root>/freshbooks/install.sh

# Test CLI still works
freshbooks --help
freshbooks invoice list --limit 5
freshbooks customer list --limit 5

# Test force flag
freshbooks invoice send --help | grep force
freshbooks invoice delete --help | grep force

# Test date filtering (if you have invoices)
freshbooks invoice list --from 2024-01-01 --limit 5
```
**Expected:** All commands work, new options appear in help
**If failing:** Review specific step that failed

---

## Testing Strategy

1. **Unit Test - output.py:**
   - Verify `print_info()` outputs to stderr
   - Verify no changes to existing functions

2. **Integration Test - Commands:**
   - `freshbooks invoice list --limit 5` returns max 5 invoices
   - `freshbooks invoice list --from 2024-01-01 --to 2024-12-31` filters by date
   - `freshbooks invoice send 123 --force` skips prompt
   - `freshbooks invoice delete 123 --force` skips prompt
   - `freshbooks customer list --limit 5` returns max 5 customers
   - `freshbooks customer list --properties id,email` returns only those properties

3. **Retry Test - client.py:**
   - Mock 429 response, verify retry with backoff
   - Mock 503 response, verify retry
   - Mock ConnectionError, verify retry
   - Verify Retry-After header is honored

---

## Success Criteria

- [ ] install.sh exists and is executable
- [ ] print_info() function exists in output.py
- [ ] invoice send uses --force/-F (not --yes/-y)
- [ ] invoice delete uses --force/-F (not --yes/-y)
- [ ] invoice list has --limit/-l option
- [ ] invoice list has --from and --to options
- [ ] customer list has --limit/-l option
- [ ] customer list has --properties/-p option
- [ ] client.py has retry logic with exponential backoff
- [ ] client.py honors Retry-After header
- [ ] client.py handles ConnectionError and Timeout
- [ ] README.md reflects all changes
- [ ] All compliance tests pass (re-run /test-cli-tool freshbooks)

---

## Critical Files for Implementation
- `<cli-tools-root>/freshbooks/freshbooks_cli/client.py` - Add retry logic (largest change)
- `<cli-tools-root>/freshbooks/freshbooks_cli/commands/invoice.py` - Force flags, limit, date filtering
- `<cli-tools-root>/freshbooks/freshbooks_cli/commands/customer.py` - Limit and properties options
- `<cli-tools-root>/freshbooks/freshbooks_cli/output.py` - Add print_info()
- `<cli-tools-root>/freshbooks/install.sh` - Create new file
- `<cli-tools-root>/freshbooks/README.md` - Update documentation
