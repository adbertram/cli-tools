"""Site Explorer models for Ahrefs CLI.

Model Design:
- DomainOverview: Headline Site Explorer metrics for a target domain
  (Domain Rating, estimated organic traffic, ranking organic keywords,
  referring domains, and backlinks).
- TopPage: A single top page by organic traffic (URL + estimated traffic).

These models mirror the CLIModel-based conventions used by the site-audit
models so both command groups serialize identically.
"""
from typing import List, Optional

from .base import CLIModel


class DomainOverview(CLIModel):
    """Site Explorer overview metrics for a domain."""

    domain: str
    domain_rating: Optional[float] = None
    organic_traffic: Optional[int] = None
    organic_keywords: Optional[int] = None
    referring_domains: Optional[int] = None
    backlinks: Optional[int] = None


class TopPage(CLIModel):
    """A single top page by organic traffic."""

    url: str
    traffic: Optional[int] = None
