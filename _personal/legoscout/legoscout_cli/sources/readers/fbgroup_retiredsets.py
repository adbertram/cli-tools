#!/usr/bin/env python3
"""Facebook group "Lego sets- Retired And Hard To Find, Buy, For sale And Trade".

Public, 63.1K members, readable without joining (`facebook groups get
250458852075384` on 2026-08-25: privacy public, membership non_member,
posts_readable true). Everything about HOW this group is read lives in
`sources/fbgroup.py`; this module supplies the group id and nothing else.
"""
from __future__ import annotations

from .. import fbgroup

NAMESPACE = "fbgroup-retiredsets"
GROUP_ID = "250458852075384"

PRICE_BASES = fbgroup.PRICE_BASES
PRICE_BASIS_RULE = fbgroup.PRICE_BASIS_RULE
NEEDS_PAGE_READ = fbgroup.NEEDS_PAGE_READ

fetch = fbgroup.fetch_for(NAMESPACE, GROUP_ID)
seller_name = fbgroup.seller_name_for(fetch)
seller_id = fbgroup.seller_id_for(fetch)
auction_end_date = fbgroup.auction_end_date
shipping_estimate = fbgroup.shipping_estimate
