"""Presentation shared by dictionary-backed Cloudflare command groups."""
from cli_tools_shared.filters import apply_properties_filter
from cli_tools_shared.output import print_output


def print_records(value, table, properties=None, default_columns=("id", "name")):
    rows = value if isinstance(value, list) else [value]
    selected = [field.strip() for field in properties.split(",") if field.strip()] if properties else []
    if selected:
        rows = apply_properties_filter(rows, ",".join(selected))
    columns = selected or list(default_columns)
    print_output(rows if isinstance(value, list) else rows[0], table=table, columns=columns, headers=columns)
