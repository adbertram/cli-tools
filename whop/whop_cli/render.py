"""Shared output and client cleanup for participant reads."""
from cli_tools_shared.filters import apply_filters, apply_properties_filter, validate_filters
from cli_tools_shared.output import print_json, print_table
from .client import WhopClient

def read(method,*args,filters=None,**kwargs):
    if filters: validate_filters(filters)
    client=WhopClient()
    try: return getattr(client,method)(*args,**kwargs)
    finally: client.close()

def render(value,table=False,properties=None,filters=None):
    rows=value if isinstance(value,list) else [value]
    if filters:
        validate_filters(filters)
        rows=apply_filters(rows,filters)
    if properties: rows=apply_properties_filter(rows,properties)
    if table:
        columns=properties.split(',') if properties else list(rows[0]) if rows else ['id']
        print_table(rows,columns,columns)
    else: print_json(rows if isinstance(value,list) else rows[0])
