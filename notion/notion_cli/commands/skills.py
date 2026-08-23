"""List, inspect, and download official Notion Skills."""

COMMAND_CREDENTIALS = {
    "list": ["no_auth"],
    "get": ["no_auth"],
    "download": ["no_auth"],
}

from pathlib import Path
from typing import List, Optional

import requests
import typer
from cli_tools_shared.filters import (
    apply_filters,
    apply_limit,
    apply_properties_filter,
    validate_filters,
)

from ..downloads import download_files
from ..output import command, print_json, print_success, print_table


OFFICIAL_SKILLS_PAGE_ID = "28da4445-d271-80c7-af1d-f7d8615723d0"
NOTION_WEB_API = "https://app.notion.com/api/v3"
SKILL_COLUMNS = ["id", "name", "size"]
SKILL_HEADERS = ["ID", "Name", "Size"]

app = typer.Typer(help="List, inspect, and download official Notion Skills")


def _property_text(properties: dict, name: str, block_id: str) -> str:
    value = properties.get(name)
    if not (
        isinstance(value, list)
        and value
        and isinstance(value[0], list)
        and value[0]
        and isinstance(value[0][0], str)
    ):
        raise ValueError(f"Official skills file block {block_id} has invalid {name} metadata")
    return value[0][0]


def _load_official_skills() -> list[dict]:
    """Read skill metadata from Notion's public page without signing files."""
    response = requests.post(
        f"{NOTION_WEB_API}/loadCachedPageChunk",
        json={
            "pageId": OFFICIAL_SKILLS_PAGE_ID,
            "limit": 100,
            "cursor": {"stack": []},
            "chunkNumber": 0,
            "verticalColumns": False,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    try:
        blocks = payload["recordMap"]["block"]
    except (KeyError, TypeError) as exc:
        raise ValueError("Official skills page response is missing recordMap.block") from exc
    if not isinstance(blocks, dict):
        raise ValueError("Official skills page recordMap.block must be an object")

    records = []
    for block_id, entry in blocks.items():
        try:
            block = entry["value"]["value"]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"Official skills block {block_id} has an invalid record shape") from exc
        if block.get("type") != "file":
            continue

        properties = block.get("properties", {})
        name = _property_text(properties, "title", block_id)
        source = _property_text(properties, "source", block_id)
        size = _property_text(properties, "size", block_id)
        parts = source.split(":", 2)
        if (
            not name.endswith(".zip")
            or len(parts) != 3
            or parts[0] != "attachment"
            or not parts[1]
            or parts[2] != name
        ):
            raise ValueError(f"Official skills file block {block_id} is not a valid ZIP attachment")
        records.append(
            {
                "id": block_id,
                "name": name,
                "size": size,
                "attachment_id": parts[1],
                "source_page_id": OFFICIAL_SKILLS_PAGE_ID,
                "_attachment_source": source,
            }
        )

    if not records:
        raise ValueError("Official skills page contains no ZIP file blocks")
    ids = [record["id"] for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("Official skills page contains duplicate file block IDs")
    return records


def _public_skill(record: dict) -> dict:
    return {key: value for key, value in record.items() if not key.startswith("_")}


def _get_official_skill(skill_id: str) -> dict:
    for record in _load_official_skills():
        if record["id"] == skill_id:
            return record
    raise ValueError(f"Official Notion skill not found: {skill_id}")


def _signed_download(record: dict) -> dict:
    response = requests.post(
        f"{NOTION_WEB_API}/getSignedFileUrls",
        json={
            "urls": [
                {
                    "permissionRecord": {"table": "block", "id": record["id"]},
                    "url": record["_attachment_source"],
                }
            ]
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    signed_urls = payload.get("signedUrls") if isinstance(payload, dict) else None
    if not isinstance(signed_urls, list) or len(signed_urls) != 1:
        raise ValueError("Official skill signed URL response must contain exactly one URL")
    return {
        "id": record["id"],
        "name": record["name"],
        "source_type": "notion_web_attachment",
        "url": signed_urls[0],
    }


@app.command("list")
@command
def skills_list(
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum skills to return"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as a table"),
):
    """List official Notion Skills and their stable skill IDs."""
    records = [_public_skill(record) for record in _load_official_skills()]
    if filter:
        validate_filters(filter)
        records = apply_filters(records, filter)
    records = apply_limit(records, limit)
    columns = SKILL_COLUMNS
    headers = SKILL_HEADERS
    if properties:
        records = apply_properties_filter(records, properties)
        columns = [item.strip() for item in properties.split(",") if item.strip()]
        headers = columns
    if table:
        print_table(records, columns, headers)
    else:
        print_json(records)


@app.command("get")
@command
def skills_get(
    skill_id: str = typer.Argument(..., help="Stable skill ID from 'notion skills list'"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as a table"),
):
    """Get one official Notion Skill by its stable skill ID."""
    record = _public_skill(_get_official_skill(skill_id))
    if table:
        print_table(
            [{"field": key, "value": value} for key, value in record.items()],
            ["field", "value"],
            ["Field", "Value"],
        )
    else:
        print_json(record)


@app.command("download")
@command
def skills_download(
    skill_id: str = typer.Argument(..., help="Stable skill ID from 'notion skills list'"),
    output: str = typer.Option(..., "--output", "-o", help="Destination directory"),
    force: bool = typer.Option(False, "--force", "-F", help="Overwrite an existing ZIP file"),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as a table"),
):
    """Download one official Notion Skill by its stable skill ID."""
    record = _get_official_skill(skill_id)
    results = download_files([_signed_download(record)], output, force=force)
    if table:
        print_table(results, ["name", "bytes", "output"], ["Name", "Bytes", "Output"])
    else:
        print_json(results)
    print_success(f"Downloaded official Notion skill to {Path(output)}")
