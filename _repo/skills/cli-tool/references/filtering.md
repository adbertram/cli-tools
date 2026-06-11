# Filtering Architecture

## Core Principle

**Every `list` command MUST support filtering via `--filter`/`-f` parameter.**

| Pattern | Status |
|---------|--------|
| `mycli items list --filter "status:active"` | REQUIRED |
| `mycli items filter --status active` | FORBIDDEN |
| `mycli filter items ...` | FORBIDDEN |

**Why no dedicated filter commands:**
- Consistency: Users learn one pattern
- Composability: Filter syntax works everywhere
- Simplicity: No confusion about list vs filter

---

## Two-Module Architecture

Both modules live in `cli_tools_shared` and are imported directly (no local copies needed).

### cli_tools_shared.filters - Core Filtering

Provides validation and client-side filtering fallback.

```python
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError

# Validate filter syntax
validate_filters(["status:eq:active", "price:gte:100"])

# Apply filters client-side (fallback only)
filtered = apply_filters(items, ["status:eq:active"])
```

**Supported operators:**
| Operator | Meaning | Example |
|----------|---------|---------|
| `eq` | Equals (default) | `status:active` or `status:eq:active` |
| `ne` | Not equals | `status:ne:archived` |
| `gt` | Greater than | `price:gt:100` |
| `gte` | Greater or equal | `price:gte:100` |
| `lt` | Less than | `price:lt:50` |
| `lte` | Less or equal | `price:lte:50` |
| `in` | In list | `status:in:active\|pending` |
| `nin` | Not in list | `status:nin:archived\|deleted` |
| `like` | Contains (case-sensitive) | `name:like:%widget%` |
| `ilike` | Contains (case-insensitive) | `name:ilike:%widget%` |
| `null` | Is null | `deleted_at:null` |
| `notnull` | Is not null | `email:notnull` |

**Comparison rule:** `gt`/`gte`/`lt`/`lte` must compare numeric-looking strings as numbers. API payloads often represent prices as strings, so `price:gt:500` must treat `"1000.00"` as greater than `500`, not as a lexicographic string. Add regression tests in `_repo/cli-tools-shared/tests/test_filters.py` for numeric string comparisons whenever changing comparison behavior.

### cli_tools_shared.filter_map - API Translation

Translates CLI filters to API-specific parameters.

```python
from cli_tools_shared.filter_map import FilterMap

# Create filter map for a resource
items_filter_map = (
    FilterMap()
    .add_argument_mapping('status')  # status='x' -> 'status:eq:x'
    .add_argument_mapping('min_price', 'price', 'gte')  # min_price=10 -> 'price:gte:10'
    .register_api_translator('status', lambda op, val: {'status': val})
    .register_api_translator('price', lambda op, val: {
        'price_min' if op == 'gte' else 'price_max': val
    })
)

# Convert CLI args to filter strings
filters = items_filter_map.args_to_filters(status='active', min_price=100)
# Result: ['status:eq:active', 'price:gte:100']

# Convert filters to API parameters
api_params = items_filter_map.to_api_params(filters)
# Result: {'status': 'active', 'price_min': 100}
```

---

## Implementation Priority (MANDATORY)

```
User requests filtering
        ↓
Does API support this filter?
        ↓
   YES: Server-side ←─── PREFERRED
        ↓
   NO: Client-side ←─── FALLBACK ONLY
```

**Always prefer server-side filtering:**
- Faster (less data transferred)
- Respects pagination
- Handles large datasets

**Only use client-side when:**
- API doesn't support the filter
- Filter is complex/custom
- Testing/development

---

## Complete Implementation Example

### In client.py

```python
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError
from cli_tools_shared.filter_map import FilterMap

# Define filter map for this resource
_items_filter_map = (
    FilterMap()
    .add_argument_mapping('status')
    .add_argument_mapping('min_price', 'price', 'gte')
    .add_argument_mapping('max_price', 'price', 'lte')
    .register_api_translator('status', lambda op, val: {'filter[status]': val})
    .register_api_translator('price', lambda op, val: {
        'filter[price_gte]' if op == 'gte' else 'filter[price_lte]': val
    })
)


def list_items(
    self,
    limit: int = 100,
    filters: Optional[List[str]] = None,
    status: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
) -> List[Dict]:
    """List items with filtering support."""

    # Combine named args into filters
    all_filters = list(filters or [])
    all_filters.extend(_items_filter_map.args_to_filters(
        status=status,
        min_price=min_price,
        max_price=max_price,
    ))

    # Validate all filters
    if all_filters:
        validate_filters(all_filters)

    # Build params
    params = {"limit": limit}

    # Server-side filtering (PREFERRED)
    if all_filters:
        api_params = _items_filter_map.to_api_params(all_filters)
        params.update(api_params)

    # Make request
    response = self._make_request("GET", "/items", params=params)
    items = response.get("items", response)

    # Client-side filtering for unsupported filters (FALLBACK)
    unsupported = [f for f in all_filters if not self._is_api_supported(f)]
    if unsupported:
        items = apply_filters(items, unsupported)

    return items
```

### In main.py or commands/items.py

Fresh scaffolds keep the default `items` command group in `main.py`. If an
existing CLI already split command groups into `commands/<group>.py`, apply the
same pattern there.

```python
@items_app.command("list")  # Or @app.command("list") in a split command module
def list_items(
    table: bool = typer.Option(False, "--table", "-t", help="Table output"),
    limit: int = typer.Option(100, "--limit", "-l", help="Max results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f",
        help="Filter: field:op:value (e.g., status:eq:active, price:gte:100)"),
    # Named shortcuts for common filters
    status: Optional[str] = typer.Option(None, "--status", "-s",
        help="Filter by status"),
    min_price: Optional[float] = typer.Option(None, "--min-price",
        help="Minimum price"),
    max_price: Optional[float] = typer.Option(None, "--max-price",
        help="Maximum price"),
):
    """List items with optional filtering."""
    client = get_client()

    try:
        items = client.list_items(
            limit=limit,
            filters=filter,
            status=status,
            min_price=min_price,
            max_price=max_price,
        )
    except FilterValidationError as e:
        print_error(str(e))
        raise typer.Exit(1)

    if table:
        print_table(items,
            columns=["id", "name", "status", "price"],
            headers=["ID", "Name", "Status", "Price"])
    else:
        print_json(items)
```

---

## Filter Syntax for Users

```bash
# Basic equality (shorthand)
mycli items list --filter "status:active"

# Explicit equality
mycli items list --filter "status:eq:active"

# Comparison
mycli items list --filter "price:gte:100"
mycli items list --filter "created:gt:2024-01-01"

# Multiple filters (AND within, OR between flags)
mycli items list --filter "status:active,price:gte:100"
mycli items list --filter "status:active" --filter "status:pending"

# Other operators
mycli items list --filter "name:like:%widget%"
mycli items list --filter "category:in:electronics|furniture"
mycli items list --filter "deleted_at:null"
```

---

## Research API Filtering

Before implementing, always check:

1. **API documentation** for filter/query parameters
2. **Common patterns:**
   - `?filter=status:active`
   - `?status=active`
   - `?q=search term`
   - OData: `?$filter=status eq 'active'`
   - GraphQL: variables in query

3. **Test actual API calls** to verify behavior

4. **Document** which filters are server-side vs client-side
