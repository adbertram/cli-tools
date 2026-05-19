"""Marketplace models for ClickBank CLI.

The ClickBank affiliate marketplace at https://accounts.clickbank.com/marketplace.htm
is a public catalog of products affiliates can promote.  There is no public REST
endpoint for marketplace search; the marketplace SPA talks to a private GraphQL
endpoint at ``POST https://accounts.clickbank.com/graphql`` from inside the
browser.  These models mirror the GraphQL schema for the
``marketplaceSearch`` / ``marketplaceOfferDetails`` operations exactly — every
field name and type is what the live endpoint returns.

Nothing here is invented: every field was observed against the live endpoint
during reverse-engineering.  When ClickBank adds a new field, add it here; do
not silently coerce missing fields with defaults that hide schema drift.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import Field

from .base import CLIModel


class MarketplaceCategory(CLIModel):
    """A top-level marketplace category (e.g. ``Health & Fitness``).

    Returned by the marketplace facets endpoint.  ``count`` is the number of
    products currently listed in the category — this fluctuates daily and
    should not be treated as stable.
    """

    name: str
    count: int


class MarketplaceSubcategory(CLIModel):
    """A subcategory under a parent category (e.g. ``Dietary Supplements``).

    ``count`` is the number of products in this subcategory **scoped to the
    parent category** in the request that produced it — the same subcategory
    name can appear under multiple categories with different counts.
    """

    name: str
    count: int
    category: Optional[str] = None  # parent category name when known


class MarketplaceCategoryTree(CLIModel):
    """A category with its subcategories — the shape ``marketplace categories``
    returns.  Built by issuing one facet query per category, since the API
    only returns the subCategory facet scoped to the current ``category``
    parameter.
    """

    name: str
    count: int
    subcategories: List[MarketplaceSubcategory] = Field(default_factory=list)


class MarketplaceStats(CLIModel):
    """Per-offer marketplace statistics as returned by ``marketplaceSearch``.

    Field names match the live GraphQL response 1:1.  All numeric fields are
    optional because ClickBank omits them for new offers that have not
    accumulated enough data.
    """

    activateDate: Optional[str] = None
    category: Optional[str] = None
    subCategory: Optional[str] = None
    initialDollarsPerSale: Optional[float] = None
    averageDollarsPerSale: Optional[float] = None
    gravity: Optional[float] = None
    totalRebill: Optional[float] = None
    # Locale flags
    de: Optional[bool] = None
    en: Optional[bool] = None
    es: Optional[bool] = None
    fr: Optional[bool] = None
    it: Optional[bool] = None
    pt: Optional[bool] = None
    # Product type flags
    standard: Optional[bool] = None
    physical: Optional[bool] = None
    rebill: Optional[bool] = None  # True when the offer has recurring billing
    upsell: Optional[bool] = None
    standardUrlPresent: Optional[bool] = None
    mobileEnabled: Optional[bool] = None
    whitelistVendor: Optional[bool] = None
    cpaVisible: Optional[bool] = None
    dollarTrial: Optional[bool] = None
    hasAdditionalSiteHoplinks: Optional[bool] = None
    directTracking: Optional[str] = None  # "enabled" | "disabled" | "not_scraped"
    # Performance metrics
    expectedReturnRate: Optional[float] = None
    returnRateSource: Optional[str] = None
    initialEPC: Optional[float] = None
    futureEPC: Optional[float] = None
    averageEPC: Optional[float] = None
    conversionRate: Optional[float] = None
    netEPC: Optional[float] = None
    biGravity: Optional[float] = None
    score: Optional[float] = None
    rank: Optional[int] = None
    sellerVolume: Optional[int] = None


class MarketplaceHit(CLIModel):
    """A single marketplace search result.

    ``site`` is the vendor nickname used as the ``vendor=`` parameter in the
    hoplink URL.  ``hoplink`` is a derived field this CLI computes; it is not
    part of the live GraphQL response.  When the caller supplies an affiliate
    nickname the hoplink is fully formed; otherwise the URL embeds a literal
    ``{affiliate}`` placeholder so the field is still self-documenting.
    """

    site: str  # vendor nickname (uppercase, e.g. "BRAINSONGX")
    title: Optional[str] = None
    description: Optional[str] = None
    favorite: Optional[bool] = None
    url: Optional[str] = None  # vendor sales page
    urlTitle: Optional[str] = None
    urlDescription: Optional[str] = None
    marketplaceStats: Optional[MarketplaceStats] = None
    affiliateToolsUrl: Optional[str] = None  # vendor's affiliate resources page
    affiliateSupportEmail: Optional[str] = None
    skypeName: Optional[str] = None
    telegramName: Optional[str] = None
    offerImageUrl: Optional[str] = None
    # Derived locally by the CLI:
    hoplink: Optional[str] = None
    category: Optional[str] = None  # convenience copy of marketplaceStats.category
    subCategory: Optional[str] = None
    gravity: Optional[float] = None
    averageDollarsPerSale: Optional[float] = None
    initialDollarsPerSale: Optional[float] = None
    rebill: Optional[bool] = None


class MarketplaceSearchResult(CLIModel):
    """Envelope for a marketplace search response."""

    totalHits: int
    offset: int
    hits: List[MarketplaceHit] = Field(default_factory=list)


class MarketplaceRangePoint(CLIModel):
    """A single data point in a historical range (rank / gravity / EPC over time).

    ClickBank returns these as ``{date, value}`` arrays on the offer-details
    endpoint.  ``date`` is an ISO ``YYYY-MM-DD`` string.
    """

    date: str
    value: float


class MarketplaceProduct(CLIModel):
    """Aggregated product view returned by ``marketplace product <vendor>``.

    Combines the search-result snapshot for the vendor with the offer-details
    historical metrics.  This is the shape the affiliate sees when asking
    "tell me everything about <vendor>".
    """

    site: str
    title: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    category: Optional[str] = None
    subCategory: Optional[str] = None
    gravity: Optional[float] = None
    biGravity: Optional[float] = None
    averageDollarsPerSale: Optional[float] = None
    initialDollarsPerSale: Optional[float] = None
    averageEPC: Optional[float] = None
    initialEPC: Optional[float] = None
    conversionRate: Optional[float] = None
    rebill: Optional[bool] = None
    standard: Optional[bool] = None
    physical: Optional[bool] = None
    cpaVisible: Optional[bool] = None
    mobileEnabled: Optional[bool] = None
    activateDate: Optional[str] = None
    rank: Optional[int] = None
    sellerVolume: Optional[int] = None
    expectedReturnRate: Optional[float] = None
    affiliateToolsUrl: Optional[str] = None
    affiliateSupportEmail: Optional[str] = None
    offerImageUrl: Optional[str] = None
    hoplink: Optional[str] = None
    # Historical detail.  ``returnRates``, ``refundRates`` and ``chargebackRates``
    # are NOT scalar floats despite their singular-looking GraphQL field names:
    # ClickBank returns them as ordered arrays of historical rate samples,
    # matching the dates in ``averageEPCRange`` etc.  Do not "fix" the type back
    # to ``float`` -- ClickBank's schema is misleading.
    returnRates: List[float] = Field(default_factory=list)
    refundRates: List[float] = Field(default_factory=list)
    chargebackRates: List[float] = Field(default_factory=list)
    averageEPCRange: List[MarketplaceRangePoint] = Field(default_factory=list)
    rankRange: List[MarketplaceRangePoint] = Field(default_factory=list)
    gravityRange: List[MarketplaceRangePoint] = Field(default_factory=list)


__all__ = [
    "MarketplaceCategory",
    "MarketplaceCategoryTree",
    "MarketplaceHit",
    "MarketplaceProduct",
    "MarketplaceRangePoint",
    "MarketplaceSearchResult",
    "MarketplaceStats",
    "MarketplaceSubcategory",
]
