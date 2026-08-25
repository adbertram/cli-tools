#!/usr/bin/env python3
"""ShopGoodwill: one `shopgoodwill search get <lot>` answers every field."""
from __future__ import annotations

from .. import listing
from ...ledger import shipping as se

NAMESPACE = "shopgoodwill"

# Same default as everywhere else, with one exception: the BIN disappears once a
# live bid passes it, so when current_price > buy_now_price the correct basis is
# current_price, not buy_now -- the BIN is stale.
PRICE_BASIS_RULE = listing.PRICE_BASIS_RULE + (
    " ShopGoodwill exception: when current_price > buy_now_price the BIN is "
    "stale, so the basis is current_price.")

NEEDS_PAGE_READ: dict = {}

# `pickupOnly` / `storePickupOnly` say the lot cannot ship; `sellerAllowPickup`
# says collection is also on offer.
_PICKUP = ("pickupOnly", "storePickupOnly", "sellerAllowPickup")
_NO_SHIPPING = ("pickupOnly", "storePickupOnly")
# `shippingPrice` and `defaultShippingPrice` are 0.0 on a pickup-only lot. That
# zero is why free-shipping fiction crept in; neither is ever read.
_UNQUOTED_WHEN = ("pickupOnly", "storePickupOnly", "shippingEstimateUnavailable")


def fetch(deal):
    lot = listing.lot_id(deal)
    return listing.cached((NAMESPACE, lot),
                          lambda: listing.cli(["shopgoodwill", "search", "get", lot]))


def available_fulfillment(deal):
    """`search get` -> `pickupOnly` / `storePickupOnly`, then `sellerAllowPickup`.

    Item 271837154 is the proof this cannot be a per-source assumption:
    ShopGoodwill ships, that lot does not.
    """
    payload = fetch(deal)
    listing.require(payload, "pickupOnly")

    options, evidence = [], []
    pickup = [f for f in _PICKUP if listing.truthy(payload, f)]
    if pickup:
        options.append("local_pickup")
    evidence.append("local_pickup: any_of%s=%s" % (list(_PICKUP), pickup or None))

    blocked = [f for f in _NO_SHIPPING if listing.truthy(payload, f)]
    if not blocked:
        options.append("shipping")
    evidence.append("shipping: none_of%s=%s" % (list(_NO_SHIPPING), blocked or None))

    if not options:
        raise listing.Undetermined(
            "the listing offers neither pickup nor shipping, which no live "
            "listing does -- re-read the page")
    return options, "; ".join(evidence)


def item_location(deal):
    """`search get` -> `pickupStreet` / `pickupCity` / `pickupState` / `pickupZip`.

    Per seller, not per source -- the same search returns Tallahassee FL and
    Detroit MI lots. `pickupCity` is seller-entered free text; store it as
    written.
    """
    payload = fetch(deal)
    listing.require(payload, "pickupCity", "pickupState")
    parts = {}
    for name, path in (("street", "pickupStreet"), ("city", "pickupCity"),
                       ("state", "pickupState"), ("zip", "pickupZip")):
        found = listing.dig(payload, path)
        parts[name] = "" if found is listing.MISSING else str(found).strip()
    text = listing.tidy("{street}, {city}, {state} {zip}".format(**parts))
    listing.require_city_state_zip(text)
    return text, "pickupStreet/City/State/Zip -> %r" % text


def auction_end_date(deal):
    """`search get` -> `endTime`.

    53 live lots once stored the sentinel `not-an-auction` while the source
    returned `isAuction: true` and a real endTime; the END DATE was the broken
    field, not `listing_type`.
    """
    payload = fetch(deal)
    value = listing.dig(payload, "endTime")
    if value is listing.MISSING:
        raise listing.Undetermined("the payload carries no endTime")
    return value, "endTime=%r" % value


def shipping_estimate(deal):
    """`search get` -> `shippingEstimate`, already calculated to 47725.

    `shippingEstimateUnavailable` + `shippingEstimateError` carry the failure
    (commonly `PACKAGE.WEIGHT.INVALID`).
    """
    payload = fetch(deal)
    for flag in _UNQUOTED_WHEN:
        if listing.truthy(payload, flag):
            reason = listing.dig(payload, "shippingEstimateError")
            reason = "" if reason is listing.MISSING else listing.flatten(str(reason))
            return (se.unquoted('"%s": %s' % (flag, reason or "no quote published")),
                    "unquoted because %s is set" % flag)

    shipping = listing.dig(payload, "shippingEstimate.shippingPrice")
    if shipping is listing.MISSING or not isinstance(shipping, (int, float)):
        raise listing.Undetermined(
            "no numeric shipping price at shippingEstimate.shippingPrice (got "
            "%r) -- a missing rate is not a free one" % (shipping,))
    handling = listing.dig(payload, "shippingEstimate.handlingPrice")
    service = listing.dig(payload, "shippingEstimate.serviceDescription")
    estimate = se.quoted(
        shipping_price=shipping,
        handling_price=None if handling is listing.MISSING else handling,
        service=None if service is listing.MISSING else service)
    return estimate, "shipping=%s handling=%s service=%s" % (shipping, handling, service)


def seller_id(deal):
    """`search get` -> `sellerId`, the Goodwill regional member number.

    Stored as TEXT: without the string form, 8 and "8" become two different
    sellers and every per-seller query splits in half.
    """
    payload = fetch(deal)
    value = listing.dig(payload, "sellerId")
    if value is listing.MISSING:
        raise listing.Undetermined("the payload carries no sellerId")
    if value is not None:
        value = str(value)
    return value, "sellerId=%r" % value


def seller_name(deal):
    """`search get` -> `sellerCompanyName`, the region's full legal name.

    The regions are not interchangeable -- seller 376's flat $10.74 shipping and
    seller 8's weight-scaled FedEx produce opposite landed $/lb on the same BIN.
    """
    payload = fetch(deal)
    value = listing.dig(payload, "sellerCompanyName")
    if value is listing.MISSING:
        raise listing.Undetermined("the payload carries no sellerCompanyName")
    return value, "sellerCompanyName=%r" % value
