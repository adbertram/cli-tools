"""Facebook CLI models."""
import re
from typing import List, Optional

from pydantic import Field, field_validator, model_validator

from cli_tools_shared import CLIModel

FACEBOOK_BASE_URL = "https://www.facebook.com"

# A rendered Facebook price: a currency prefix followed by the amount ("$15",
# "CA$1,100.00", "£1,600"). The browser extractors in ``client.py`` are the
# authoritative shape gate -- they match the currency prefix as a Unicode
# currency symbol (``\p{Sc}``) with an optional currency code -- so this pattern
# only has to split an already-validated token into its symbol and amount.
# Python's ``re`` has no ``\p{Sc}``, hence the "leading non-digit run" form.
PRICE_PATTERN = re.compile(r"^(?P<currency>[^\d\s]{1,4}?)\s?(?P<amount>[\d,]+(?:\.\d{2})?)$")


class MarketplaceListing(CLIModel):
    """A Facebook Marketplace listing."""

    item_id: str = Field(frozen=True)
    title: str
    price: Optional[float] = None
    #: The struck-through pre-drop price on a discounted listing. None when the
    #: seller has never lowered the price. Only the detail (``get``) surface
    #: exposes it; the list surface reports the current price only.
    original_price: Optional[float] = None
    #: The currency symbol Facebook rendered for this listing, verbatim ("$",
    #: "CA$"). Facebook prefixes the symbol for listings priced outside the
    #: viewer's currency, so the numeric price alone is ambiguous. None for a
    #: free listing.
    price_currency: Optional[str] = None
    url: str
    location: Optional[str] = None
    description: Optional[str] = None
    availability: Optional[str] = None
    #: Facebook's own per-listing fulfillment model, verbatim. Observed tokens
    #: (live 2026-07-26): IN_PERSON, PUBLIC_MEETUP, DOOR_PICKUP, DOOR_DROPOFF
    #: (all local collection/delivery) and SHIPPING_ONSITE (Facebook-checkout
    #: shipping). Reported raw so a consumer maps them itself and a token
    #: Facebook adds later is never silently dropped.
    #:
    #: None means UNKNOWN -- Facebook did not describe this listing on the
    #: surface that was read. It NEVER means "no shipping offered". `get` fails
    #: loudly instead of returning None; only `list` rows can carry it, and only
    #: for a tile Facebook's own payload never covered.
    delivery_types: Optional[List[str]] = None
    image_urls: Optional[List[str]] = Field(default=None, exclude=True)
    local_images: Optional[List[str]] = None

    @model_validator(mode="before")
    @classmethod
    def derive_price_currency(cls, data):
        """Take the currency symbol from the rendered price string.

        ``price`` arrives as Facebook rendered it ("$15", "CA$75"), and is then
        normalized to a bare float. Capturing the symbol first keeps a CA$75
        listing from being reported as if it were 75 USD.
        """
        if not isinstance(data, dict) or data.get("price_currency"):
            return data
        match = PRICE_PATTERN.match(str(data.get("price") or "").strip())
        if match is None:
            return data
        return {**data, "price_currency": match.group("currency")}

    @field_validator("price", "original_price", mode="before")
    @classmethod
    def normalize_price(cls, v):
        """Convert a rendered price to a float. '$10' -> 10.0, 'Free' -> 0.0."""
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if not isinstance(v, str):
            raise ValueError(f"Price must be a string or number, got {type(v).__name__}.")
        v = v.strip()
        if not v or v.lower() == "unknown":
            return None
        if v.lower() == "free":
            return 0.0
        match = PRICE_PATTERN.match(v)
        if match is None:
            raise ValueError(
                f"Unrecognized Facebook price string: {v!r}. Facebook changed its "
                "price rendering and the CLI parser needs updating."
            )
        return float(match.group("amount").replace(",", ""))

    @field_validator("delivery_types")
    @classmethod
    def reject_empty_delivery_types(cls, v):
        """An empty list would read as 'this listing offers no fulfillment'.

        Facebook always names at least one delivery type for a listing it
        describes, so an empty array means the read is broken, not that the
        seller offers nothing. Unknown stays None.
        """
        if v is not None and len(v) == 0:
            raise ValueError(
                "delivery_types must be None (unknown) or a non-empty list; an empty "
                "list would misreport an unreadable listing as offering no fulfillment."
            )
        return v

    @field_validator("url", mode="before")
    @classmethod
    def make_absolute_url(cls, v):
        """Convert relative URL to absolute."""
        if isinstance(v, str) and v.startswith("/"):
            return f"{FACEBOOK_BASE_URL}{v}"
        return v


class Group(CLIModel):
    """A Facebook Group the user has joined."""

    group_id: str = Field(frozen=True)
    name: str
    url: Optional[str] = None
    member_count: Optional[str] = None


class Comment(CLIModel):
    """A comment on a Facebook Group post."""

    comment_id: Optional[str] = None
    author: str
    text: str
    created_time: Optional[str] = None
    replies: List["Comment"] = Field(default_factory=list)


class GroupPost(CLIModel):
    """A post from a Facebook Group."""

    post_id: str = Field(frozen=True)
    title: Optional[str] = None
    author: Optional[str] = None
    text: Optional[str] = None
    body: Optional[str] = None
    timestamp: Optional[str] = None
    url: Optional[str] = None
    thread_url: Optional[str] = None
    reactions: Optional[int] = None
    comment_count: Optional[int] = None
    comments: Optional[List[Comment]] = None
    image_urls: Optional[List[str]] = None


Comment.model_rebuild()
