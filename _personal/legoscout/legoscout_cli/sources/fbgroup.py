#!/usr/bin/env python3
"""Every LEGO buy/sell/trade Facebook GROUP reads the same way. This is that way.

One registry namespace per group, because a group is a separate inventory pool
with its own membership, its own reachability and its own watermark -- but ONE
implementation, because `facebook groups posts list|get` is a single surface and
33 copies of it would be 33 places for the next Facebook change to be half-fixed.
A namespace module under `readers/` supplies its group id and nothing else.

This is NOT Facebook Marketplace (`readers/facebook.py`). The two surfaces share
a company and nothing else that matters here:

    Marketplace                        a group post
    -----------                        ------------
    one listing per item_id            MANY items in one post, at many prices
    structured `delivery_types`        prose: "Will gladly ship at buyer's expense"
    structured `location_text`         prose: "I'm located in the northwest
                                       suburbs of Chicago"
    `seller_id` + `seller_name`        `author` + `author_id`
    `--sort newest` (creation_time)    no sort option at all
    2,448-listing depth per search     `--limit` hard-capped at 50, no paging

MEASURED 2026-08-25, group 250458852075384, `--limit 15`: the feed came back
2026-08-23, 08-23, 08-25, 08-25, 08-24, 08-25, **08-11**, 08-22, 08-25, 08-25,
08-25, 08-25, 08-25, 08-25. That is Facebook's ranked group feed, not a
chronological one, and there is no option to make it chronological. So the
watermark-bounded crawl in `legoscout-sources` `<incremental_crawl>` cannot be
used on this surface: its documented "No watermark / no recency sort" exception
applies, and `listing_key` de-duplication is what keeps a crawl from re-recording
known inventory. The other two pilot groups happened to come back descending on
the same day, which is exactly why the order can never be RELIED on.
"""
from __future__ import annotations

import re

from . import listing

# The `--limit` ceiling `facebook groups posts list` enforces (verified live
# 2026-08-25: `--limit 51` exits 2 with "51 is not in the range 1<=x<=50").
# There is no paging option behind it, so this is the whole visible window.
POST_WINDOW = 50

# A group post is a fixed ask: nobody bids in a Facebook group, and a group
# publishes no Buy It Now, so only branch (3) of the shared rule can match --
# the same reasoning `readers/facebook.py` records for Marketplace, and the same
# tuple, so `validate.check` rejects any other basis at the write instead of
# letting a run invent one. `unknown` stays legal: it means the item was never
# read, which is a gap rather than a contradiction.
PRICE_BASES = ("static_price",)

PRICE_BASIS_RULE = (
    "A Facebook group sale post is a fixed ask per item: the group runs no "
    "bidding and publishes no separate Buy It Now, so branch (3) of the shared "
    "rule is the ONLY branch that ever matches. Record THIS ITEM's own asking "
    "price -- not the post's first price, and not a total for the post -- in "
    "`static_price` and set price_basis: static_price. Leave current_price and "
    "buy_now_price null. Haggling in a comment or a DM is a message, not a "
    "published price, so it never changes the basis and its amount is never "
    "stored." + " " + listing.PRICE_BASIS_RULE)

# Two fields a group post genuinely does not structure. Both are stated as the
# exact surface to read, per `readers/__init__.py`'s rule that a `NEEDS_PAGE_READ`
# entry must name where the answer lives rather than report a gap.
NEEDS_PAGE_READ = {
    "item_location": (
        "the post BODY (`text`/`body` from `facebook groups posts get "
        "<group_id>/posts/<post_id>`). A group post carries no structured "
        "location field of any kind -- unlike Marketplace, which publishes "
        "`location_text`. Sellers write it in prose and only sometimes: live "
        "2026-08-25 examples are \"I'm located in the northwest suburbs of "
        "Chicago\", \"shipping from 22630\" and \"Athens OH area\". Read the "
        "body, and record a state-qualified location ONLY when the body "
        "actually names one; a bare metro nickname is not an answer. Never "
        "infer a location from the group's name -- \"(U.S.A)\" in a group "
        "title is a membership rule, not a seller's address."),
    "available_fulfillment": (
        "the post BODY (same fetch as item_location). A group post carries no "
        "`delivery_types` equivalent. Live 2026-08-25 prose: \"Will gladly "
        "ship at buyer's expense (must cover postage and PP fees)\", "
        "\"shipping available at your cost (shipping from 22630)\", \"Pickup "
        "will be one of the local police stations\". A post can offer both, "
        "one, or say nothing at all -- and saying nothing is UNREAD, never "
        "\"pickup only\". Read the body; if it does not answer, report the row "
        "unresolved rather than guessing."),
}

# Facebook publishes no auction of any kind inside a group, and no destination
# shipping rate: the seller's own prose ("at buyer's expense") is a policy, not
# a quote. Both are therefore ANSWERED here rather than left unread.
auction_end_date = listing.never_an_auction(
    "a Facebook group buy/sell/trade post is a fixed ask with negotiation by "
    "comment or DM; Facebook runs no bidding inside a group")

shipping_estimate = listing.never_quotes_shipping(
    "a Facebook group post publishes no destination rate. A seller writes a "
    "shipping POLICY in prose (\"at buyer's expense\") and quotes an actual "
    "amount only in a DM after a buyer names a ZIP, so the post itself carries "
    "no rate to record -- the same structural absence as Facebook Marketplace")


# ---------------------------------------------------------------------------
# Keys. ONE LEDGER ROW PER ITEM, so the key needs a per-item sub-key.
# ---------------------------------------------------------------------------

# `<namespace>|<post_id>#<item_key>`. The pipe segment is what
# `listing.lot_id()` already returns for every source, so nothing upstream
# changes; the `#` splits that segment into the post to FETCH and the item
# inside it to record.
#
# Why per item: a group post is not a listing. Live 2026-08-25, post
# 2559186437869269 in group 250458852075384 listed 21 distinct sets from $10 to
# $300, each with its own availability ("pending", "2 available"). Keyed per
# post, those 21 collapse into one ledger row carrying one price and one
# status -- so 20 buyable items are invisible and the one that is stored is
# wrong for most of them.
#
# Why the SET NUMBER is the preferred sub-key: it is the only per-item token in
# the post that survives an edit. Sellers edit these posts constantly, mostly to
# mark items sold, and the edit rewrites the line ("31157 - 3N1 Creator Peacock
# - $15" -> "... - $15 (pending)"). A key derived from the line text would change
# with it and the same item would re-enter the ledger as a new row on the next
# crawl; a key derived from the item's ordinal would shift for every item below
# a deleted line. The set number does neither.
KEY_SEPARATOR = "#"
_ITEM_KEY_MAX = 64
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def item_key(printed_identifier):
    """The sub-key for one item, from the identifier THE POST prints for it.

    Pass the set number when the item's line names one ("31157", "10497-1") --
    that is the stable case and the one to prefer. Pass the item's own printed
    name only when the post names no set number for it ("Yoda Minifigure
    Activity set"); such a key moves if the seller rewords that line, which is
    a known and accepted limit of an unnumbered item, not a reason to invent a
    number for it.

    Raises rather than substituting anything. There is no positional fallback:
    an item this function cannot key is an item to report, not to guess at.
    """
    text = str(printed_identifier).strip().lower()
    key = _SLUG_RE.sub("-", text).strip("-")
    if not key:
        raise listing.Undetermined(
            "%r normalizes to an empty item key, so it identifies nothing -- "
            "key the item by the set number its own line prints"
            % (printed_identifier,))
    if len(key) > _ITEM_KEY_MAX:
        raise listing.Undetermined(
            "item key %r is %d characters (max %d) -- key the item by the set "
            "number its line prints rather than by its whole description. "
            "Truncating instead would silently merge two items into one "
            "ledger row." % (key, len(key), _ITEM_KEY_MAX))
    return key


def build_listing_key(namespace, post_id, printed_identifier):
    """`<namespace>|<post_id>#<item_key>` for ONE item inside one post."""
    post = str(post_id).strip()
    if not post.isdigit():
        raise listing.Undetermined(
            "%r is not a Facebook group post id (the `post_id` field of "
            "`facebook groups posts list`, all digits)" % (post_id,))
    return "%s|%s%s%s" % (namespace, post, KEY_SEPARATOR,
                          item_key(printed_identifier))


def split_key(deal):
    """(post_id, item_key) for a row. Raises on a key that has no item half.

    A key with no `#` is a row keyed per POST, which the 21-set post above is
    the standing argument against. It fails here instead of being read as an
    item, because a reader that quietly accepted it would make the per-item
    contract unenforced everywhere it is not tested.
    """
    segment = listing.lot_id(deal)
    if KEY_SEPARATOR not in segment:
        raise listing.Undetermined(
            "%r carries no %r, so it names a POST rather than an item in it. A "
            "single group post routinely lists 20+ separately priced sets; key "
            "each one `<namespace>|<post_id>%s<item_key>`."
            % (deal.get("listing_key"), KEY_SEPARATOR, KEY_SEPARATOR))
    post, _, item = segment.partition(KEY_SEPARATOR)
    if not post.isdigit() or not item:
        raise listing.Undetermined(
            "%r does not split into a numeric post id and a non-empty item key"
            % (deal.get("listing_key"),))
    return post, item


# ---------------------------------------------------------------------------
# The one fetch, and the two fields it answers.
# ---------------------------------------------------------------------------

def fetch_for(namespace, group_id):
    """This group's `groups posts get` reader, memoized per POST.

    Keyed by (namespace, post_id) -- NOT by the whole listing_key -- so the 21
    items in one post cost ONE CLI call between them rather than 21. That is the
    same per-fetch keying rule `listing.cached` documents; here the fetch unit is
    genuinely the post, not the row.
    """
    def fetch(deal):
        post, _ = split_key(deal)
        return listing.cached(
            (namespace, post),
            lambda: listing.cli(["facebook", "groups", "posts", "get",
                                 "%s/posts/%s" % (group_id, post)]))
    return fetch


def seller_name_for(fetch):
    """`groups posts get` -> `author`, the poster's Facebook display name.

    Deterministic: Facebook names the poster on every group story node
    (`feedback.owning_profile.name`), so this is a field read, not a parse.
    Verified live 2026-08-25 -- "Michael J. Medeiros", "Miles McFadden". A
    display name is not an identity, so join on `seller_id`.
    """
    def seller_name(deal):
        payload = fetch(deal)
        value = listing.dig(payload, "author")
        if value is listing.MISSING or not value:
            raise listing.Undetermined("the post payload carries no author")
        return value, "author=%r" % value
    return seller_name


def seller_id_for(fetch):
    """`groups posts get` -> `author_id`, Facebook's own numeric profile id.

    This surface published no keyed seller identity until 2026-08-25. It does
    now: Facebook has always carried `feedback.owning_profile.id` in the group
    story node (equal to `actors[0].id`) and the `facebook` CLI simply did not
    expose it, so the honest answer to "is one recoverable?" was yes and the fix
    belonged in the CLI, not in a NEEDS_PAGE_READ note here. `author_id` was
    added to `GroupPost` on 2026-08-25 and verified live on all three pilot
    groups -- e.g. Michael J. Medeiros -> 1257760325.

    That id is what makes a per-seller view possible at all across 33 group
    namespaces: the SAME person posts the same inventory into several groups
    (Lyndsey Pare posted twice in one 11-post window of 2318028917 alone), and
    only a numeric id can prove two rows are one seller.
    """
    def seller_id(deal):
        payload = fetch(deal)
        value = listing.dig(payload, "author_id")
        if value is listing.MISSING or not value:
            raise listing.Undetermined(
                "the post payload carries no author_id -- Facebook publishes "
                "it in `feedback.owning_profile.id`, so an absent one means "
                "the CLI read a node shape it does not know; fix the read "
                "rather than storing a name as an identity")
        return value, "author_id=%r" % value
    return seller_id
