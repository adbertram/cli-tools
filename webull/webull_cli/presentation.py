"""JSON error and presentation helpers shared by resource commands."""
import functools
import typer
from cli_tools_shared.filters import apply_filters, apply_properties_filter, validate_filters
from cli_tools_shared.output import print_json, print_table
from .client import WebullError, safe_error

def guard(fn):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except typer.Exit:
            raise
        except Exception as exc:
            error = exc if isinstance(exc, WebullError) else safe_error(exc)
            print_json(error.as_dict())
            raise typer.Exit(1) from None
    return wrapped


def render(body, *, table=False, filters=None, properties=None, limit=None):
    if filters:
        validate_filters(filters)
    if isinstance(body, list):
        rows = apply_filters(body, filters) if filters else body
        rows = rows[:limit] if limit is not None else rows
        if properties:
            rows = apply_properties_filter(rows, properties)
    else:
        if filters or limit is not None:
            raise WebullError("validation", "Filtering and limits require an array response.")
        rows = apply_properties_filter([body], properties) if properties else [body]
    if table:
        columns = list(dict.fromkeys(key for row in rows for key in row))
        print_table(rows, columns, columns)
    else:
        print_json(rows if isinstance(body, list) else rows[0])


