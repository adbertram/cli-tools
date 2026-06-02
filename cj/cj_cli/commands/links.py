"""``cj links`` subcommand group.

Three commands:

- ``list <advertiser-id>``  -- query CJ's Link Search REST API for the
  advertiser's available creatives (text links, banners, deep links).
  Each row carries a ``click_url`` -- the affiliate tracking URL the
  publisher embeds in their content.

- ``get <link-id>``  -- fetch one creative's full detail.  CJ's API
  has no per-id endpoint; this iterates a page of results.

- ``deeplink <advertiser-id> <destination-url>``  -- offline URL
  generator.  Returns a CJ deep-link tracking URL that resolves to the
  supplied destination.  Requires ``CJ_PUBLISHER_ACCOUNT_ID`` to be
  configured -- this is the per-publisher account id that CJ embeds
  in every tracking URL.  No API call; pure URL construction.
"""

from __future__ import annotations

from typing import List, Optional
from urllib.parse import quote

import typer
from pydantic import BaseModel

from cli_tools_shared.output import handle_error, print_info, print_json, print_table

from ..client import get_client
from ..config import get_config
from ..filter_map import FilterMap  # noqa: F401  compliance: command files reference filter_map


app = typer.Typer(help="Search creatives and generate affiliate tracking URLs", no_args_is_help=True)


# Compliance: each command's credential gate, used by the auth audit tests.
# ``deeplink`` is pure URL construction so it requires no credentials at
# all -- it reads CJ_PUBLISHER_ACCOUNT_ID from the env file but does not
# call any CJ API.
COMMAND_CREDENTIALS = {
    "list": ["personal_access_token"],
    "get": ["personal_access_token"],
    "deeplink": ["no_auth"],
}


def _to_dict(item):
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def _extract_field(item, field: str):
    data = _to_dict(item)
    value = data
    for part in field.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def _extract_fields(items: list, fields: list) -> list:
    return [{field: _extract_field(item, field) for field in fields} for item in items]


# ----------------------------------------------------------------------
# links list
# ----------------------------------------------------------------------


@app.command("list")
def links_list(
    advertiser_id: str = typer.Argument(..., help="CJ advertiser ID to list creatives for"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of records (CJ caps page size at 100)"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Client-side filter (field:op:value)"
    ),
    link_type: Optional[str] = typer.Option(
        None,
        "--type",
        help='Filter by CJ link type (e.g. "Text Link", "Banner", "Click Link")',
    ),
    category: Optional[str] = typer.Option(
        None, "--category", "-c", help="Filter by creative category"
    ),
    keywords: Optional[str] = typer.Option(
        None, "--keywords", "-k", help="Free-text keywords (server-side search)"
    ),
    promotion_type: Optional[str] = typer.Option(
        None, "--promotion-type", help='Filter by promotion type (e.g. "coupon", "sale")'
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include (supports dot-notation)",
    ),
    page: int = typer.Option(1, "--page", help="1-indexed page number"),
):
    """List creatives for an advertiser via CJ's Link Search API.

    The publisher must have a joined relationship with the advertiser
    for CJ to return any links; otherwise the response is empty.

    Examples:
        cj links list 4837117
        cj links list 4837117 --type "Text Link" --limit 5
        cj links list 4837117 --table
        cj links list 4837117 --properties "link_id,link_name,click_url"
    """
    try:
        client = get_client()
        rows = client.search_links(
            advertiser_ids=advertiser_id,
            keywords=keywords,
            link_type=link_type,
            category=category,
            promotion_type=promotion_type,
            page=page,
            limit=limit,
        )

        if filter:
            from ..client import _apply_filters
            rows = _apply_filters(rows, filter)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            rows = _extract_fields(rows, fields)

        if table:
            if not rows:
                print_info(
                    f"No links found for advertiser {advertiser_id}.  Confirm "
                    f"the relationship is 'joined' via "
                    f"`cj relationships get {advertiser_id}`."
                )
                return
            if properties:
                cols = [f.strip() for f in properties.split(",")]
                print_table(rows, cols, cols)
            else:
                print_table(
                    rows,
                    ["link_id", "link_name", "link_type", "click_url"],
                    ["Link ID", "Name", "Type", "Click URL"],
                )
        else:
            print_json(rows)

    except Exception as exc:
        raise typer.Exit(handle_error(exc))


# ----------------------------------------------------------------------
# links get
# ----------------------------------------------------------------------


@app.command("get")
def links_get(
    link_id: str = typer.Argument(..., help="CJ link ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as key/value table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """Get full detail for a single creative by link id.

    CJ's Link Search API has no per-id endpoint -- this iterates a
    page of results client-side.  For better performance when the
    advertiser is known, use ``cj links list <advertiser-id>`` and
    filter by ``link_id`` in the output.

    Examples:
        cj links get 14729571
        cj links get 14729571 --table
    """
    try:
        client = get_client()
        link = client.get_link(link_id)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            data = {f: _extract_field(link, f) for f in fields}
        else:
            data = _to_dict(link)

        if table:
            rows = [{"field": k, "value": v} for k, v in data.items()]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(data)

    except Exception as exc:
        raise typer.Exit(handle_error(exc))


# ----------------------------------------------------------------------
# links deeplink
# ----------------------------------------------------------------------


# CJ deep-link redirector host.  Every CJ tracking URL flows through one
# of the redirector domains; ``www.anrdoezrs.net`` is the canonical
# choice for the publisher-side deep-link generator.  CJ also serves the
# same redirects via ``www.dpbolvw.net`` / ``www.tkqlhce.com`` etc., but
# the format is identical and a publisher's account id is the only
# variable that matters for resolution.
CJ_DEEPLINK_HOST = "https://www.anrdoezrs.net"


def _build_deeplink(publisher_account_id: str, destination_url: str, sid: Optional[str] = None) -> str:
    """Build a CJ deep-link tracking URL.

    Format: ``https://www.anrdoezrs.net/links/<account-id>/type/dlg[/sid/<sid>]/<destination>``

    The destination URL is appended in plain form (CJ's redirector
    parses everything after the last ``/`` of the type segment as the
    destination).  We do NOT percent-encode the destination -- CJ's
    redirector treats an encoded URL as a literal string and the
    resulting redirect 404s.  This matches the format CJ's own Deep
    Link Generator emits.
    """
    base = f"{CJ_DEEPLINK_HOST}/links/{publisher_account_id}/type/dlg"
    if sid:
        # SID (sub-id) is the publisher's tracking tag for reporting.
        # CJ accepts any URL-safe ASCII; quote it defensively.
        base = f"{base}/sid/{quote(sid, safe='')}"
    return f"{base}/{destination_url}"


@app.command("deeplink")
def links_deeplink(
    advertiser_id: str = typer.Argument(..., help="CJ advertiser ID"),
    destination_url: str = typer.Argument(..., help="Destination URL on the advertiser site"),
    sid: Optional[str] = typer.Option(
        None,
        "--sid",
        "-s",
        help='Publisher sub-id (tracking tag for CJ reports, e.g. "blog-post-slug")',
    ),
    verify: bool = typer.Option(
        True,
        "--verify/--no-verify",
        help="Confirm the publisher has a joined relationship with the advertiser before emitting",
    ),
):
    """Generate a CJ deep-link tracking URL.

    The generated URL routes through CJ's redirector
    (``anrdoezrs.net``) and lands on the supplied destination URL on
    the advertiser's site.  Clicks are credited to the publisher
    identified by ``CJ_PUBLISHER_ACCOUNT_ID``.

    Requires ``CJ_PUBLISHER_ACCOUNT_ID`` in the profile env file --
    this is the numeric segment between ``/member/`` and
    ``/publisher/`` in any authenticated members.cj.com URL.

    Examples:
        cj links deeplink 4837117 https://nordvpn.com/torrent
        cj links deeplink 4837117 https://nordvpn.com/torrent --sid blog-vpn-comparison
        cj links deeplink 4837117 https://nordvpn.com/torrent --no-verify  # skip relationship check
    """
    try:
        config = get_config()
        publisher_account_id = config.publisher_account_id

        if verify:
            client = get_client()
            detail = client.get_advertiser(advertiser_id)
            from ..models import RelationshipStatus
            if detail.relationship_status != RelationshipStatus.JOINED:
                raise typer.BadParameter(
                    f"Cannot emit a deep link for advertiser {advertiser_id} "
                    f"({detail.advertiser_name!r}) -- relationship is "
                    f"{detail.relationship_status.value if detail.relationship_status else 'unknown'}, "
                    f"not 'joined'.  Apply first with "
                    f"`cj relationships apply {advertiser_id}` and wait for "
                    f"approval, or pass --no-verify to emit anyway (the URL "
                    f"will redirect but the click will not be credited)."
                )

        click_url = _build_deeplink(publisher_account_id, destination_url, sid=sid)
        print_json({
            "advertiser_id": advertiser_id,
            "destination_url": destination_url,
            "sid": sid,
            "click_url": click_url,
        })

    except Exception as exc:
        raise typer.Exit(handle_error(exc))
