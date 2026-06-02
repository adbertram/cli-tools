"""Pronunciation dictionary commands for ElevenLabs CLI."""
COMMAND_CREDENTIALS = {
    "list": ["api_key"],
    "get": ["api_key"],
    "create-from-rules": ["api_key"],
    "create-from-file": ["api_key"],
    "update": ["api_key"],
    "set-rules": ["api_key"],
    "add-rules": ["api_key"],
    "remove-rules": ["api_key"],
    "download": ["api_key"],
}

from pathlib import Path
from typing import Any, Dict, List, Optional

import typer
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import handle_error, print_json, print_table

from ..client import get_client
from .common import apply_properties, key_value_rows, properties_columns


app = typer.Typer(help="Manage pronunciation dictionaries", no_args_is_help=True)


def parse_alias_rule(rule: str) -> Dict[str, Any]:
    """Parse an alias rule from string_to_replace=alias."""
    parts = rule.split("=", 1)
    if len(parts) != 2:
        raise ValueError("Alias rules must use string_to_replace=alias")
    string_to_replace = parts[0].strip()
    alias = parts[1].strip()
    if not string_to_replace or not alias:
        raise ValueError("Alias rule string_to_replace and alias cannot be empty")
    return {
        "string_to_replace": string_to_replace,
        "type": "alias",
        "alias": alias,
    }


def parse_phoneme_rule(rule: str) -> Dict[str, Any]:
    """Parse a phoneme rule from string_to_replace|alphabet|phoneme."""
    parts = rule.split("|", 2)
    if len(parts) != 3:
        raise ValueError("Phoneme rules must use string_to_replace|alphabet|phoneme")
    string_to_replace = parts[0].strip()
    alphabet = parts[1].strip()
    phoneme = parts[2].strip()
    if not string_to_replace or not alphabet or not phoneme:
        raise ValueError("Phoneme rule string_to_replace, alphabet, and phoneme cannot be empty")
    if alphabet not in {"ipa", "cmu"}:
        raise ValueError("Phoneme rule alphabet must be ipa or cmu")
    return {
        "string_to_replace": string_to_replace,
        "type": "phoneme",
        "alphabet": alphabet,
        "phoneme": phoneme,
    }


def build_rules(alias_rules: Optional[List[str]], phoneme_rules: Optional[List[str]]) -> List[Dict[str, Any]]:
    """Build the ElevenLabs rules payload from CLI options."""
    rules: List[Dict[str, Any]] = []
    if alias_rules is not None:
        rules.extend(parse_alias_rule(rule) for rule in alias_rules)
    if phoneme_rules is not None:
        rules.extend(parse_phoneme_rule(rule) for rule in phoneme_rules)
    if not rules:
        raise ValueError("At least one --alias-rule or --phoneme-rule is required")
    return rules


def print_item(item, table: bool, properties: Optional[str]):
    """Print a single item as JSON or a key/value table."""
    output = apply_properties([item], properties)[0]
    if table:
        print_table(key_value_rows(output), ["field", "value"], ["Field", "Value"])
    else:
        print_json(output)


@app.command("list")
def pronunciation_dictionaries_list(
    limit: int = typer.Option(30, "--limit", "-l", min=1, max=100, help="Maximum dictionaries to return"),
    cursor: Optional[str] = typer.Option(None, "--cursor", help="Pagination cursor"),
    sort: str = typer.Option("creation_time_unix", "--sort", help="Sort field: creation_time_unix or name"),
    sort_direction: str = typer.Option("DESCENDING", "--sort-direction", help="Sort direction"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)",
    ),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List pronunciation dictionaries."""
    try:
        page = get_client().list_pronunciation_dictionaries(
            page_size=limit,
            sort=sort,
            sort_direction=sort_direction,
            cursor=cursor,
        )
        output = apply_properties(page.pronunciation_dictionaries, properties)
        if filter:
            output = apply_filters(output, filter)
        if table:
            columns = properties_columns(
                properties,
                ["id", "name", "latest_version_id", "latest_version_rules_num", "description"],
            )
            print_table(output, columns, columns)
        elif properties is None:
            print_json(output)
        else:
            print_json(output)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def pronunciation_dictionaries_get(
    pronunciation_dictionary_id: str = typer.Argument(..., help="Pronunciation dictionary ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get pronunciation dictionary metadata and latest rules."""
    try:
        dictionary = get_client().get_pronunciation_dictionary(pronunciation_dictionary_id)
        print_item(dictionary, table, properties)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("create-from-rules")
def pronunciation_dictionaries_create_from_rules(
    name: str = typer.Option(..., "--name", "-n", help="Pronunciation dictionary name"),
    alias_rule: Optional[List[str]] = typer.Option(
        None,
        "--alias-rule",
        help="Alias rule in string_to_replace=alias form. Repeat for multiple rules.",
    ),
    phoneme_rule: Optional[List[str]] = typer.Option(
        None,
        "--phoneme-rule",
        help="Phoneme rule in string_to_replace|alphabet|phoneme form. Repeat for multiple rules.",
    ),
    description: Optional[str] = typer.Option(None, "--description", help="Dictionary description"),
    workspace_access: Optional[str] = typer.Option(None, "--workspace-access", help="admin, editor, commenter, or viewer"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Create a pronunciation dictionary from alias and phoneme rules."""
    try:
        dictionary = get_client().create_pronunciation_dictionary_from_rules(
            name=name,
            rules=build_rules(alias_rule, phoneme_rule),
            description=description,
            workspace_access=workspace_access,
        )
        print_item(dictionary, table, properties)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("create-from-file")
def pronunciation_dictionaries_create_from_file(
    name: str = typer.Option(..., "--name", "-n", help="Pronunciation dictionary name"),
    file: Path = typer.Option(..., "--file", "-f", exists=True, file_okay=True, dir_okay=False, help="PLS file path"),
    description: Optional[str] = typer.Option(None, "--description", help="Dictionary description"),
    workspace_access: Optional[str] = typer.Option(None, "--workspace-access", help="admin, editor, commenter, or viewer"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Create a pronunciation dictionary from a PLS lexicon file."""
    try:
        dictionary = get_client().create_pronunciation_dictionary_from_file(
            name=name,
            file_path=file,
            description=description,
            workspace_access=workspace_access,
        )
        print_item(dictionary, table, properties)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("update")
def pronunciation_dictionaries_update(
    pronunciation_dictionary_id: str = typer.Argument(..., help="Pronunciation dictionary ID"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Pronunciation dictionary name"),
    archived: Optional[bool] = typer.Option(None, "--archived/--not-archived", help="Archive state"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Update pronunciation dictionary metadata without changing its version."""
    try:
        dictionary = get_client().update_pronunciation_dictionary(
            pronunciation_dictionary_id=pronunciation_dictionary_id,
            name=name,
            archived=archived,
        )
        print_item(dictionary, table, properties)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("set-rules")
def pronunciation_dictionaries_set_rules(
    pronunciation_dictionary_id: str = typer.Argument(..., help="Pronunciation dictionary ID"),
    alias_rule: Optional[List[str]] = typer.Option(
        None,
        "--alias-rule",
        help="Alias rule in string_to_replace=alias form. Repeat for multiple rules.",
    ),
    phoneme_rule: Optional[List[str]] = typer.Option(
        None,
        "--phoneme-rule",
        help="Phoneme rule in string_to_replace|alphabet|phoneme form. Repeat for multiple rules.",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Replace all rules in a pronunciation dictionary."""
    try:
        result = get_client().set_pronunciation_dictionary_rules(
            pronunciation_dictionary_id=pronunciation_dictionary_id,
            rules=build_rules(alias_rule, phoneme_rule),
        )
        print_item(result, table, None)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("add-rules")
def pronunciation_dictionaries_add_rules(
    pronunciation_dictionary_id: str = typer.Argument(..., help="Pronunciation dictionary ID"),
    alias_rule: Optional[List[str]] = typer.Option(
        None,
        "--alias-rule",
        help="Alias rule in string_to_replace=alias form. Repeat for multiple rules.",
    ),
    phoneme_rule: Optional[List[str]] = typer.Option(
        None,
        "--phoneme-rule",
        help="Phoneme rule in string_to_replace|alphabet|phoneme form. Repeat for multiple rules.",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Add or replace rules in a pronunciation dictionary."""
    try:
        result = get_client().add_pronunciation_dictionary_rules(
            pronunciation_dictionary_id=pronunciation_dictionary_id,
            rules=build_rules(alias_rule, phoneme_rule),
        )
        print_item(result, table, None)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("remove-rules")
def pronunciation_dictionaries_remove_rules(
    pronunciation_dictionary_id: str = typer.Argument(..., help="Pronunciation dictionary ID"),
    rule_string: List[str] = typer.Option(..., "--rule-string", help="Rule string_to_replace value to remove"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Remove rules from a pronunciation dictionary."""
    try:
        result = get_client().remove_pronunciation_dictionary_rules(
            pronunciation_dictionary_id=pronunciation_dictionary_id,
            rule_strings=rule_string,
        )
        print_item(result, table, None)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("download")
def pronunciation_dictionaries_download(
    pronunciation_dictionary_id: str = typer.Argument(..., help="Pronunciation dictionary ID"),
    version_id: str = typer.Argument(..., help="Pronunciation dictionary version ID"),
    output: Path = typer.Option(..., "--output", "-o", help="Path to write the PLS file"),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as table"),
):
    """Download a pronunciation dictionary version as a PLS file."""
    try:
        result = get_client().download_pronunciation_dictionary(
            pronunciation_dictionary_id=pronunciation_dictionary_id,
            version_id=version_id,
            output_path=output,
        )
        print_item(result, table, None)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
