"""Shared command helpers to eliminate filter/output boilerplate."""
from contextlib import contextmanager
from typing import List, Optional

from cli_tools_shared.filters import apply_filters, apply_properties_filter, apply_limit
from cli_tools_shared.output import print_json, print_table

from .client import get_client


@contextmanager
def client_session():
    """Context manager that provides a FacebookClient and ensures cleanup."""
    client = get_client()
    try:
        yield client
    finally:
        client.close()


def output_single(data: dict, *, table: bool, properties: Optional[str]):
    """Apply properties filter then print a single item as table or JSON."""
    if properties:
        items = apply_properties_filter([data], properties)
        data = items[0] if items else data
    if table:
        columns = list(data.keys())
        print_table([data], columns, columns)
    else:
        print_json(data)


def output_list(
    items: List[dict],
    *,
    table: bool,
    filter: Optional[List[str]],
    properties: Optional[str],
    limit: Optional[int],
    default_columns: List[str],
    default_headers: List[str],
    noun: str,
):
    """Apply filters, limit, properties, then print as table or JSON."""
    if filter:
        items = apply_filters(items, filter)

    items = apply_limit(items, limit)

    if properties:
        items = apply_properties_filter(items, properties)

    if table:
        if not items:
            print(f"No {noun}s found.")
            return
        if properties:
            columns = [f.strip() for f in properties.split(",")]
            print_table(items, columns, columns)
        else:
            print_table(items, default_columns, default_headers)
    else:
        print_json(items)
