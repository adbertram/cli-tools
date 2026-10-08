"""Emit full RPC responses, consuming streamed batches lazily."""
import json
import typer
from cli_tools_shared.output import print_json


def print_responses(result, stream=False):
    """Print ordinary JSON or one complete batch per JSONL line."""
    if stream:
        for batch in result:
            typer.echo(json.dumps(batch, ensure_ascii=False, allow_nan=False))
    else:
        print_json(result)
