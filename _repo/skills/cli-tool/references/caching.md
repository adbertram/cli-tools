# Browser Automation Caching

Standardized data-level caching for browser automation CLIs. Caches method return values as JSON files so cache hits skip the browser entirely — no launch, no navigation, no scraping.

**Package:** `cli_tools_shared.data_cache` and `cli_tools_shared.cache_commands`

## How It Works

1. Client method decorated with `@cached` is called
2. Decorator checks `CACHE_ENABLED` env var (default: `true`)
3. Generates a deterministic cache key from method name + arguments
4. **Cache hit** (file exists, age < TTL): deserialize and return — method body never executes
5. **Cache miss**: execute method, serialize result, write to `{storage_dir}/cache/{method}_{hash}.json`

Cache files are JSON:
```json
{
  "timestamp": 1772316370.02,
  "data": {
    "__pydantic__": "OrderList",
    "data": { "orders": [], "count": 0 }
  }
}
```

## Integration Steps

### 1. Add `@cached` to read-only client methods

```python
# client.py
from cli_tools_shared.data_cache import cached

class MyClient:
    def __init__(self):
        self.config = get_config()  # REQUIRED: must have .storage_dir

    @cached
    def list_items(self, status: str = "active") -> list[dict]:
        """Expensive browser call — cached."""
        self._ensure_browser()
        self._navigate(f"{BASE_URL}/items?status={status}")
        ...

    @cached
    def get_item(self, item_id: str) -> dict:
        """Single item lookup — cached."""
        ...

    # Do NOT cache write methods
    def create_item(self, data: dict) -> dict:
        ...
```

**Rules:**
- Only cache **read-only** methods (list, get, search)
- Never cache **write** methods (create, update, delete, post)
- Methods **must** have a return type hint (used for cache deserialization)
- `self.config` **must** have a `storage_dir` property (provided by `BaseConfig`)

### 2. Register the `cache` subcommand

```python
# main.py
from cli_tools_shared.cache_commands import create_cache_app
from .config import get_config

app.add_typer(create_cache_app(get_config), name="cache")
```

This gives users `mytool cache clear` to wipe all cached data.

### 3. Add `--no-cache` global flag

```python
# main.py
import os

@app.callback(invoke_without_command=True)
def callback(
    ctx: typer.Context,
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass response cache"),
    version: Optional[bool] = typer.Option(None, "--version", "-v", ...),
):
    if no_cache:
        os.environ["CACHE_ENABLED"] = "false"
    ...
```

### 4. Configure env vars

In `.env.example`:
```bash
# Response cache settings
CACHE_ENABLED=true
CACHE_TTL=3600
```

## Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `CACHE_ENABLED` | `true` | Enable/disable caching. `--no-cache` flag sets to `false` at runtime. |
| `CACHE_TTL` | `3600` | Cache lifetime in seconds. Set lower for frequently changing data. |

## Cache Key Generation

Keys are deterministic hashes from the method name + all arguments:

```
method: list_orders(platform="bricklink", status="paid")
key:    list_orders_a1b2c3d4e5f6g7h8
file:   ~/.local/share/cli-tools/<name>/authentication_profiles/default/cache/list_orders_a1b2c3d4e5f6g7h8.json
```

- Positional args included in order
- Keyword args sorted by key name
- `self` is excluded (decorator intercepts after binding)
- Hash: first 16 chars of SHA256

**Same args = same cache file.** Different args = different cache file.

## Serialization

The decorator handles plain dicts/lists/scalars and Pydantic models automatically:

| Return Type | Serialized As | Deserialized Via |
|-------------|---------------|------------------|
| Pydantic model | `{"__pydantic__": "ModelName", "data": {...}}` | `ModelType.model_validate(data)` |
| `List[Model]` | Array of serialized models | Recursive deserialization |
| Plain dict/list/scalar | Stored as-is | Returned as-is |
| Enum values | `.value` | Returned as raw value |
| Dates | `.isoformat()` | Returned as string |

**Requirement:** Methods must have a return type hint so the decorator knows how to deserialize:

```python
@cached
def get_item(self, item_id: str) -> dict:  # return type hint required
    ...
```

## Cache Storage Layout

```
~/.local/share/cli-tools/<name>/
└── authentication_profiles/
    └── default/
        ├── cache/
        │   ├── list_items_c7932d7e885e9cca.json
        │   ├── get_item_a1b2c3d4e5f6g7h8.json
        │   └── search_x9y8z7w6v5u4t3s2.json
        └── browser-data/
            └── ...
```

Cache files live under the active authentication profile's `cache/` directory inside the tool user profile folder (`~/.local/share/cli-tools/<name>/`).

## Cache Hit Tracking

The module tracks whether the last `@cached` call was a hit:

```python
from cli_tools_shared.data_cache import get_cache_hit, reset_cache_hit

hit = get_cache_hit()  # True (hit), False (miss), None (no cached call yet)
reset_cache_hit()      # Reset after consuming
```

This is informational — used by output formatters if you want to indicate cached data.

## What NOT to Cache

- **Write operations**: create, update, delete, post, mark, resolve
- **Methods with side effects**: anything that changes state on the target site
- **Auth methods**: login, logout, session checks
- **Time-sensitive data**: if staleness would cause incorrect behavior (use a low TTL instead)

## Bypassing Cache

```bash
# Per-execution: global flag
mytool --no-cache items list

# Per-execution: env var
CACHE_ENABLED=false mytool items list

# Permanent: clear all cached data
mytool cache clear

# Change TTL
CACHE_TTL=300 mytool items list
```

## Complete Example

Minimal browser CLI with caching fully wired:

```python
# main.py
import os, typer
from cli_tools_shared.cache_commands import create_cache_app
from .config import get_config

app = typer.Typer(name="mysite")
app.add_typer(create_cache_app(get_config), name="cache")

@app.callback(invoke_without_command=True)
def callback(
    ctx: typer.Context,
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass response cache"),
):
    if no_cache:
        os.environ["CACHE_ENABLED"] = "false"
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()
```

```python
# client.py
from cli_tools_shared.data_cache import cached
from .config import get_config

class MySiteClient:
    def __init__(self):
        self.config = get_config()  # provides storage_dir

    @cached
    def list_items(self, category: str = "all") -> ItemList:
        # Only runs on cache miss
        self._ensure_browser()
        ...

    @cached
    def get_item(self, item_id: str) -> Item:
        ...

    def update_item(self, item_id: str, data: dict) -> Item:
        # NOT cached — write operation
        ...
```
