"""Nextdoor GraphQL client.

Authentication is browser-based: ``nextdoor auth login`` drives a persistent
Chromium profile and the session lives in that profile (the single source of
truth). Data operations are GraphQL persisted-query POSTs that reuse the live
session cookies fetched from that profile via the shared ``BrowserAuthState``.

Nextdoor routes each persisted query as ``POST {base_url}/<operationName>``
(e.g. ``https://nextdoor.com/api/gql/getMe``); the operation name is part of
the path and the persisted-query hash travels in the request body.
"""

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests

from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.http_session import (
    BrowserAuthState,
    BrowserAuthStateError,
    DEFAULT_REQUESTS_BASE_DELAY,
    DEFAULT_REQUESTS_JITTER,
    DEFAULT_REQUESTS_MAX_DELAY,
    DEFAULT_REQUESTS_MAX_RETRIES,
    RequestsRetryPolicy,
    request_with_retry,
    required_path,
)

from .browser import NextdoorBrowser
from .config import (
    NEXTDOOR_ALLOWED_DOMAINS,
    NEXTDOOR_HOST,
    NEXTDOOR_ORIGIN,
    get_config,
)

# Full GraphQL query documents for each operation, keyed by operation name.
#
# Nextdoor's Automatic Persisted Query (APQ) protocol normally lets a client
# send just a sha256 hash once the server has the matching query text
# registered, falling back to sending the hash *and* the full document when
# the server answers "PersistedQueryNotFound" (see ``_graphql()``). Nextdoor's
# own frontend never sends that fallback in practice: every request captured
# live from it (news feed, For Sale & Free grid, and global search pages) was
# hash-only, and its production JS bundles (searched live, ~7MB across all 11
# loaded chunks) contain zero occurrences of any of these operation names --
# the query text is stripped from the client at build time. That means
# Nextdoor's own internal document text is unrecoverable by design, and a
# hash we merely copied from live traffic would break again the next time
# Nextdoor rotates it with no way to recover.
#
# So this client owns its own documents instead: each one below was authored
# from the exact fields ``normalize_*`` (below) already relies on -- taken
# from real captured response fixtures in ``tests/fixtures/`` -- and verified
# live against Nextdoor's GraphQL schema by executing it end-to-end through
# the authenticated session (introspection is disabled server-side, so
# argument/type names came from the server's own field-validation error
# messages, e.g. "Cannot query field 'x' on type 'Y'. Did you mean to use an
# inline fragment on 'Z'?", not from guessing). See ``PERSISTED_QUERIES``
# below for how each operation's fast-path hash relates to its document here
# (derived-and-primary for the two operations that were actually broken;
# fallback-only, alongside Nextdoor's own still-working hash, for the rest).
#
# Known limitation: ``ClassifiedFeedItem`` intentionally omits
# ``locationGeoTag.location.formattedName`` (and therefore the ``location``
# field stays ``None`` if this fallback ever fires). That field requires a
# ``format: GeoLocationNameFormat!`` enum argument whose legal values could
# not be discovered without introspection (multiple plausible guesses --
# FULL, DEFAULT, STANDARD, FORMATTED, SHORT_NAME, LONG -- were all rejected
# live); every other field ``normalize_classified_detail`` uses is present.
PERSISTED_QUERY_DOCUMENTS = {
    "PersonalizedFeed": """query PersonalizedFeed($mainFeedArgs: MainFeedArgs!) {
  me {
    personalizedFeed(mainFeedArgs: $mainFeedArgs) {
      feedItems {
        feedItemType
        contentId
        ... on FeedItemPost {
          post {
            postType
            subject
            body
            author { displayName }
            createdAt { epochMillis }
            detailLink { href }
            classified { title price currency description }
          }
        }
        ... on FeedItemPromo {
          promo {
            ... on Ad {
              creative { sponsorName { text } }
            }
          }
        }
      }
    }
  }
}""",
    "getMe": """query getMe {
  me {
    user {
      id
      legacyUserId
      secureUserId
      name { shortName displayName }
      gender
      isAvailable
      userSocialGraphData { connectionStatus }
      __typename
    }
  }
}""",
    "dashboardBadges": """query dashboardBadges {
  me {
    shortcuts {
      type
      title
      badges
      __typename
    }
  }
}""",
    # The For Sale & Free grid (https://nextdoor.com/for_sale_and_free/).
    "searchClassifiedV2": """query searchClassifiedV2($classifiedSearchArgs: ClassifiedSearchArgs!) {
  searchClassifiedFeed(classifiedSearchArgs: $classifiedSearchArgs) {
    searchResultView {
      ... on SearchResultGrid {
        searchResultItemsV2 {
          pageInfo { hasNextPage endCursor }
          edges {
            node {
              itemType
              item {
                __typename
                ... on SearchResultGridItem {
                  contentId
                  title { text styles { start length attributes { isStrikethrough } } }
                  subtitle { text }
                  image { image { url } }
                  url
                }
              }
            }
          }
        }
      }
    }
  }
}""",
    # One For Sale & Free listing detail page
    # (https://nextdoor.com/for_sale_and_free/<uuid>/).
    "ClassifiedFeedItem": """query ClassifiedFeedItem($classifiedId: NextdoorID!) {
  classifiedFeedItem(classifiedId: $classifiedId) {
    classified {
      legacyClassifiedId
      title
      price
      originalPrice
      currency
      status
      isSold
      topic { name { singularName } }
      author {
        ... on UserAuthor {
          user { name { displayName } }
        }
      }
      distance { miles }
      createdAt { epochMillis }
      expiresAt { epochMillis }
      photos { url }
      shareText
      description
    }
  }
}""",
    # Nextdoor's real global content search (https://nextdoor.com/search/).
    "search": """query search($excludeFirstSection: Boolean, $mainSearchArgs: MainSearchArgs!) {
  searchFeedV2(excludeFirstSection: $excludeFirstSection, mainSearchArgs: $mainSearchArgs) {
    searchResultView {
      ... on SearchResultGrid {
        type
        searchResultItemsV2 {
          edges {
            node {
              itemType
              item {
                __typename
                ... on SearchResultGridItem {
                  contentId
                  contentType
                  title { text styles { start length attributes { isStrikethrough } } }
                  subtitle { text }
                  url
                }
              }
            }
          }
        }
      }
      ... on SearchResultSection {
        type
        searchResultItems {
          edges {
            node {
              __typename
              contentId
              contentType
              title { text }
              subtitle { text }
              url
            }
          }
        }
      }
    }
  }
}""",
}

# Fast-path persisted-query hashes.
#
# ``PersonalizedFeed`` and ``search`` were the two operations actually broken
# (their old hardcoded hashes were stale -- confirmed via live capture: the
# real production frontend now sends different hashes for both, which is
# exactly what "PersistedQueryNotFound" for every call meant). Their fast
# path is therefore derived from the document THIS CLIENT owns, so it no
# longer depends on matching Nextdoor's internal, frequently-rotating build
# hash for these two at all -- any future rotation is handled entirely by the
# APQ fallback in ``_graphql()`` re-registering the same, unchanging hash.
#
# The other four operations (getMe, dashboardBadges, searchClassifiedV2,
# ClassifiedFeedItem) already work correctly with Nextdoor's own current
# production hash (verified live) and, for getMe/ClassifiedFeedItem, that
# hash's query returns MORE fields than this client's authored document
# below (e.g. getMe's full raw profile; ClassifiedFeedItem's
# ``location.formattedName``). Switching their fast path to the authored
# hash would silently narrow already-working output, so their hardcoded
# hash is kept as primary; the matching entry in ``PERSISTED_QUERY_DOCUMENTS``
# is used only as the APQ fallback if that hash is ever rotated/evicted.
PERSISTED_QUERIES = {
    "PersonalizedFeed": hashlib.sha256(PERSISTED_QUERY_DOCUMENTS["PersonalizedFeed"].encode()).hexdigest(),
    "getMe": "17d16335240791a39640e8cebc220c3f84786668a46245176749d1e5e4eb21e1",
    "dashboardBadges": "f721ff14d106e321b4019f064e130331e5b73c091c3675b55866b3775b5cd738",
    # The For Sale & Free grid (https://nextdoor.com/for_sale_and_free/).
    "searchClassifiedV2": "9b07f9e5d35a3c112fbaf1bfcf34f1d0ff29a89a43c7467d9c8219b63881df9d",
    # One For Sale & Free listing detail page
    # (https://nextdoor.com/for_sale_and_free/<uuid>/).
    "ClassifiedFeedItem": "0d413ce56d2ef7b14155c237ff58fbc34a4e0206fadd2e02d006f145493fd9d6",
    "search": hashlib.sha256(PERSISTED_QUERY_DOCUMENTS["search"].encode()).hexdigest(),
}


# Each normalize function below owns BOTH the record shape it produces and the
# default table column order for that shape. main.py imports these column tuples
# so the display columns can never drift from the record fields. Shapes are
# derived from real captured Nextdoor GraphQL responses.
FEED_COLUMNS = ("id", "type", "title", "price", "created_at", "url")
CLASSIFIED_COLUMNS = ("id", "title", "price", "variant", "subtitle", "url")
SEARCH_COLUMNS = ("id", "section", "type", "title", "url")
NOTIFICATION_COLUMNS = ("id", "label", "badges")

# Maps the CLI sort vocabulary (Source-CLI Sort Standard) to Nextdoor's
# server-side ``PersonalizedFeed`` sort values. This is a GENUINE server-side
# recency sort: the captured feed response advertises these in its own
# ``sortOrderOptions`` and the query accepts the choice via
# ``mainFeedArgs.sortOrder``.
#   newest    -> RECENT_POSTS (chronological, most recent first) — the default
#   relevance -> FOR_YOU      (Nextdoor's algorithmic "For you" feed)
# main.py imports this map so the CLI vocabulary and the server values can never
# drift. ``newest`` is the required default per the sort standard.
FEED_SORT_MAP = {"newest": "RECENT_POSTS", "relevance": "FOR_YOU"}
FEED_DEFAULT_SORT_ORDER = FEED_SORT_MAP["newest"]

# Maps the CLI sort vocabulary to the For Sale & Free grid's server-side sort
# values. These are the exact values the web app sends through
# ``classifiedSearchArgs.filters.sortOrder``, captured from the live page:
#   newest    -> SORT_BY_TIME              ("Newest" in the Sort By menu)
#   relevance -> SORT_BY_DISTANCE_AND_DATE ("Most Relevant" — the site default)
# Both are genuine server-side sorts, not a client-side re-order.
CLASSIFIED_SORT_MAP = {"newest": "SORT_BY_TIME", "relevance": "SORT_BY_DISTANCE_AND_DATE"}
CLASSIFIED_DEFAULT_SORT_ORDER = CLASSIFIED_SORT_MAP["newest"]

# The web app tags its For Sale & Free grid requests with this context; the
# server uses it to select the classifieds ranking pipeline.
CLASSIFIED_TRACKING_CONTEXT = "FSF_GRID"
# ...and its global search requests with this one.
SEARCH_TRACKING_CONTEXT = "GLOBAL_SEARCH_ALL"

# Time zone the feed and listing-detail queries render their relative
# timestamps in. Absolute timestamps in CLI output come from the response's own
# epoch millis, so this only affects Nextdoor's own "9 hr ago" style strings.
NEXTDOOR_TIME_ZONE = "America/Chicago"


def _optional_dict(container: Optional[dict], key: str) -> Optional[dict]:
    """Read a nested object that is allowed to be absent or null.

    Absent/null means "this item does not carry that content" (e.g. a plain
    neighbor post has no ``classified``). A present value of the wrong type is
    a contract violation and fails loudly — no silent coercion.
    """
    if container is None or key not in container or container[key] is None:
        return None
    value = container[key]
    if not isinstance(value, dict):
        raise ClientError(f"Expected '{key}' to be an object, got {type(value).__name__}.")
    return value


def _instant_iso(instant: Optional[dict]) -> Optional[str]:
    """Render a Nextdoor ``Instant`` object as an ISO-8601 UTC timestamp."""
    if instant is None:
        return None
    millis = required_path(instant, ["epochMillis"], str)
    return datetime.fromtimestamp(int(millis) / 1000, tz=timezone.utc).isoformat()


def _post_permalink(post: Optional[dict]) -> Optional[str]:
    """Absolute permalink for a feed post.

    Nextdoor post permalinks are OPAQUE SHORT SLUGS that exist only in the
    response — ``post.detailLink.href`` is ``/p/m_wcBjjgGRwy?view=detail``
    while the feed id is a numeric ``contentId`` such as ``489406804``. The
    slug is therefore never derivable from the id; it must come from the
    payload. The href is site-relative, so it is resolved against the Nextdoor
    origin. Items with no ``detailLink`` (PROMO ad slots) have no permalink,
    which is reported truthfully as None.
    """
    detail_link = _optional_dict(post, "detailLink")
    if detail_link is None:
        return None
    return urljoin(NEXTDOOR_ORIGIN, required_path(detail_link, ["href"], str))


def _promo_sponsor_name(raw: dict) -> Optional[str]:
    """Sponsor name of a PROMO (ad) feed item."""
    promo = _optional_dict(raw, "promo")
    creative = _optional_dict(promo, "creative")
    sponsor = _optional_dict(creative, "sponsorName")
    return sponsor.get("text") if sponsor is not None else None


def _feed_item_title(raw: dict, post: Optional[dict], classified: Optional[dict]) -> Optional[str]:
    """Pull the human-readable title from a heterogeneous feed item.

    The title source is dispatched by the content the item actually carries:
    a For Sale & Free listing that surfaces in the general feed keeps its
    title on ``post.classified.title`` (its ``post.subject`` is an empty
    string), a plain post keeps it on ``post.subject``, and a PROMO ad slot
    only has ``promo.creative.sponsorName.text``. Any other item type has no
    documented title field, so the title is None (truthful — not a masked
    fallback to an unrelated field).
    """
    if classified is not None:
        return classified.get("title")
    if post is not None:
        return post.get("subject")
    if raw.get("feedItemType") == "PROMO":
        return _promo_sponsor_name(raw)
    return None


def _feed_item_body(post: Optional[dict], classified: Optional[dict]) -> Optional[str]:
    """Body text of a feed item, from whichever content the post carries."""
    if classified is not None:
        return classified.get("description")
    if post is not None:
        return post.get("body")
    return None


def normalize_feed_item(raw: dict) -> dict:
    """Map one PersonalizedFeed item to the public CLI record shape.

    Feed items are heterogeneous (POST, PROMO, ...). The stable identity is
    ``contentId`` and the kind is ``feedItemType``; every other field is
    content-specific (see ``_feed_item_title`` / ``_post_permalink``) and is
    None when the item genuinely does not carry it.
    """
    item_type = raw.get("feedItemType")
    post = _optional_dict(raw, "post") if item_type == "POST" else None
    classified = _optional_dict(post, "classified")
    author = _optional_dict(post, "author")
    return {
        "id": raw.get("contentId"),
        "type": item_type,
        "post_type": post.get("postType") if post is not None else None,
        "title": _feed_item_title(raw, post, classified),
        "price": classified.get("price") if classified is not None else None,
        "author": author.get("displayName") if author is not None else None,
        "created_at": _instant_iso(_optional_dict(post, "createdAt")),
        "url": _post_permalink(post),
        "body": _feed_item_body(post, classified),
    }


def _split_priced_title(styled: dict) -> dict:
    """Split a classified grid item's ``StyledText`` title into price + title
    (+ optional variant).

    Nextdoor packs the price display, the listing title, and (for listings
    with a selected variant, e.g. color) a variant line into ONE StyledText
    separated by newlines: ``"$150\\nPokemon Card Tins Collection"`` (no
    variant), ``"$260\\nNew YETI Tundra 45 Hard Cooler\\nColor: Rescue
    Red/Navy/White"`` (variant line). A listing with no price is a single
    line (``"Garage sale"``); a discounted listing renders both prices on the
    price line (``"$175 $250\\nWoods RM59 finishing mower"``) and marks the
    original price with a strikethrough style run. The style runs — not
    currency guesswork — decide which characters are struck through, so the
    split is structural.

    Line roles by count: 1 line = title only (no price); 2 lines = price
    line + title; 3+ lines = price line + title + one or more variant lines
    (joined back with newlines into a single ``variant`` string). Every
    return carries a ``variant`` key so callers never branch on its absence.
    """
    text = required_path(styled, ["text"], str)
    lines = text.split("\n")
    if len(lines) == 1:
        return {"title": lines[0], "price": None, "original_price": None, "variant": None}

    price_line, title = lines[0], lines[1]
    variant_lines = lines[2:]
    struck = set()
    for style in _optional_list(styled, "styles"):
        if not required_path(style, ["attributes", "isStrikethrough"], bool):
            continue
        start = required_path(style, ["start"], int)
        struck.update(range(start, start + required_path(style, ["length"], int)))

    price = "".join(c for i, c in enumerate(price_line) if i not in struck).strip()
    original_price = "".join(c for i, c in enumerate(price_line) if i in struck).strip()
    return {
        "title": title,
        "price": price or None,
        "original_price": original_price or None,
        "variant": "\n".join(variant_lines) or None,
    }


def _result_item_parts(item: dict) -> dict:
    """Decompose a search/classifieds result item's title into title + price.

    ``SearchResultGridItem`` is the For Sale & Free card, and only that node
    packs a price display in front of the listing title, so only it gets the
    price split. Every other search node (``SearchResult``: neighbors,
    businesses, events, posts) carries a plain title, which is used verbatim —
    no price parsing is attempted on content that has no price. Sponsored ad
    slots carry no title at all.
    """
    styled = _optional_dict(item, "title")
    if styled is None:
        return {"title": None, "price": None, "original_price": None, "variant": None}
    if item.get("__typename") == "SearchResultGridItem":
        return _split_priced_title(styled)
    return {
        "title": required_path(styled, ["text"], str),
        "price": None,
        "original_price": None,
        "variant": None,
    }


def normalize_classified_item(raw: dict) -> dict:
    """Map one ``searchClassifiedV2`` edge node to the public CLI record shape.

    The grid is heterogeneous: ``ORGANIC`` nodes are real listings
    (``SearchResultGridItem``) and carry the direct listing URL, while
    sponsored nodes (``CLASSIFIEDS_GAM_ITEM``, ``CLASSIFIEDS_NAMPLUS_ITEM``)
    are ad slots with no listing identity — their listing fields are
    truthfully None, exactly as PROMO rows are in the feed.
    """
    item = required_path(raw, ["item"], dict)
    parts = _result_item_parts(item)
    subtitle = _optional_dict(item, "subtitle")
    image = _optional_dict(_optional_dict(item, "image"), "image")
    return {
        "id": item.get("contentId"),
        "type": raw.get("itemType"),
        "title": parts["title"],
        "price": parts["price"],
        "original_price": parts["original_price"],
        "variant": parts["variant"],
        "subtitle": subtitle.get("text") if subtitle is not None else None,
        "image_url": image.get("url") if image is not None else None,
        "url": item.get("url"),
    }


def normalize_classified_detail(raw: dict) -> dict:
    """Map one ``ClassifiedFeedItem`` classified object to the CLI record shape.

    The detail operation returns the full listing, so this record carries the
    fields the grid card cannot: the raw numeric ``price`` plus its currency,
    the full description, the named category, sale status, expiry, and the
    canonical listing URL Nextdoor itself publishes in ``shareText``.
    """
    author_user = _optional_dict(_optional_dict(raw, "author"), "user")
    author_name = _optional_dict(author_user, "name")
    topic_name = _optional_dict(_optional_dict(raw, "topic"), "name")
    distance = _optional_dict(raw, "distance")
    location = _optional_dict(_optional_dict(raw, "locationGeoTag"), "location")
    return {
        "id": raw.get("legacyClassifiedId"),
        "title": raw.get("title"),
        "price": raw.get("price"),
        "original_price": raw.get("originalPrice"),
        "currency": raw.get("currency"),
        "status": raw.get("status"),
        "is_sold": raw.get("isSold"),
        "category": topic_name.get("singularName") if topic_name is not None else None,
        "seller": author_name.get("displayName") if author_name is not None else None,
        "distance_miles": distance.get("miles") if distance is not None else None,
        "location": location.get("formattedName") if location is not None else None,
        "created_at": _instant_iso(_optional_dict(raw, "createdAt")),
        "expires_at": _instant_iso(_optional_dict(raw, "expiresAt")),
        "photo_urls": [photo.get("url") for photo in _optional_list(raw, "photos")],
        "url": raw.get("shareText"),
        "description": raw.get("description"),
    }


def normalize_search_result(section: Optional[str], raw: dict) -> dict:
    """Map one global-``search`` result node to the public CLI record shape.

    Nextdoor returns two node shapes. The For Sale & Free section wraps its
    classifieds grid node in an ``item`` object (the same
    ``SearchResultGridItem`` payload ``classifieds list`` parses), so those
    rows get the same price/title split as ``classifieds list``. Neighbor,
    business, event and post sections return the ``SearchResult`` payload
    directly. ``section`` is the owning result view's type; ``type`` is the
    item's own ``contentType`` and is None for sponsored ad slots, which carry
    no content identity.

    The wrapper is detected STRUCTURALLY — by the presence of its ``item``
    object — not by ``node.__typename == 'SearchResultItem'``. This client's
    own ``search`` document does not select ``__typename`` on edge nodes, so
    live responses omit it entirely; dispatching on it made every grid row
    read its fields off the wrapper (which has none of them) and come back
    all-null except ``section``. Same contract as
    ``normalize_classified_item``, which always unwraps ``item``.
    """
    item = _optional_dict(raw, "item")
    if item is None:
        item = raw
    parts = _result_item_parts(item)
    subtitle = _optional_dict(item, "subtitle")
    return {
        "id": item.get("contentId"),
        "section": section,
        "type": item.get("contentType"),
        "title": parts["title"],
        "price": parts["price"],
        "subtitle": subtitle.get("text") if subtitle is not None else None,
        "url": item.get("url"),
    }


def normalize_notification(raw: dict) -> dict:
    """Map one dashboard badge/shortcut entry to the public CLI record shape.

    Shortcuts carry a stable ``type`` slug, a display ``title``, and a
    ``badges`` value (null when there are none) — the badges are the point of
    this command.
    """
    return {
        "id": raw.get("type"),
        "label": raw.get("title"),
        "badges": raw.get("badges"),
    }


def _is_login_wall(text: str) -> bool:
    """Detect Nextdoor's logged-out HTML landing/login page in a response body."""
    head = text[:2000].lower()
    return "<!doctype html" in head and ("log in" in head or "/login" in head)


def _optional_list(container: dict, key: str) -> list:
    """Read a list-valued collection that is allowed to be absent or empty.

    Absent means "no results" (a valid empty collection). A present value of
    the wrong type is a contract violation and fails loudly — no silent
    coercion.
    """
    if key not in container or container[key] is None:
        return []
    value = container[key]
    if not isinstance(value, list):
        raise ClientError(f"Expected '{key}' to be a list, got {type(value).__name__}.")
    return value


def _error_message(err) -> str:
    """Render one GraphQL error entry as a human-readable string."""
    if isinstance(err, dict) and isinstance(err.get("message"), str):
        return err["message"]
    return str(err)


def _is_persisted_query_not_found(errors: list) -> bool:
    """True when a GraphQL ``errors`` array is Apollo's ``PersistedQueryNotFound``.

    Confirmed live against Nextdoor: an unregistered/unknown hash answers with
    HTTP 200 and exactly ``{"errors": [{"message": "PersistedQueryNotFound", ...}]}``.
    """
    return any(_error_message(err) == "PersistedQueryNotFound" for err in errors)


def _feed_query_variables(limit: int, sort_order: str) -> dict:
    """Build the ``PersonalizedFeed`` GraphQL variables for one feed page.

    Shared by ``get_feed`` (the real feed request) and
    ``_assert_session_authenticated`` (a cheap ``me``-scoped liveness probe) so
    the query shape lives in exactly one place. ``sort_order`` must already be a
    valid ``FEED_SORT_MAP`` server value; the caller owns that validation.
    """
    return {
        "pagedCommentsMode": "FEED",
        "useEdgesV2": False,
        "includeModerationInfo": False,
        "mainFeedArgs": {
            "pageSize": limit,
            "nextPage": None,
            "supportedFeatures": {
                "rollupTypes": ["CAROUSEL", "LIST", "GRID"],
                "rollupItemTypes": [
                    "IMAGE_CARD",
                    "LIST_CARD",
                    "POST",
                    "PUBLISHER_DISCOVERY",
                    "ONBOARDING_CAROUSEL_CARD",
                    "LOCAL_EVENT_CARD",
                ],
                "numCommentsForNewsPosts": 2,
                "isStickyCommentPreviewEnabled": False,
            },
            "sortOrder": sort_order,
        },
        "timeZone": NEXTDOOR_TIME_ZONE,
    }


class NextdoorClient:
    """Client for the Nextdoor GraphQL API using a browser-captured session."""

    def __init__(
        self,
        config=None,
        max_retries: int = DEFAULT_REQUESTS_MAX_RETRIES,
        base_delay: float = DEFAULT_REQUESTS_BASE_DELAY,
        max_delay: float = DEFAULT_REQUESTS_MAX_DELAY,
        jitter: float = DEFAULT_REQUESTS_JITTER,
    ):
        self.config = config or get_config()
        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            detail = f"Missing credentials: {', '.join(missing)}. " if missing else ""
            raise ClientError(
                f"{detail}No saved Nextdoor browser session. "
                "Run 'nextdoor auth login' to authenticate."
            )
        self.base_url = self.config.base_url
        self._retry_policy = RequestsRetryPolicy(
            max_retries=max_retries,
            base_delay=base_delay,
            max_delay=max_delay,
            jitter=jitter,
        )
        self._session: Optional[requests.Session] = None
        self._browser: Optional[NextdoorBrowser] = None

    # ---- Session / auth ----

    @property
    def browser(self) -> NextdoorBrowser:
        """The BrowserAutomation subclass that owns the persistent session.

        The persistent Chromium profile this browser manages is the single
        source of truth for the authenticated session that ``BrowserAuthState``
        reads its cookies from.
        """
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def _build_session(self) -> requests.Session:
        """Build a requests session carrying the live browser cookies + CSRF."""
        try:
            state = BrowserAuthState.from_config(self.config)
            cookies = state.cookies_for_host(
                NEXTDOOR_HOST,
                allowed_domains=NEXTDOOR_ALLOWED_DOMAINS,
            )
        except BrowserAuthStateError as exc:
            raise ClientError(
                f"Nextdoor browser session is missing or invalid ({exc}). "
                "Run 'nextdoor auth login --force' to refresh."
            ) from exc

        cookie_jar = {c.name: c.value for c in cookies}
        csrf = cookie_jar.get("csrftoken")

        session = requests.Session()
        session.cookies.update(cookie_jar)
        session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": NEXTDOOR_ORIGIN,
                "Referer": f"{NEXTDOOR_ORIGIN}/news_feed/",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            }
        )
        if csrf:
            session.headers["x-csrftoken"] = csrf
        return session

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = self._build_session()
        return self._session

    def close(self):
        if self._session is not None:
            self._session.close()
            self._session = None
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    # ---- GraphQL transport ----

    def _graphql(self, operation: str, variables: Optional[Dict] = None) -> Dict:
        """POST a persisted-query GraphQL operation and return its ``data`` object.

        Nextdoor routes the operation by path: ``{base_url}/<operation>``. This
        sends the fast-path hash-only request first; on a ``PersistedQueryNotFound``
        error (Nextdoor evicts or rotates registered hashes independently of this
        client), it retries exactly once with the full query document from
        ``PERSISTED_QUERY_DOCUMENTS`` included, per the standard Apollo Automatic
        Persisted Query protocol. See the comment above ``PERSISTED_QUERY_DOCUMENTS``
        for why this client owns its own documents instead of Nextdoor's.
        """
        if operation not in PERSISTED_QUERIES:
            raise ClientError(f"Unknown Nextdoor GraphQL operation: {operation}")
        variables = {} if variables is None else variables

        body = self._graphql_post(operation, variables, PERSISTED_QUERIES[operation])
        errors = _optional_list(body, "errors")
        if errors and _is_persisted_query_not_found(errors):
            document = PERSISTED_QUERY_DOCUMENTS.get(operation)
            if document is None:
                raise ClientError(
                    f"Nextdoor rejected the persisted query for {operation} "
                    "(PersistedQueryNotFound) and no fallback query document is "
                    "available for this operation."
                )
            fallback_hash = hashlib.sha256(document.encode()).hexdigest()
            body = self._graphql_post(operation, variables, fallback_hash, query=document)
            errors = _optional_list(body, "errors")

        if errors:
            messages = "; ".join(_error_message(err) for err in errors)
            if any(
                token in messages.lower()
                for token in ("auth", "login", "session", "unauthorized")
            ):
                raise ClientError(
                    f"Nextdoor session rejected the request ({messages}). "
                    "Run 'nextdoor auth login --force' to refresh the session."
                )
            raise ClientError(f"GraphQL error for {operation}: {messages}")

        data = body.get("data")
        if data is None:
            raise ClientError(f"Nextdoor returned no data for {operation}.")

        # Nextdoor answers a structurally-valid persisted query with HTTP 200 and
        # ``data.me == null`` when the session is not authenticated (it does NOT
        # return a 401/403 or a GraphQL error in this case). Treat an explicit
        # null ``me`` as the unauthenticated signal and fail loudly.
        if isinstance(data, dict) and "me" in data and data["me"] is None:
            raise ClientError(
                "Nextdoor session is not authenticated (server returned a null "
                "user). Run 'nextdoor auth login --force' to refresh the session."
            )
        return data

    def _graphql_post(
        self,
        operation: str,
        variables: Dict,
        sha256_hash: str,
        query: Optional[str] = None,
    ) -> Dict:
        """POST one persisted-query GraphQL request and return its parsed JSON body.

        ``query`` is omitted for the normal fast (hash-only) path and included
        only for the APQ fallback retry in ``_graphql()``.
        """
        payload = {
            "operationName": operation,
            "variables": variables,
            "extensions": {
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": sha256_hash,
                }
            },
        }
        if query is not None:
            payload["query"] = query
        url = f"{self.base_url}/{operation}"
        response = self._request("POST", url, json_body=payload)

        if response.status_code in (401, 403) or _is_login_wall(response.text):
            raise ClientError(
                "Nextdoor session is not authenticated (server returned the login "
                "page). Run 'nextdoor auth login --force' to refresh the session."
            )
        if not response.ok:
            raise ClientError(f"HTTP {response.status_code}: {response.text[:300]}")

        try:
            return response.json()
        except ValueError as exc:
            raise ClientError(
                f"Nextdoor returned a non-JSON response for {operation}: {response.text[:200]}"
            ) from exc

    def _request(self, method: str, url: str, json_body: Optional[Dict] = None) -> requests.Response:
        def send() -> requests.Response:
            return self.session.request(method, url, json=json_body)

        try:
            return request_with_retry(send, self._retry_policy)
        except requests.exceptions.RequestException as exc:
            raise ClientError(f"Nextdoor request failed after retries: {exc}") from exc

    # ---- Public operations ----

    @cached
    def get_feed(self, limit: int = 10, sort_order: str = FEED_DEFAULT_SORT_ORDER) -> List[dict]:
        """Return feed items (shape: see ``normalize_feed_item``).

        ``sort_order`` is a Nextdoor server-side feed sort value (one of
        ``FEED_SORT_MAP`` values): ``RECENT_POSTS`` for newest-first
        (chronological) or ``FOR_YOU`` for the algorithmic feed. The value is
        sent to the server via ``mainFeedArgs.sortOrder`` — this is a real
        server-side sort, not a client-side re-order. An unrecognized value
        fails loudly (no silent fallback).
        """
        if sort_order not in FEED_SORT_MAP.values():
            valid = ", ".join(sorted(FEED_SORT_MAP.values()))
            raise ClientError(
                f"Unknown feed sortOrder '{sort_order}'. Valid values: {valid}."
            )
        data = self._graphql("PersonalizedFeed", _feed_query_variables(limit, sort_order))
        feed = required_path(data, ["me", "personalizedFeed"], dict)
        items = _optional_list(feed, "feedItems")
        return [normalize_feed_item(item) for item in items]

    @cached
    def get_me(self) -> dict:
        """Return the current authenticated user object."""
        data = self._graphql("getMe")
        me = required_path(data, ["me"], dict)
        user = me.get("user")
        if not user:
            raise ClientError(
                "Nextdoor returned no user for getMe. The session is likely "
                "logged out. Run 'nextdoor auth login --force'."
            )
        return user

    @cached
    def get_notifications(self) -> List[dict]:
        """Return dashboard badge/shortcut entries (unread counts)."""
        data = self._graphql("dashboardBadges")
        me = required_path(data, ["me"], dict)
        shortcuts = _optional_list(me, "shortcuts")
        return [normalize_notification(item) for item in shortcuts]

    def _assert_session_authenticated(self) -> None:
        """Fail loudly with the standard re-auth message if the session is logged out.

        The search operations query top-level fields that Nextdoor answers with
        HTTP 200 + an empty result even when the session is logged out, so they
        cannot self-detect an expired session. This runs one cheap ``me``-scoped
        probe; ``_graphql`` raises the standard re-auth ``ClientError`` when
        ``data.me`` is null. It is intentionally NOT ``@cached`` so a dead session
        always re-raises.
        """
        self._graphql("PersonalizedFeed", _feed_query_variables(1, FEED_DEFAULT_SORT_ORDER))

    @cached
    def list_classifieds(
        self,
        query: str = "",
        limit: int = 25,
        sort_order: str = CLASSIFIED_DEFAULT_SORT_ORDER,
    ) -> List[dict]:
        """Return For Sale & Free listings (shape: ``normalize_classified_item``).

        This is Nextdoor's dedicated classifieds surface — the same
        ``searchClassifiedV2`` operation the /for_sale_and_free/ grid issues —
        so every organic row carries a real direct listing URL and price.
        ``sort_order`` must be a ``CLASSIFIED_SORT_MAP`` server value; an
        unrecognized value fails loudly (no silent fallback).

        ``query`` is the grid's own keyword box (empty string browses
        everything) and is sent verbatim as ``classifiedSearchArgs.query``. It
        is a RELEVANCE SIGNAL, NOT A FILTER. Verified live: a nonsense token
        ("zzzzznotarealthing") returns zero edges, so the server does receive
        and act on the keyword — but a real word returns its genuine top
        matches followed by unrelated padding, and a word with no local
        inventory returns padding only ("lego" -> "Vintage Secretary Desk").
        Row counts for the same keyword also vary between consecutive calls.
        Callers that need keyword-bearing rows must post-filter the records
        (e.g. ``title``/``subtitle`` contains) — Nextdoor exposes no
        exact-match or relevance-threshold argument on this operation.

        The grid is cursor-paginated at ~20 nodes per page, so pages are
        fetched until ``limit`` records are collected or the server reports no
        next page. All pages of one call share a single ``requestId``, exactly
        as the web app does when a reader scrolls the grid.
        """
        if sort_order not in CLASSIFIED_SORT_MAP.values():
            valid = ", ".join(sorted(CLASSIFIED_SORT_MAP.values()))
            raise ClientError(
                f"Unknown classified sortOrder '{sort_order}'. Valid values: {valid}."
            )

        request_id = str(uuid.uuid4())
        rows: List[dict] = []
        cursor: Optional[str] = None
        while True:
            args = {
                "query": query,
                "requestId": request_id,
                "enableSpellCorrection": False,
                "searchTrackingContext": CLASSIFIED_TRACKING_CONTEXT,
                "filters": {
                    "isBuyForGood": False,
                    "isDiscounted": False,
                    "isFree": False,
                    "sortOrder": sort_order,
                },
            }
            if cursor is not None:
                args["cursor"] = cursor

            data = self._graphql("searchClassifiedV2", {"classifiedSearchArgs": args})
            feed = required_path(data, ["searchClassifiedFeed"], dict)
            views = _optional_list(feed, "searchResultView")
            if not views:
                break

            grid = required_path(views[0], ["searchResultItemsV2"], dict)
            edges = _optional_list(grid, "edges")
            if not edges:
                break
            rows.extend(
                normalize_classified_item(required_path(edge, ["node"], dict))
                for edge in edges
            )

            page_info = required_path(grid, ["pageInfo"], dict)
            if len(rows) >= limit or not page_info.get("hasNextPage"):
                break
            cursor = required_path(page_info, ["endCursor"], str)

        if not rows:
            self._assert_session_authenticated()
        return rows[:limit]

    @cached
    def get_classified(self, classified_id: str) -> dict:
        """Return one For Sale & Free listing by its id.

        ``classified_id`` is the UUID that appears in the listing URL and in
        ``classifieds list`` output. This runs the same ``ClassifiedFeedItem``
        operation the listing detail page issues.
        """
        data = self._graphql(
            "ClassifiedFeedItem",
            {
                "pagedCommentsMode": "DETAILS",
                "useEdgesV2": False,
                "classifiedId": classified_id,
                "timeZone": NEXTDOOR_TIME_ZONE,
            },
        )
        classified = required_path(data, ["classifiedFeedItem", "classified"], dict)
        return normalize_classified_detail(classified)

    @cached
    def search(self, query: str, limit: int = 25) -> List[dict]:
        """Return global search results (shape: ``normalize_search_result``).

        This is Nextdoor's real content search — the ``search`` operation the
        /search/ page issues — which returns one result view per content type
        (For Sale & Free listings, neighbors, events, businesses, posts), each
        with its own direct URL. ``excludeFirstSection`` is False so the
        top-ranked section is included; the web app splits it into a separate
        request purely to render that section sooner.

        Nextdoor answers this operation with HTTP 200 and empty result views
        even when the session is logged out (no ``me`` field, no GraphQL error,
        no login wall), so an empty result is ambiguous. Only in that empty case
        do we run a cheap ``me``-scoped liveness probe, which raises the
        standard re-auth ``ClientError`` on a dead session.

        The operation exposes no paging or sort arguments, so ``limit`` caps
        the flattened result list client-side.
        """
        session_id = str(uuid.uuid4())
        data = self._graphql(
            "search",
            {
                "excludeFirstSection": False,
                "mainSearchArgs": {
                    "query": query,
                    "requestId": str(uuid.uuid4()),
                    "searchSessionId": session_id,
                    "clientContextId": session_id,
                    "enableSpellCorrection": True,
                    "searchTrackingContext": SEARCH_TRACKING_CONTEXT,
                },
            },
        )
        feed = required_path(data, ["searchFeedV2"], dict)

        rows: List[dict] = []
        for view in _optional_list(feed, "searchResultView"):
            section = view.get("type")
            # Grid views (For Sale & Free) hold their edges under
            # ``searchResultItemsV2``; list views use ``searchResultItems``.
            # Each view carries exactly one of the two.
            for container_key in ("searchResultItemsV2", "searchResultItems"):
                container = _optional_dict(view, container_key)
                if container is None:
                    continue
                rows.extend(
                    normalize_search_result(section, required_path(edge, ["node"], dict))
                    for edge in _optional_list(container, "edges")
                )

        if not rows:
            self._assert_session_authenticated()
        return rows[:limit]


_client: Optional[NextdoorClient] = None


def get_client() -> NextdoorClient:
    """Get or create the global Nextdoor client instance."""
    global _client
    if _client is None:
        _client = NextdoorClient()
    return _client
