"""Rakuten Advertising entity models.

Rakuten exposes advertiser data via the ``/advertisersearch/1.0`` REST
endpoint which returns XML by default. The client converts the XML body
to dicts before building these models.
"""
from typing import Any, Optional

from pydantic import Field

from .base import CLIModel


class Advertiser(CLIModel):
    """A Rakuten advertiser the publisher can apply to or has joined.

    Returned by GET /advertisersearch/1.0. Rakuten's advertiser-search
    XML uses ``mid`` for the merchant id and ``merchantname`` for the
    display name. This model exposes both plus generic ``id``/``name``
    aliases so downstream tooling (table formatters, get commands) can
    find them by the conventional field names.
    """

    id: Optional[str] = Field(default=None, description="Merchant id (alias for mid)")
    mid: Optional[str] = Field(default=None, description="Merchant id")
    name: Optional[str] = None
    merchantname: Optional[str] = None
    url: Optional[str] = None
    description: Optional[str] = None
    offer: Optional[str] = None
    network: Optional[str] = None
    categories: Optional[str] = None
    applicationStatus: Optional[str] = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "Advertiser":
        known = {
            "id",
            "mid",
            "merchantname",
            "name",
            "url",
            "description",
            "offer",
            "network",
            "categories",
            "applicationStatus",
        }
        kwargs: dict[str, Any] = {}
        extra: dict[str, Any] = {}
        for key, value in data.items():
            if key in known:
                kwargs[key] = value
            else:
                extra[key] = value
        if not kwargs.get("name") and kwargs.get("merchantname"):
            kwargs["name"] = kwargs["merchantname"]
        if not kwargs.get("id") and kwargs.get("mid"):
            kwargs["id"] = kwargs["mid"]
        kwargs["extra"] = extra
        return cls(**kwargs)


def create_advertiser(data: dict) -> Advertiser:
    return Advertiser.from_dict(data)
