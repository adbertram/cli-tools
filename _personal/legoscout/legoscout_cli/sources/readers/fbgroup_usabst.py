#!/usr/bin/env python3
"""Facebook group "THE LEGO BUY/SELL/TRADE PAGE (U.S.A)".

PRIVATE, 13.4K members, readable only because Adam is a member (`facebook groups
get Legosforsale` on 2026-08-25: privacy private, membership member,
posts_readable true, group_id 266584920129216). Losing that membership turns
every read into exit 1 `UNREADABLE_GROUP:` -- which a source worker must record
as BLOCKED, never as zero candidates.

The group id used everywhere is the NUMERIC one. Its vanity slug `Legosforsale`
resolves to the same group and the CLI accepts either, but the numeric id is
what Facebook's own payloads are keyed by and it cannot be re-pointed at another
group the way a slug can.
"""
from __future__ import annotations

from .. import fbgroup

NAMESPACE = "fbgroup-usabst"
GROUP_ID = "266584920129216"

PRICE_BASES = fbgroup.PRICE_BASES
PRICE_BASIS_RULE = fbgroup.PRICE_BASIS_RULE
NEEDS_PAGE_READ = fbgroup.NEEDS_PAGE_READ

fetch = fbgroup.fetch_for(NAMESPACE, GROUP_ID)
seller_name = fbgroup.seller_name_for(fetch)
seller_id = fbgroup.seller_id_for(fetch)
auction_end_date = fbgroup.auction_end_date
shipping_estimate = fbgroup.shipping_estimate
