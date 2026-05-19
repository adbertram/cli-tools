"""Link models for the CJ Link Search API.

Maps the ``<link>`` element returned by
``https://link-search.api.cj.com/v2/link-search``.  See CJ developer
docs.  Like the advertiser model, fields default to ``Optional[str]``
to preserve sentinel values CJ may return ("N/A", empty elements) and
to avoid blind numeric coercion crashing the response (see Bug 1 and
Bug 3 in the advertiser-side parser).
"""

from typing import Optional

from pydantic import Field

from .base import CLIModel


class Link(CLIModel):
    """One creative/link returned by ``cj links list`` and ``cj links get``.

    The ``click_url`` field is the tracking URL the publisher embeds in
    their content -- this is what AffiliateMagic needs to insert into
    blog posts.  ``destination`` is the underlying advertiser URL the
    click resolves to.
    """

    link_id: str = Field(frozen=True)
    advertiser_id: str
    advertiser_name: Optional[str] = None
    link_name: Optional[str] = None
    link_type: Optional[str] = None
    click_url: Optional[str] = None
    destination: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    language: Optional[str] = None
    promotion_type: Optional[str] = None
    promotion_start_date: Optional[str] = None
    promotion_end_date: Optional[str] = None
    relationship_status: Optional[str] = None
    sale_commission: Optional[str] = None
    click_commission: Optional[str] = None
    seven_day_epc: Optional[str] = None
    three_month_epc: Optional[str] = None
    creative_height: Optional[str] = None
    creative_width: Optional[str] = None


def create_link(data: dict) -> Link:
    """Build a :class:`Link` from a parsed link-search row.

    The factory is a thin wrapper that exists to mirror the
    ``create_advertiser`` / ``create_relationship`` pattern and to give
    callers (the parser, the test suite) one place to evolve the
    field-mapping if CJ ever renames an element.
    """
    return Link(
        link_id=str(data["link_id"]),
        advertiser_id=str(data["advertiser_id"]),
        advertiser_name=data.get("advertiser_name"),
        link_name=data.get("link_name"),
        link_type=data.get("link_type"),
        click_url=data.get("click_url"),
        destination=data.get("destination"),
        description=data.get("description"),
        category=data.get("category"),
        language=data.get("language"),
        promotion_type=data.get("promotion_type"),
        promotion_start_date=data.get("promotion_start_date"),
        promotion_end_date=data.get("promotion_end_date"),
        relationship_status=data.get("relationship_status"),
        sale_commission=data.get("sale_commission"),
        click_commission=data.get("click_commission"),
        seven_day_epc=data.get("seven_day_epc"),
        three_month_epc=data.get("three_month_epc"),
        creative_height=data.get("creative_height"),
        creative_width=data.get("creative_width"),
    )
