"""Read and extend the static site's own records: taxonomy terms and posts.

The static site source under ``static-site/src/data`` is the single authority
for both. ``terms.json`` holds the ``categories`` and ``tags`` lists; each post
is one markdown file whose frontmatter carries its slug, title, publish date,
and tag ids.
"""
import json
import re
from datetime import datetime
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from . import client as client_module
from .client import ClientError, _atomic_write_bytes

TAXONOMIES = ("categories", "tags")
TERM_FIELDS = ["id", "name", "slug", "count"]
SPONSORED_TAG_NAME = "Sponsored"


def _terms_path():
    return client_module.STATIC_SITE_ROOT / "src" / "data" / "terms.json"


def _load_terms_document() -> Dict[str, List[Dict[str, Any]]]:
    path = _terms_path()
    if not path.is_file():
        raise ClientError(f"Static site terms file is missing: {path}")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ClientError(f"Static site terms file is not a JSON object: {path}")
    for taxonomy in TAXONOMIES:
        if not isinstance(document.get(taxonomy), list):
            raise ClientError(f"Static site terms file has no {taxonomy} list: {path}")
    return document


def list_terms(taxonomy: str) -> List[Dict[str, Any]]:
    """Return every term in one taxonomy, in file order."""
    return _load_terms_document()[taxonomy]


def get_term(taxonomy: str, term_id: int) -> Dict[str, Any]:
    """Return the term with this id, or fail."""
    for term in list_terms(taxonomy):
        if term["id"] == term_id:
            return term
    raise ClientError(f"No {taxonomy} term has id {term_id}")


def term_slug(name: str) -> str:
    """Derive a term slug the way the existing entries are derived."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug:
        raise ClientError(f"Could not derive a slug from term name {name!r}")
    return slug


def create_term(taxonomy: str, name: str) -> Dict[str, Any]:
    """Append one term with the next free id and persist terms.json."""
    name = name.strip()
    if not name:
        raise ClientError("Term name must not be empty")
    document = _load_terms_document()
    terms = document[taxonomy]
    for term in terms:
        if term["name"].casefold() == name.casefold():
            raise ClientError(
                f"{taxonomy} already has a term named {term['name']!r} (id {term['id']})"
            )
    slug = term_slug(name)
    for term in terms:
        if term["slug"] == slug:
            raise ClientError(
                f"{taxonomy} already has slug {slug!r} (term {term['name']!r}, id {term['id']})"
            )
    # Term ids are unique across both taxonomies, so the next free id is past
    # the highest id in either list.
    next_id = max(term["id"] for group in TAXONOMIES for term in document[group]) + 1
    created = {"id": next_id, "name": name, "slug": slug, "count": 0}
    terms.append(created)
    terms.sort(key=lambda term: term["name"].casefold())
    _atomic_write_bytes(
        _terms_path(),
        (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
    )
    return created


def list_posts() -> List[Dict[str, Any]]:
    """Return slug, title, publish instant, and tag ids for every corpus post."""
    post_root = client_module.STATIC_SITE_ROOT / "src" / "data" / "posts"
    if not post_root.is_dir():
        raise ClientError(f"Static site post corpus is missing: {post_root}")
    site_zone = ZoneInfo(client_module.STATIC_SITE_TIME_ZONE)
    posts = []
    for path in sorted(post_root.glob("*.md")):
        pieces = path.read_text(encoding="utf-8").split("---", 2)
        if len(pieces) != 3 or pieces[0].strip():
            raise ClientError(f"Static post has invalid frontmatter: {path}")
        fields = dict(
            line.split(": ", 1) for line in pieces[1].strip("\n").splitlines() if ": " in line
        )
        published = datetime.fromisoformat(fields["pubDate"].strip())
        if published.tzinfo is None:
            published = published.replace(tzinfo=site_zone)
        posts.append(
            {
                "slug": json.loads(fields["slug"]),
                "title": json.loads(fields["title"]),
                "published": published,
                "tag_ids": json.loads(fields["tagIds"]),
            }
        )
    return posts
