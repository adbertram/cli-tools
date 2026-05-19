"""Live ad scanner for ATA Blog posts.

Uses PlaywrightService (non-persistent) + Google Publisher Tag API to observe
which advertiser domains render on a live post URL over N reloads.
Live-only. No persistence.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from cli_tools_shared.browser import PlaywrightServiceError

# Data-driven defaults -- single source of truth.
# ONE budget knob: per_check_timeout. No hidden ceilings.
SCANNER_DEFAULTS: Dict[str, Any] = {
    "checks": 3,                 # reloads per scan
    "interval": 5,               # seconds between reloads
    "per_check_timeout": 30,     # max seconds waiting for ads per check
    "poll_ms": 500,              # polling cadence
    "stable_polls": 2,           # N consecutive equal slot counts => stable
    "min_initial_wait_s": 6,     # give ads time to render before accepting "stable at zero"
    "warm_scroll_count": 8,      # scrolls during warm-page phase
    "warm_scroll_delay_s": 0.8,  # seconds between scrolls
    "iframe_id_prefix": "google_ads_iframe_",
    "session": "ata-blog-ads-scan",
}

_CAPTURE_INIT_JS = r"""
// Pre-page-load hook: intercepts `window.pbjs` at definition time and registers
// Prebid event listeners that accumulate EVERY bid response -- not just winners.
// Runs before any page script via context.add_init_script().
(() => {
  window.__atacap = {bidResponses: [], wonKeys: new Set(), noBids: [],
                     timeouts: [], auctionEnds: []};
  Object.defineProperty(window, 'pbjs', {
    configurable: true,
    set(v) {
      Object.defineProperty(window, 'pbjs', {value: v, configurable: true, writable: true, enumerable: true});
      try {
        v.que = v.que || [];
        v.que.push(function() {
          try {
            v.onEvent && v.onEvent('bidResponse', b => {
              window.__atacap.bidResponses.push({
                bidder: b.bidder || null,
                adUnit: b.adUnitCode || null,
                cpm: typeof b.cpm === 'number' ? b.cpm : null,
                currency: b.currency || null,
                creativeId: b.creativeId != null ? String(b.creativeId) : null,
                source: b.source || null,
                domains: (b.meta && b.meta.advertiserDomains) || null,
                auctionId: b.auctionId || null,
                requestId: b.requestId || null,
              });
            });
            v.onEvent && v.onEvent('bidWon', b => {
              // Mark the corresponding bidResponse as a winner by (bidder, creativeId, cpm).
              window.__atacap.wonKeys.add(
                [b.bidder, b.creativeId, b.cpm, b.adUnitCode].join('|')
              );
            });
            v.onEvent && v.onEvent('noBid', b => {
              window.__atacap.noBids.push({bidder: b.bidder || null, adUnit: b.adUnitCode || null});
            });
            v.onEvent && v.onEvent('bidTimeout', b => {
              window.__atacap.timeouts.push({bidder: b.bidder || null, adUnit: b.adUnitCode || null});
            });
            v.onEvent && v.onEvent('auctionEnd', a => {
              window.__atacap.auctionEnds.push({
                auctionId: a.auctionId,
                requested: (a.bidderRequests || []).length,
              });
            });
          } catch (e) { window.__atacap.hookErr = String(e); }
        });
      } catch (e) { window.__atacap.setupErr = String(e); }
    },
    get() { return undefined; },
  });
})();
"""


class StealthBrowser:
    """Thin wrapper around sync_playwright + playwright-stealth.

    Exposes the subset of PlaywrightService's API that scan_pages needs:
    browser_open(url), page_goto(url), reload(), evaluate(js, arg).

    Stealth is REQUIRED -- AdThrive/Raptive refuses to load ads in a vanilla
    headless Playwright session. Without stealth the scanner returns empty
    results on any Raptive-managed publisher (which includes ATA).

    Also installs a Prebid bid-capture hook via context.add_init_script() so
    we capture EVERY bid response (not just the final winners via
    getAllWinningBids()).
    """

    def __init__(self, session: str = "ata-blog-ads-scan", timeout: int = 30,
                 headed: bool = False, user_agent: Optional[str] = None):
        self.session = session
        self.timeout = timeout
        self.headed = headed
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        from playwright_stealth import Stealth
        try:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(
                headless=not self.headed,
                args=["--disable-blink-features=AutomationControlled"],
            )
            self._context = self._browser.new_context(
                viewport={"width": 1280, "height": 800},
                locale="en-US",
                timezone_id="America/New_York",
                user_agent=self.user_agent,
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            Stealth().apply_stealth_sync(self._context)
            self._context.add_init_script(_CAPTURE_INIT_JS)
        except Exception as e:
            self._cleanup()
            raise PlaywrightServiceError(f"Failed to start stealth browser: {e}") from e
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._cleanup()
        return False

    def _cleanup(self):
        for obj, name in ((self._page, "_page"), (self._context, "_context"),
                          (self._browser, "_browser"), (self._pw, "_pw")):
            if obj is None:
                continue
            try:
                if name == "_pw":
                    obj.stop()
                else:
                    obj.close()
            except Exception:
                pass
            setattr(self, name, None)

    def browser_open(self, url: str, persistent: bool = False, headed: bool = False):
        """Open the first URL. `persistent`/`headed` kept for interface compatibility
        (StealthBrowser uses its own __init__ config)."""
        if self._page is None:
            if self._context is None:
                raise PlaywrightServiceError("StealthBrowser not entered as context manager")
            self._page = self._context.new_page()
        try:
            self._page.goto(url, timeout=self.timeout * 1000)
        except Exception as e:
            raise PlaywrightServiceError(f"Failed to navigate to {url}: {e}") from e

    def page_goto(self, url: str):
        if self._page is None:
            raise PlaywrightServiceError("no active page; call browser_open first")
        try:
            self._page.goto(url, timeout=self.timeout * 1000)
        except Exception as e:
            raise PlaywrightServiceError(f"Failed to navigate to {url}: {e}") from e

    def reload(self):
        if self._page is None:
            raise PlaywrightServiceError("no active page; call browser_open first")
        self._page.reload(timeout=self.timeout * 1000)

    def evaluate(self, js: str, arg: Any = None) -> Any:
        if self._page is None:
            raise PlaywrightServiceError("no active page; call browser_open first")
        if arg is not None:
            return self._page.evaluate(js, arg)
        return self._page.evaluate(js)


_GPT_POLL_JS = r"""
(arg) => {
  const out = {gptDetected: false, slots: []};
  try {
    const hasGPT  = typeof googletag !== 'undefined' && googletag.apiReady;
    const hasPbjs = typeof pbjs !== 'undefined';
    const cap     = window.__atacap;
    out.gptDetected = hasGPT || hasPbjs || !!cap;
    if (!out.gptDetected) return out;

    // PRIMARY: bid-event capture buffer (populated by _CAPTURE_INIT_JS).
    // This gives us EVERY bid response, not just the final winners.
    if (cap && Array.isArray(cap.bidResponses)) {
      const wonKeys = cap.wonKeys || new Set();
      cap.bidResponses.forEach(b => {
        const domains = b.domains || [];
        const domain = domains.length ? domains[0] : null;
        const wonKey = [b.bidder, b.creativeId, b.cpm, b.adUnit].join('|');
        out.slots.push({
          slotId:       b.adUnit,
          advertiserId: null,
          creativeId:   b.creativeId,
          lineItemId:   null,
          domain:       domain,
          bidder:       b.bidder,
          cpm:          b.cpm,
          currency:     b.currency,
          source:       b.source,
          auctionId:    b.auctionId,
          won:          wonKeys.has && wonKeys.has(wonKey) || false,
        });
      });
    }

    // FALLBACK: getAllWinningBids (winners only) for pages where our init hook
    // didn't get installed before pbjs was defined.
    if (out.slots.length === 0 && hasPbjs && typeof pbjs.getAllWinningBids === 'function') {
      try {
        (pbjs.getAllWinningBids() || []).forEach(b => {
          const domains = (b.meta && b.meta.advertiserDomains) || [];
          out.slots.push({
            slotId:       b.adUnitCode || null,
            advertiserId: null,
            creativeId:   b.creativeId != null ? String(b.creativeId) : null,
            lineItemId:   null,
            domain:       domains.length ? domains[0] : null,
            bidder:       b.bidder || null,
            cpm:          typeof b.cpm === 'number' ? b.cpm : null,
            currency:     b.currency || null,
            source:       b.source || null,
            auctionId:    b.auctionId || null,
            won:          true,
          });
        });
      } catch (e) { out.pbjs_error = String(e); }
    }

    // FALLBACK: GPT's getResponseInformation for non-Raptive sites.
    if (hasGPT && typeof googletag.pubads === 'function') {
      try {
        const pubads = googletag.pubads();
        if (typeof pubads.getResponseInformation === 'function') {
          const info = pubads.getResponseInformation() || {};
          Object.entries(info).forEach(([slotId, meta]) => {
            if (out.slots.some(s => s.slotId === slotId)) return;
            out.slots.push({
              slotId,
              advertiserId: meta && meta.advertiserId != null ? String(meta.advertiserId) : null,
              creativeId:   meta && meta.creativeId   != null ? String(meta.creativeId)   : null,
              lineItemId:   meta && meta.lineItemId   != null ? String(meta.lineItemId)   : null,
              domain:       null,
              bidder:       null,
              cpm:          null,
              currency:     null,
              source:       'gpt',
              auctionId:    null,
              won:          true,
            });
          });
        }
      } catch (e) { out.gpt_error = String(e); }
    }

    // Iframe-src enrichment for slots still missing a domain.
    out.slots.forEach(s => {
      if (s.domain || !s.slotId) return;
      const iframe = document.querySelector('iframe[id^="' + arg.prefix + s.slotId + '"]');
      if (iframe) {
        try {
          const src = iframe.getAttribute('src') || '';
          const m = src.match(/https?:\/\/([^\/]+)/);
          if (m) s.domain = m[1];
        } catch (e) { /* cross-origin */ }
      }
    });

    // Ambient counters.
    if (cap) {
      out.no_bids       = (cap.noBids       || []).length;
      out.timeouts      = (cap.timeouts     || []).length;
      out.auction_count = (cap.auctionEnds  || []).length;
    }
    return out;
  } catch (e) {
    return {gptDetected: false, slots: [], error: String(e)};
  }
}
"""


def _validate_params(checks: int, interval: int, per_check_timeout: int) -> None:
    if checks <= 0:
        raise ValueError(f"checks must be > 0, got {checks}")
    if interval < 0:
        raise ValueError(f"interval must be >= 0, got {interval}")
    if per_check_timeout <= 0:
        raise ValueError(f"per_check_timeout must be > 0, got {per_check_timeout}")


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"Invalid URL: {url!r}")


def scan_page(
    url: str,
    checks: Optional[int] = None,
    interval: Optional[int] = None,
    per_check_timeout: Optional[int] = None,
    _service_factory=None,
) -> Dict[str, Any]:
    """Scan ONE URL. Returns deduplicated ad summary. See module docstring."""
    return scan_pages([url], checks, interval, per_check_timeout, _service_factory)[0]


def scan_pages(
    urls: List[str],
    checks: Optional[int] = None,
    interval: Optional[int] = None,
    per_check_timeout: Optional[int] = None,
    _service_factory=None,
) -> List[Dict[str, Any]]:
    """Scan MANY URLs using ONE shared PlaywrightService (saves N Chromium cold starts)."""
    if not urls:
        return []
    n_checks = SCANNER_DEFAULTS["checks"] if checks is None else checks
    ival = SCANNER_DEFAULTS["interval"] if interval is None else interval
    per_to = SCANNER_DEFAULTS["per_check_timeout"] if per_check_timeout is None else per_check_timeout
    _validate_params(n_checks, ival, per_to)
    for u in urls:
        _validate_url(u)

    factory = _service_factory or (lambda: StealthBrowser(
        session=SCANNER_DEFAULTS["session"], timeout=per_to
    ))
    evaluate_arg = {"prefix": SCANNER_DEFAULTS["iframe_id_prefix"]}

    results: List[Dict[str, Any]] = []
    with factory() as svc:
        first = True
        for url in urls:
            start_ts = time.time()
            if first:
                svc.browser_open(url=url, persistent=False, headed=False)
                first = False
            else:
                svc.page_goto(url)  # shared browser, just navigate
            records: List[Dict[str, Any]] = []
            gpt_seen = False
            for i in range(n_checks):
                if i > 0:
                    if ival > 0:
                        time.sleep(ival)
                    svc.reload()
                _warm_page(svc)  # trigger lazy-load via scroll
                check = _poll_until_stable(svc, per_to, evaluate_arg)
                if check.get("gptDetected"):
                    gpt_seen = True
                records.extend(check.get("slots", []))
            duration = round(time.time() - start_ts, 3)
            results.append(_summarise(url, n_checks, duration, gpt_seen, records))
    return results


def _warm_page(svc) -> None:
    """Scroll through the page to trigger AdThrive/Raptive lazy-load and give
    GPT time to initialize."""
    scroll_count = SCANNER_DEFAULTS["warm_scroll_count"]
    scroll_delay = SCANNER_DEFAULTS["warm_scroll_delay_s"]
    try:
        for _ in range(scroll_count):
            svc.evaluate("() => window.scrollBy(0, 800)")
            time.sleep(scroll_delay)
        svc.evaluate("() => window.scrollTo(0, 0)")
    except Exception:
        # If evaluate fails here, _poll_until_stable will catch it next.
        pass


def _poll_until_stable(svc, per_check_timeout: int, arg: dict) -> Dict[str, Any]:
    """Poll GPT until slot count is stable for `stable_polls` consecutive polls
    OR the per_check_timeout elapses.

    Special case: "stable at zero" is only accepted AFTER `min_initial_wait_s`
    elapses -- real-world ad auctions often take 3-6s to fill slots, and
    declaring stability-at-zero too early misses late-rendering creatives.
    If per_check_timeout is very short (< min_initial_wait_s), the floor is
    clamped so tests with short budgets still exit on time.

    No fallback patterns: if evaluate() returns None we treat it as
    infrastructure failure and raise.
    """
    start = time.time()
    deadline = start + per_check_timeout
    poll_s = SCANNER_DEFAULTS["poll_ms"] / 1000.0
    stable_target = SCANNER_DEFAULTS["stable_polls"]
    min_initial_wait = min(SCANNER_DEFAULTS["min_initial_wait_s"], max(0, per_check_timeout - 1))

    last_count = None
    stable_run = 0
    last_result: Dict[str, Any] = {"gptDetected": False, "slots": []}

    while time.time() < deadline:
        result = svc.evaluate(_GPT_POLL_JS, arg)
        if result is None:
            raise PlaywrightServiceError(
                "page.evaluate returned None; _GPT_POLL_JS is designed to always return an object"
            )
        last_result = result
        cnt = len(result.get("slots", []))
        if cnt == last_count:
            stable_run += 1
            if stable_run >= stable_target - 1:
                # Accept non-zero stability immediately; gate zero-stability
                # behind min_initial_wait so ads have time to load.
                if cnt > 0 or (time.time() - start) >= min_initial_wait:
                    return last_result
        else:
            stable_run = 0
        last_count = cnt
        time.sleep(poll_s)
    return last_result


def _dedupe_key(rec: Dict[str, Any]) -> Tuple[str, str, str]:
    """Dedupe key. Falls back to slotId ONLY when both advertiserId AND domain
    are missing, so two genuinely-unknown advertisers aren't collapsed into one.
    advertiserId='0' (house ad) is distinct from None (unknown)."""
    adv = rec.get("advertiserId")
    dom = rec.get("domain")
    if adv is None and dom is None:
        return ("__unknown__", "", rec.get("slotId") or "")
    # Use sentinel strings so None and '' don't collide (None -> '\x00', '' -> '').
    adv_k = "\x00" if adv is None else adv
    dom_k = "\x00" if dom is None else dom
    return (adv_k, dom_k, "")


def _summarise(url, n_checks, duration, gpt_seen, records):
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not gpt_seen or not records:
        return {
            "url": url,
            "scanned_at": now_iso,
            "checks_completed": n_checks,
            "duration_seconds": duration,
            "gpt_detected": gpt_seen,
            "unique_advertisers": [],
            "total_impressions": 0,
        }
    buckets: Dict[tuple, Dict[str, Any]] = {}
    total = 0
    for r in records:
        total += 1
        k = _dedupe_key(r)
        if k not in buckets:
            buckets[k] = {
                "domain": r.get("domain"),
                "advertiser_id": r.get("advertiserId"),
                "creative_ids": [],
                "slot": r.get("slotId"),
                "bidders": [],
                "cpms": [],
                "max_cpm": None,
                "min_cpm": None,
                "avg_cpm": None,
                "appearances": 0,
                "won_count": 0,
            }
        cid = r.get("creativeId")
        if cid and cid not in buckets[k]["creative_ids"]:
            buckets[k]["creative_ids"].append(cid)
        bidder = r.get("bidder")
        if bidder and bidder not in buckets[k]["bidders"]:
            buckets[k]["bidders"].append(bidder)
        cpm = r.get("cpm")
        if cpm is not None:
            buckets[k]["cpms"].append(cpm)
        if r.get("won"):
            buckets[k]["won_count"] += 1
        buckets[k]["appearances"] += 1
    advertisers = []
    for b in buckets.values():
        cpms = b.pop("cpms")
        if cpms:
            b["min_cpm"] = round(min(cpms), 4)
            b["max_cpm"] = round(max(cpms), 4)
            b["avg_cpm"] = round(sum(cpms) / len(cpms), 4)
        b["share"] = round(b["appearances"] / total, 3)
        advertisers.append(b)
    advertisers.sort(key=lambda x: (x["won_count"], x["appearances"]), reverse=True)
    return {
        "url": url,
        "scanned_at": now_iso,
        "checks_completed": n_checks,
        "duration_seconds": duration,
        "gpt_detected": True,
        "unique_advertisers": advertisers,
        "total_impressions": total,
    }
