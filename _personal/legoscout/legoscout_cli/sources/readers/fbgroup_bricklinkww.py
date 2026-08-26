#!/usr/bin/env python3
"""Facebook group "BrickLink Worldwide Buyers and Sellers".

Public, 38.9K members, Adam is a member (`facebook groups get 2318028917` on
2026-08-25: privacy public, membership member, posts_readable true). Everything
about HOW this group is read lives in `sources/fbgroup.py`; this module supplies
the group id and nothing else.

Worldwide by name and in fact -- a live 2026-08-25 window carried sellers posting
from outside the US. Landed cost to ZIP 47725 is the gate, not the group.
"""
from __future__ import annotations

from .. import fbgroup

NAMESPACE = "fbgroup-bricklinkww"
GROUP_ID = "2318028917"

PRICE_BASES = fbgroup.PRICE_BASES
PRICE_BASIS_RULE = fbgroup.PRICE_BASIS_RULE
NEEDS_PAGE_READ = fbgroup.NEEDS_PAGE_READ

fetch = fbgroup.fetch_for(NAMESPACE, GROUP_ID)
seller_name = fbgroup.seller_name_for(fetch)
seller_id = fbgroup.seller_id_for(fetch)
auction_end_date = fbgroup.auction_end_date
shipping_estimate = fbgroup.shipping_estimate
