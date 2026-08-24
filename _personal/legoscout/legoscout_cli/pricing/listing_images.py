#!/usr/bin/env python3
"""Download a listing's photos so set numbers can be read off the box.

Sellers routinely post a set with no set number in the text, but the box front
carries the name, number and piece count in plain sight. Before 2026-07-25 the
pipeline treated those as unidentifiable and left profit null; a Craigslist
listing that said only "Lego set for sale" turned out to be 75380 Mos Espa
Podrace, readable straight off the photo.

This handles the fetch half. The agent then Reads each saved file (vision) and
identifies the sets. It cannot identify sets itself.

    legoscout pricing images --urls "https://img/a.jpg" --urls "https://img/b.jpg"
    legoscout pricing images --url "https://..." --key craigslist|indianapolis|7945147424
    legoscout pricing images --key shopgoodwill|271746980      # pulls url from the ledger

PREFER --urls. Scraping the listing page works on almost nothing: an
unauthenticated fetch returns 403 on Shop The Salvation Army, an Incapsula
challenge on LiveAuctioneers, and a JS shell on Poshmark, Mercari and Depop.
The URLs exist, but only in the crawler's hands -- Shop The Salvation Army's
`search get` returns an `image_urls` array, every eBay search row carries
`image_url`, and ShopGoodwill exposes them through `search get`. So the crawl
records them on the deal and the image pass is handed the list.

--key resolves against the LEDGER, so it works only for a listing already
written. A fresh candidate has no ledger row yet, which is exactly when the
image pass matters most. Use --urls there.

ONE IMAGE CAN HOLD SEVERAL SETS -- a stacked pile or a group shot is common.
Enumerate every distinct box, don't stop at the first.
"""
from .. import paths
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

from PIL import Image

from ..ledger import db as ledger_db

LEDGER = ledger_db.DB_PATH
OUT_ROOT = paths.LISTING_IMAGES_ROOT
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126 Safari/537.36")

# Per-source image discovery. Craigslist and ShopGoodwill expose predictable
# CDN paths; the generic fallback scrapes any plausible image URL.
PATTERNS = [
    ("images.craigslist.org",
     r"https://images\.craigslist\.org/[A-Za-z0-9_\-]+\.jpg", "craigslist"),
    # A photo URL named by a JSON key, with NO file extension. HiBid serves
    # every lot photo as `"fullSizeLocation":"https://cdn.hibid.com/img.axd?
    # id=8373775669&...&sz=MAX&checksum=..."`, and the extension-matching
    # pattern below found only the site logo -- which the sprite filter then
    # dropped, so `--url` on a HiBid lot returned `count: 0` while the page
    # held 12 photos. Keyed on the JSON field name, not on the file name.
    ("fullSizeLocation",
     r'"(?:fullSizeLocation|fullImageLocation)"\s*:\s*"(https://[^"]+)"',
     "json_key"),
    ("", r"https://[^\"'\s]+?\.(?:jpg|jpeg|png|webp)", "generic"),
]

# A saved file needs an extension: the vision pass Reads it, and a file called
# `img.axd_id_8373775669_wid_` is not recognisable as an image. The extension
# comes from the response Content-Type. A generic MIME type requires decoder
# verification of the saved bytes.
EXTENSION_BY_TYPE = {
    "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
    "image/webp": ".webp", "image/gif": ".gif", "image/avif": ".avif",
}
EXTENSION_BY_FORMAT = {
    "JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif",
    "AVIF": ".avif",
}
# Craigslist serves several sizes off one id; prefer the biggest.
CL_SIZES = ["1200x900", "600x450", "300x300"]

# Some CDNs serve a thumbnail and a full-size original off the same image id,
# differing only by a size token in the path -- swapping the token is a
# same-origin URL rewrite, no extra request or auth needed. On 2026-08-04 the
# eBay worker recorded s-l300/s-l140 thumbnails into `image_urls`; the vision
# pass ran against those, and re-inspecting at s-l1600 changed material facts
# on 9 of 15 candidates, including a false Duplo call on ebay|307104753811.
# Poshmark's `m_` (178KB) vs `l_` (483KB) confirmed the same shape 2026-08-05.
_SIZE_REWRITES = [
    (re.compile(r"(i\.ebayimg\.com/images/g/[^/]+/)s-l\d+(\.\w+)"),
     r"\g<1>s-l1600\g<2>"),
    (re.compile(r"(di2ponv0v5otw\.cloudfront\.net/posts/.+/)[sm]_(\w+\.\w+)$"),
     r"\g<1>l_\g<2>"),
]


class FetchError(RuntimeError):
    """curl failed before it returned one complete response contract."""


def normalize_image_url(url):
    """Canonicalize path separators and rewrite known thumbnail CDN paths."""
    url = url.replace("\\", "/")
    for pattern, repl in _SIZE_REWRITES:
        rewritten = pattern.sub(repl, url)
        if rewritten != url:
            return rewritten
    return url


def verified_generic_image_extension(path):
    """Return a supported extension when generic MIME bytes are a valid image."""
    try:
        with Image.open(path) as image:
            image.verify()
            return EXTENSION_BY_FORMAT.get(image.format)
    except (Image.DecompressionBombError, OSError, SyntaxError):
        return None


def fetch(url, dest=None):
    """The page text, or `(http_code, content_type)` when saving to `dest`.

    The Content-Type is what names the saved file's extension. HiBid, K-BID and
    Mercari all serve photos from extensionless CDN paths, so the URL cannot
    say what the bytes are and the response has to.
    """
    cmd = ["curl", "-sS", "-L", "-A", UA, url]
    if dest:
        cmd += ["-o", dest, "-w", "%{http_code} %{content_type}"]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            raise FetchError(
                "curl exited %d for %s: %s"
                % (p.returncode, url, p.stderr.strip()[:300]))
        parts = p.stdout.strip().split(None, 1)
        if not parts:
            raise FetchError(
                "curl returned no HTTP status for %s" % url)
        return parts[0], (parts[1].split(";")[0].strip().lower()
                          if len(parts) > 1 else "")
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise FetchError(
            "curl exited %d for %s: %s"
            % (p.returncode, url, p.stderr.strip()[:300]))
    return p.stdout


def ledger_record(key):
    return ledger_db.get_deal(key)


SGW_CDN = "https://shopgoodwillimages.azureedge.net/production/"


def shopgoodwill_images(item_id):
    """All photos for a ShopGoodwill lot, via the CLI rather than the page."""
    p = subprocess.run(["shopgoodwill", "search", "get", str(item_id)],
                       capture_output=True, text=True)
    if p.returncode != 0:
        return []
    try:
        item = json.loads(p.stdout)
    except ValueError:
        return []

    def find(o, key):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == key:
                    return v
                r = find(v, key)
                if r is not None:
                    return r
        elif isinstance(o, list):
            for v in o:
                r = find(v, key)
                if r is not None:
                    return r
        return None

    raw = find(item, "imageUrlString") or ""
    out = []
    for part in str(raw).split(";"):
        part = normalize_image_url(part.strip())
        if part:
            out.append(SGW_CDN + part)
    return out


def discover(html):
    for marker, pat, kind in PATTERNS:
        if marker and marker not in html:
            continue
        urls = sorted(set(re.findall(pat, html)))
        if not urls:
            continue
        if kind == "json_key":
            # Already the full-size photo, named by the page's own JSON. No
            # size rewriting and no sprite filtering: the key IS the claim
            # that this is the lot's picture.
            return [(u.replace("\\u002F", "/").replace("\\/", "/"), str(n))
                    for n, u in enumerate(urls, 1)], False
        if kind == "craigslist":
            ids = sorted({re.sub(r"_(?:\d+x\d+c?)\.jpg$", "", u).rsplit("/", 1)[-1]
                          for u in urls})
            return [("https://images.craigslist.org/%s_%s.jpg" % (i, s), i)
                    for i in ids for s in CL_SIZES], True
        # skip sprites/icons/logos that are never product photos
        urls = [u for u in urls
                if not re.search(r"(sprite|icon|logo|avatar|badge)", u, re.I)]
        return [(u, str(n)) for n, u in enumerate(urls, 1)], False
    return [], False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--key")
    ap.add_argument("--urls", nargs="+", metavar="URL",
                    help="Image URLs the crawler already captured. Skips the "
                         "listing page entirely -- use this whenever you have "
                         "them, because scraping the page does not work on "
                         "most sources.")
    ap.add_argument("--max", type=int,
                    help="Stop after this many images. Listing-page discovery "
                         "defaults to 12; explicit --urls fetch every URL.")
    a = ap.parse_args()

    url, key = a.url, a.key
    cands, try_sizes = None, False

    # Supplied URLs win outright. The crawler read them through that source's
    # authenticated CLI, and this script cannot re-derive them: an unauthenticated
    # fetch returns 403 on Shop The Salvation Army, an Incapsula challenge on
    # LiveAuctioneers, and a JS shell on Poshmark, Mercari and Depop. Whenever
    # they are in hand, the listing page is not touched at all.
    if a.urls:
        malformed = [u for u in a.urls
                     if not isinstance(u, str) or not u.strip()
                     or any(char.isspace() for char in u)]
        if malformed:
            print("each --urls value must contain one URL with no whitespace; "
                  "repeat --urls for separate values: %r" % malformed[0],
                  file=sys.stderr)
            return 1
        cands = [(u, str(n)) for n, u in enumerate(a.urls, 1)]

    if cands is None and key and not url:
        # --key resolves against the LEDGER, so it only works for a listing
        # already recorded. A fresh candidate is not in the ledger yet -- that
        # is what --urls is for.
        rec = ledger_record(key)
        if not rec:
            print("listing_key not in ledger: %s. A candidate that has not been "
                  "written yet has no ledger row; pass --urls with the image "
                  "URLs the crawl captured." % key, file=sys.stderr)
            return 1
        url = rec.get("direct_url") or rec.get("url")

    if cands is None and not url:
        print("need --urls, --url, or a --key that resolves to one",
              file=sys.stderr)
        return 1

    if key or url:
        slug = re.sub(r"[^A-Za-z0-9]+", "_", key or url)[:70]
    else:
        # --urls with no --key/--url: several appraisers can run this
        # concurrently on different listings. A shared "urls" folder let
        # them overwrite and cross-read each other's photos, so derive a
        # stable per-listing name from the URL set instead.
        digest = hashlib.sha256("\n".join(sorted(a.urls)).encode()).hexdigest()[:16]
        slug = "urls_%s" % digest
    out = os.path.join(OUT_ROOT, slug)
    os.makedirs(out, exist_ok=True)

    if cands is None and key and key.startswith("shopgoodwill|"):
        sgw = shopgoodwill_images(key.split("|", 1)[1])
        if sgw:
            cands = [(u, str(n)) for n, u in enumerate(sgw, 1)]

    # Only fetch the listing page when nothing else produced candidates. This
    # used to run unconditionally, so the ShopGoodwill branch above could hold
    # every image URL and the run would still exit 1 on a blocked page.
    html = ""
    if cands is None:
        try:
            html = fetch(url)
        except FetchError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if not html:
            print("could not fetch %s" % url, file=sys.stderr)
            return 1
        cands, try_sizes = discover(html)
    if not cands:
        # A page with almost no markup is a JS shell, not a page without
        # photos. K-BID serves 82kB with logos only and Mercari 5.7kB of
        # shell; both hold the photos client-side, so scraping can never get
        # them. Say which case this is, because the remedy differs.
        shell = bool(html) and len(html) < 20000
        print("no image URLs found on %s (%s). Pass --urls with the image URLs "
              "the crawl captured through that source's authenticated CLI: an "
              "unauthenticated page fetch returns a JS shell on Poshmark, "
              "Mercari and Depop, logos only on K-BID, 403 on Shop The "
              "Salvation Army and an Incapsula challenge on LiveAuctioneers."
              % (url or "the supplied list",
                 "%d chars, a JS shell" % len(html or "") if shell
                 else "%d chars fetched" % len(html or "")),
              file=sys.stderr)
        return 1

    image_limit = a.max if a.max is not None else (None if a.urls else 12)
    saved, seen, results = [], set(), []
    for u, ident in cands:
        source_url = u
        u = normalize_image_url(u)
        result = {"source_url": source_url, "normalized_url": u}
        if image_limit is not None and len(saved) >= image_limit:
            result.update(status="skipped_limit",
                          error="not fetched because --max=%d" % image_limit)
            results.append(result)
            continue
        if try_sizes and ident in seen:
            result.update(status="skipped_alternate_size",
                          error="a larger image for this photo was saved")
            results.append(result)
            continue
        # The query string is not part of the file name. HiBid's
        # `img.axd?id=8373775669&wid=&rwl=false&...&checksum=N19mquKO` produced
        # a 60-character name of parameters and no extension at all, which the
        # vision pass cannot open.
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_",
                      u.split("?", 1)[0].rsplit("/", 1)[-1])[-40:] or "image"
        dest = os.path.join(out, "%s_%s" % (ident, stem))
        try:
            code, content_type = fetch(u, dest)
        except FetchError as exc:
            if os.path.exists(dest):
                os.remove(dest)
            result.update(status="failed", http_status=None,
                          content_type=None, bytes=0, error=str(exc))
            results.append(result)
            continue
        extension = EXTENSION_BY_TYPE.get(content_type)
        if code == "200" and content_type == "application/octet-stream":
            extension = verified_generic_image_extension(dest)
        byte_count = os.path.getsize(dest) if os.path.exists(dest) else 0
        if code == "200" and extension and byte_count > 8000:
            # The response's OWN Content-Type names the extension. A URL that
            # already ends in the right one is not renamed twice.
            if not dest.lower().endswith(extension):
                final = dest + extension
                os.replace(dest, final)
                dest = final
            saved.append(dest)
            seen.add(ident)
            result.update(status="saved", path=dest)
        elif code == "200" and extension:
            # Keep valid thumbnails out of the vision set without reporting
            # them as download failures. Product-size images can accompany a
            # small duplicate in the same supplied URL list.
            result.update(status="skipped_thumbnail", http_status=code,
                          content_type=content_type, bytes=byte_count,
                          error="image has fewer than 8001 bytes")
            if os.path.exists(dest):
                os.remove(dest)
        else:
            result.update(status="failed", http_status=code,
                          content_type=content_type, bytes=byte_count,
                          error=("need HTTP 200, a supported image Content-Type or "
                                 "verified generic image bytes"))
            if os.path.exists(dest):
                os.remove(dest)
        results.append(result)

    print(json.dumps({"url": url, "listing_key": key, "dir": out,
                      "images": saved, "count": len(saved),
                      "results": results}, indent=2))
    if saved:
        print("\nRead each file above, then identify EVERY distinct LEGO box "
              "visible (one photo can hold several sets).", file=sys.stderr)
        print("Verify each candidate with `bricklink catalog set <no>-1` on NAME "
              "and piece count before pricing -- a box number misread by one "
              "digit resolves to a real but wrong set.", file=sys.stderr)
    return 0 if saved else 1


if __name__ == "__main__":
    sys.exit(main())
