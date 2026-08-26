#!/usr/bin/env python3
"""Local viewer for the LEGO Scout ledger: one score-ranked table, live refresh,
and action buttons that write straight back to the ledger.

A static file can't do this -- Chrome blocks fetch() from file://, so a
standalone page can only show data frozen at build time and its buttons can't
persist anything. This binds an HTTP server so Refresh genuinely re-reads the
ledger and Reject/Inquired/Bid Placed are real writes.

Bulk and sets share one table because they share one score: legoscout-deal-scoring
puts both on a 0-100 scale that means the same thing, so "what are my best buys
right now" is one sorted list. Category-specific detail lives in the expandable
row, which is where it belongs -- nobody scans fourteen columns.

Row shaping is delegated to `display/rows.py`, in process; this server is
its only consumer.

Runs until stopped -- ctrl-c for a local debug session, pm2 on adam-server
for the deployed page. There is no self-shutdown-when-idle behaviour: pm2 is
the process supervisor for the deployed instance, and a timer racing against
a supervisor that just restarts it is pointless.

    legoscout display serve                                   # local debug
    legoscout display serve --host 100.117.198.37 --port 8788  # what pm2 runs
"""
import argparse
import json
import os
import re
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
from . import rows
from ..ledger import db as ledger_db
from ..ledger import prospects as prospects_db
from ..scoring import rescore as rescore_ledger
from ..ledger import sellers as sellers_db
from ..paths import MINIFIG_CROP_ROOT

DEFAULT_PORT = 8787

LEDGER = ledger_db.DB_PATH

# The ledger path every Python-side read/write in this server uses. `--db`
# defaults to the live ledger, so this always holds exactly ONE real path and
# the calls below pass it unconditionally -- there is no "override or default"
# expression anywhere.
DB_OVERRIDE = LEDGER

# `best` and `watchlist` are gone: quality is the score, and status is lifecycle
# plus what Adam did. `active` is here so a row can be un-rejected.
ALLOWED_STATUS = set(ledger_db.SETTABLE_STATUS)
_write_lock = threading.Lock()

# Request-origin gate. Loopback is not a boundary a browser respects, and the
# deployed instance binds a real Tailscale interface, so this matters even
# more there: every page Adam has open can reach this host, and /status is a
# real write to the ledger. main() fills both sets from the resolved
# host/port, so they always describe this process and no other.
#   ALLOWED_HOSTS   -- the Host values that mean "this server". A request naming
#                      anything else arrived through a name that resolves here,
#                      which is DNS rebinding, so it is refused outright.
#   ALLOWED_ORIGINS -- the origins the page itself is served from.
ALLOWED_HOSTS = set()
ALLOWED_ORIGINS = set()
JSON_CTYPE = "application/json"
CROP_ROOT = Path(MINIFIG_CROP_ROOT)
CROP_MAX_BYTES = 10 * 1024 * 1024
CROP_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
# Extension-chosen types must be proven by the file's leading bytes.
CROP_MAGIC = {
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/webp": b"RIFF",
}
CONTENT_HASH_CROP_RE = re.compile(
    r"^figcrop-v[0-9]+-[0-9a-f]{64}\.(?:jpe?g|png|webp)$", re.I)


def build_rows(active_only=True):
    """The rows, built in process. `--db` applies here as it does everywhere
    else in this server: one response can no longer mix two databases."""
    return rows.build_rows(active_only, DB_OVERRIDE)


def set_status(listing_key, status, path):
    """Write a status change back to the ledger. Serialised so two fast clicks
    can't interleave a read-modify-write and lose one.

    `path` is required, with no default: a default bound at import time would go
    stale the moment main() resolves `--db`, and the caller would silently write
    to the wrong file.
    """
    # listing_key reaches the sqlite3 driver as a bound parameter, and the
    # driver's own type error is a 500 the caller cannot act on. The type is the
    # caller's mistake, so it is reported here as one.
    if not isinstance(listing_key, str) or not listing_key.strip():
        return False, "listing_key must be a non-empty string"
    if status not in ALLOWED_STATUS:
        return False, "status %r not allowed" % status
    with _write_lock:
        ts = datetime.now(timezone.utc).isoformat()
        if not ledger_db.update_status(listing_key, status, ts, path=path):
            return False, "listing_key not found"
    return True, "ok"


def set_favorite(source, seller_id, is_favorite, path):
    """Flip a seller's favorite flag and immediately rescore that seller's
    live-status deals so the star, the score, and the row highlight all agree
    on refresh. Serialised under the same lock /status uses.
    """
    if not isinstance(source, str) or not source.strip():
        return False, "source must be a non-empty string"
    if not isinstance(seller_id, str) or not seller_id.strip():
        return False, "seller_id must be a non-empty string"
    if not isinstance(is_favorite, bool):
        return False, "is_favorite must be a boolean"
    with _write_lock:
        try:
            sellers_db.set_favorite(source, seller_id, is_favorite, path=path)
        except sellers_db.SellerError as exc:
            return False, str(exc)
        rescore_ledger.rescore_seller(source, seller_id, apply=True, path=path)
    return True, "ok"


# Prospect statuses the page may set. `dead` stays agent-side -- it is the
# world's verdict (a closed business, a past event), recorded by
# expire_events(), not a button Adam clicks.
PROSPECT_SETTABLE_STATUS = ("active", "rejected")


def set_prospect_status(prospect_id, status, path):
    """Adam's reject/restore click on a prospect row. Same serialisation as
    /status: two fast clicks must not interleave."""
    if not isinstance(prospect_id, int) or isinstance(prospect_id, bool):
        return False, "prospect_id must be an integer"
    if status not in PROSPECT_SETTABLE_STATUS:
        return False, "status %r not allowed" % status
    with _write_lock:
        if prospects_db.get_prospect(prospect_id, path=path) is None:
            return False, "prospect not found"
        prospects_db.update_prospect_status(prospect_id, status, path=path)
    return True, "ok"


def set_prospect_favorite(prospect_id, is_favorite, path):
    """The ★ on a prospect row. Flips the flag only -- unlike a seller star,
    no score changes, so no rescore follows."""
    if not isinstance(prospect_id, int) or isinstance(prospect_id, bool):
        return False, "prospect_id must be an integer"
    if not isinstance(is_favorite, bool):
        return False, "is_favorite must be a boolean"
    with _write_lock:
        try:
            prospects_db.set_favorite(prospect_id, is_favorite, path=path)
        except prospects_db.ProspectError as exc:
            return False, str(exc)
    return True, "ok"


PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<title>LEGO Scout — Deals</title>
<style>
:root{--bg:#faf9f7;--fg:#1a1a18;--dim:#6b6a65;--line:#e5e3dd;--card:#fff;--accent:#2b6cb0}
@media(prefers-color-scheme:dark){:root{--bg:#1a1a18;--fg:#eceae4;--dim:#9a978f;--line:#33322e;--card:#232320;--accent:#7fb3e8}}
*{box-sizing:border-box}
body{margin:0;padding:20px;background:var(--bg);color:var(--fg);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:14px}
h1{font-size:19px;margin:0;font-weight:600}
.meta{color:var(--dim);font-size:12px}
button{font:inherit;cursor:pointer;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--fg);padding:5px 12px}
button:hover{border-color:var(--accent);color:var(--accent)}
#refresh{font-weight:600;border-color:var(--accent);color:var(--accent)}
#refresh[disabled]{opacity:.5;cursor:default}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:10px;margin-bottom:12px}
.metric{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:9px 12px}
.metric-label{font-size:11px;color:var(--dim)}
.metric-value{font-size:19px;font-weight:600}
.controls{display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap;align-items:center}
input[type=text]{flex:1;min-width:200px;padding:6px 10px;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--fg);font:inherit}
.ftab{padding:3px 11px;border-radius:6px;font-size:12px;color:var(--dim);border:1px solid var(--line);background:transparent}
.ftab.on{background:var(--card);color:var(--fg);font-weight:600}
.wrap{overflow:auto;max-height:74vh;border:1px solid var(--line);border-radius:8px;background:var(--card)}
table{width:100%;border-collapse:collapse;font-size:13px}
th{position:sticky;top:0;background:var(--card);text-align:left;font-size:11px;font-weight:600;color:var(--dim);
   padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap;cursor:pointer;z-index:1}
th.on{color:var(--fg)}
td{padding:5px 10px;border-bottom:1px solid var(--line);white-space:nowrap;vertical-align:middle}
td.tc{max-width:0;overflow:hidden;text-overflow:ellipsis}
td.tc a{color:var(--accent);text-decoration:none}
td.tc a:hover{text-decoration:underline}
tr:hover td{background:rgba(127,127,127,.07)}
.num{text-align:right}.dim{color:var(--dim);font-size:12px}
.sc{display:inline-flex;align-items:center;justify-content:center;min-width:34px;height:20px;border-radius:4px;font-size:11px;font-weight:600}
.pos{color:#2f7d32;font-weight:600}.neg{color:#b3261e;font-weight:600}
.nocomp{color:var(--dim);font-size:11px;font-style:italic}
.floor{color:var(--dim);font-style:italic}
.cat{font-size:10px;text-transform:uppercase;letter-spacing:.04em;color:var(--dim);border:1px solid var(--line);border-radius:4px;padding:1px 5px}
.flag{color:#b26a00;font-weight:600;cursor:help}
.exp{cursor:pointer;color:var(--dim);user-select:none;width:14px;display:inline-block}
.tlb{white-space:nowrap}
.tlb input{width:64px;padding:3px 6px;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--fg);font:inherit;font-size:12px}
.tlb-out{display:inline-block;min-width:52px;font-size:12px;font-weight:600;margin-left:4px}
.act{display:grid;grid-template-columns:66px 70px 74px 56px;gap:4px;align-items:center}
.act button{padding:2px 4px;font-size:11px;width:100%;box-sizing:border-box;text-align:center}
.act .lbl{text-align:center}
.b-rej:hover{border-color:#b3261e;color:#b3261e}
#rejectall:hover{border-color:#b3261e;color:#b3261e}
#rejectall[disabled]{opacity:.5;cursor:default}
.b-inq:hover{border-color:var(--accent);color:var(--accent)}
.b-bid:hover{border-color:#b26a00;color:#b26a00}
.b-buy:hover{border-color:#2f7d32;color:#2f7d32}
.bought{color:#2f7d32;font-weight:600;font-style:normal}
tr.is-bought td{background:rgba(47,125,50,.07)}
/* Row whose listing link was opened most recently -- survives re-render and
   reload so Adam can come back from the marketplace tab and see where he was. */
tr.is-last td{background:rgba(43,108,176,.15)}
@media(prefers-color-scheme:dark){tr.is-last td{background:rgba(127,179,232,.16)}}
tr.is-last td:first-child{box-shadow:inset 3px 0 0 var(--accent)}
/* A favorited seller's deal -- gold tint, plus a star badge by the title. */
tr.is-fav td{background:rgba(212,160,23,.12)}
@media(prefers-color-scheme:dark){tr.is-fav td{background:rgba(212,160,23,.2)}}
.star{cursor:pointer;color:var(--line)}
.star.on{color:#d4a017}
.star:hover{color:#d4a017}
.favbadge{color:#d4a017;margin-left:3px}
tr.det td{white-space:normal;background:rgba(127,127,127,.05);padding:10px 14px}
.dgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px 18px}
.dk{font-size:11px;color:var(--dim)}
.dv{font-size:13px}
.minifig-summary{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:12px 0 8px;font-size:12px;color:var(--dim)}
.id-state{padding:3px 8px;border-radius:999px;font-weight:600}
.id-state.complete{background:#d5ead2;color:#2f6929}
.id-state.incomplete{background:#fbe3b4;color:#875d0d}
.fig-list{display:grid;gap:8px}
.fig-entry{display:grid;grid-template-columns:72px minmax(180px,1.6fr) repeat(4,minmax(82px,.55fr));gap:10px;align-items:center;padding:8px;border:1px solid var(--line);border-radius:7px;background:var(--card)}
.minifig-crop{width:64px;height:64px;object-fit:cover;border-radius:5px;border:1px solid var(--line)}
.fig-name{font-weight:600}.fig-id,.fig-meta,.fig-notes{font-size:11px;color:var(--dim)}
.fig-money{text-align:right}.fig-money .dk{text-transform:none}.fig-value,.fig-number{font-weight:600}
@media(max-width:760px){.fig-entry{grid-template-columns:64px 1fr}.fig-money{text-align:left}}
.basis{margin-top:8px;font-size:12px;color:var(--dim);font-style:italic}
.lbl{font-size:11px;font-style:italic;color:var(--dim)}
#toast{position:fixed;right:18px;bottom:18px;background:var(--card);border:1px solid var(--accent);
  border-radius:8px;padding:9px 14px;font-size:13px;opacity:0;transition:opacity .2s;pointer-events:none;z-index:9}
#toast.show{opacity:1}
a.bl{margin-right:6px;color:var(--accent);text-decoration:none}
</style></head><body>
<header>
  <h1>LEGO Scout — Deals</h1>
  <span id="viewtabs"></span>
  <button id="refresh">↻ Refresh</button>
  <span class="meta" id="stamp"></span>
  <label class="meta"><input type="checkbox" id="showall"> include rejected</label>
  <label class="meta" title="Bid-only auctions show an opening or current bid, so their landed cost is a floor. Hiding them leaves only listings with a firm price."><input type="checkbox" id="firmonly"> buy-now only</label>
  <label class="meta" title="Rows where the model's own read of the listing disagrees with the computed score by more than 15 points. These are the rows worth a second look -- and the signal that the formula is missing a factor."><input type="checkbox" id="flagged"> flagged only</label>
  <label class="meta" title="Sets and minifigure lots with a computed net profit under $10, AND ones with no profit figure at all (no comps, missing landed cost, gated incomplete), are hidden by default. Uncheck to see everything."><input type="checkbox" id="minprofit" checked> hide sets &amp; minifigs &lt; $10 / unpriced</label>
  <label class="meta" title="Listings priced under $20 are not worth the time to chase -- hidden by default, bulk, sets, and minifigure lots alike. Uses the Price column's number (the current bid on a bid-only auction)."><input type="checkbox" id="minprice" checked> hide price &lt; $20</label>
</header>
<div class="metrics" id="metrics"></div>
<div class="controls">
  <input type="text" id="q" placeholder="Filter by title, source, set number…">
  <span id="catfilters"></span>
  <span id="filters"></span>
  <button id="rejectall" title="Rejects every deal currently shown below -- after the active tab, category filter, search, and toggles -- skipping any already inquired, bid placed, purchased, or rejected.">Reject all shown</button>
</div>
<div class="wrap"><table><thead><tr id="thead"></tr></thead><tbody id="tbody"></tbody></table></div>
<div id="toast"></div>
<script>
const AUCTION_TIP="Opening or current bid on an active auction, not a final price. Landed cost will change before it ends.";
const SHIP_TIP="Estimated inbound freight, not a seller quote.";
const NO_SHIP_TIP="Inbound freight has not been quoted or estimated for this lot -- usually because the listing states no weight. Total is a floor, not a landed cost.";
// available_fulfillment is the ONLY thing that decides pickup vs ship. The page
// reads its label rather than inferring "free pickup" from a $0.00 figure.
const PICKUP_TIP="Local pickup only -- the seller will not ship, so there is no freight to pay and none to quote. Adam collects it himself, which only works inside the 30-mile drive radius of 47725.";
const INCOMPLETE_TIP="Listing states the set is incomplete or parts-only; BrickLink comps price a complete set, so profit is not calculable.";
const MAXBID_TIP="The most this lot is worth to Adam -- $4.00/lb scaled by the quality multiplier for bulk, or net resale less the minimum margin for a set or minifigure lot. The score collapses as the price approaches it.";
const QUAL_TIP="How good the lot is on its own merits, price excluded. 75 is a plain clean bulk lot.";
const LEGACY_TIP="Scored by the old model, on a scale that no longer applies. Not comparable to the rest of the table, so it never ranks against them.";
const UNSCORABLE_TIP="Not enough information to score. The reason is in the expanded row.";
const MAXBID_PROFIT_TIP="If you were to win this item at your Max Bid, this is what you would net -- resale value minus that landed-cost ceiling. This auction is not settled yet, so it is a guaranteed floor, not an estimate. Win below Max Bid and you net more.";

let DATA=[], filter="active", catFilter="all", sortCol="score", sortAsc=false,
    showAll=false, firmOnly=false, flaggedOnly=false, minProfitOnly=true, minPriceOnly=true;
// The Prospects view is a whole different object, so it is a top-level view
// toggle rather than another status chip: its own columns, its own render,
// and its own two write routes (/prospect_status, /prospect_favorite).
let VIEW="deals", PDATA=[];
const EXPANDED=new Set();
// Typed target-$/lb values, kept outside DATA/render so a keystroke survives
// the next render() -- search, sort, and filter clicks all replace tbody's
// innerHTML wholesale, which would otherwise wipe an in-progress input.
const TARGETLB=new Map();
// listing_key of the row whose title link was opened last, kept in
// localStorage so it still reads as "where I was" after a refresh.
let LASTOPENED=localStorage.getItem("ls_last_opened")||"";
// Statuses that mean Adam has already dealt with the row, so it is not part of
// the "what do I do next" view.
const ACTED=new Set(["rejected","purchased","inquired","bid_placed"]);

const COLS=[{k:"score",l:"Score",s:1},{k:"title",l:"Title",w:"width:99%"},{k:"cat",l:"Cat"},
  {k:"source",l:"Source"},{k:"seller",l:"Seller"},{k:"price",l:"Price",s:1},{k:"total",l:"Landed",s:1},
  {k:"perLb",l:"$ / lb",s:1},{k:"profit",l:"Profit",s:1},
  {k:"maxPrice",l:"Max bid",s:1},{k:"quality",l:"Qual",s:1},{k:"modelScore",l:"Model",s:1},
  {k:"ends",l:"Ends"},{k:"tlb",l:"Target $"},{k:"act",l:""}];

// Name carries the same width:99% hint the deals Title column uses. td.tc is
// max-width:0 so its ellipsis works, which collapses an unhinted column to
// nothing -- without this the prospect name renders as "Platinu…".
const PCOLS=[{k:"name",l:"Name",w:"width:99%"},{k:"hypothesis_type",l:"Type"},{k:"status",l:"Status"},
  {k:"available_fulfillment",l:"Fulfillment"},{k:"distance_miles",l:"Miles"},{k:"event_date",l:"Event"},
  {k:"location",l:"Location"},{k:"contact_count",l:"Contacts"},{k:"latest_outreach_state",l:"Outreach"},
  {k:"created_at",l:"Added"},{k:"act",l:""}];

// $1-10 red, $10-20 yellow, $20+ green. Below $1 (incl. negative) reads as the
// same red as the rest of the "not worth it" band -- there is no separate,
// darker bucket for a loss.
function profitBg(v){if(v==null)return"#e8e6e0";if(v>=20)return"#c0dd97";if(v>=10)return"#fac775";return"#f3a6a6";}
function profitFg(v){if(v==null)return"#77756e";if(v>=20)return"#3b6d11";if(v>=10)return"#ba7517";return"#9a2f2f";}
// A bid-only auction has no settled price yet -- `potential_profit` was
// computed against the current bid, a floor. `profitAtMaxBid` is the floor
// Adam is guaranteed if he holds the line at his own walk-away Max Bid; see
// legoscout display rows for the derivation. Marked with an asterisk since it is a
// worst-case projection, not a settled number.
function profitDisplay(r){
  if(r.cat!=="set"&&r.cat!=="minifigure")return null;
  return r.auc?r.profitAtMaxBid:r.profit;}

function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}
function money(v){return (v===null||v===undefined||v==="")?"—":"$"+Number(v).toFixed(2);}

// Inverts legoscout-pricing's fees.py landed_cost(): that function solves
// hammer -> landed total; this solves the reverse, target landed total (the
// $/lb Adam types for a bulk lot times its weight) -> the hammer bid that reaches it.
// Mirrors all three tax_basis rules so the answer matches the Landed column's
// own math instead of a looser approximation.
function units(r){return r.weight;}
function calcBid(r,target){
  const t=parseFloat(target);
  if(!isFinite(t)||t<=0)return null;
  const u=units(r);
  if(!u)return null;
  const total=t*u;
  const prem=r.prem||0,tax=r.tax||0,fixed=r.premFix||0,ship=r.ship||0;
  const basis=r.taxBasis||"hammer_plus_premium";
  if(basis==="hammer_plus_shipping")return(total-fixed-ship*(1+tax))/(1+prem+tax);
  if(basis==="hammer_plus_premium")return(total-fixed*(1+tax)-ship)/((1+prem)*(1+tax));
  return(total-fixed-ship)/(1+prem+tax);
}
function tlbOut(r,val){
  if(!val)return"";
  const bid=calcBid(r,val);
  if(bid==null)return"";
  return bid<0?'<span class="neg" title="Fixed fees and shipping alone exceed this per-unit target.">over budget</span>':money(bid);
}
function setTlb(key,val){
  TARGETLB.set(key,val);
  const r=DATA.find(x=>x.key===key),el=document.getElementById("tlbo-"+key);
  if(r&&el)el.innerHTML=tlbOut(r,val);
}
function scoreBg(s){if(s==null)return"#e8e6e0";if(s>=90)return"#c0dd97";if(s>=75)return"#9fe1cb";if(s>=55)return"#fac775";return"#e8e6e0";}
function scoreFg(s){if(s==null)return"#77756e";if(s>=90)return"#3b6d11";if(s>=75)return"#0f6e56";if(s>=55)return"#ba7517";return"#77756e";}

// Only rows this scorer has actually seen carry a comparable number. A legacy
// row keeps its old score visible but never sorts against the new scale --
// otherwise a stale 100 sits permanently at the top of the table.
function rank(r){return r.scored?r.score:null;}

function blLinks(nums){if(!Array.isArray(nums)||!nums.length)return'<span class="nocomp">—</span>';
  return nums.slice(0,4).map(n=>'<a class="bl" target="_blank" href="https://www.bricklink.com/v2/catalog/catalogitem.page?S='+encodeURIComponent(n)+'#T=P">'+esc(n)+'</a>').join(" ")
    +(nums.length>4?' <span class="dim">+'+(nums.length-4)+'</span>':'');}
function pctText(v){let s=v.toFixed(2);
  if(s.indexOf(".")>=0)s=s.replace(/0+$/,"").replace(/\.$/,"");
  return s+"%";}
function feeTitle(r){
  const pa=r.premAmt||0, ta=r.taxAmt||0, fx=r.premFix||0, parts=[];
  const pp=(r.prem||0)*100, tp=(r.tax||0)*100;
  if(!pp&&!tp&&!fx)return "No buyer's premium or sales tax on this source";
  if(r.auc)parts.push("Not final while bidding is open — these apply to your winning bid");
  const pct=pa-fx;
  if(pp)parts.push("Buyer's premium "+pctText(pp)+(r.auc||!pct?"":" = $"+pct.toFixed(2)));
  if(fx)parts.push("Flat lot fee $"+fx.toFixed(2)+" — owed regardless of the bid");
  if(tp)parts.push("Sales tax "+pctText(tp)+(r.auc||!ta?"":" = $"+ta.toFixed(2)));
  if(!r.auc)parts.push("Total fees = $"+(pa+ta).toFixed(2));
  if(String(r.fees||"").indexOf("*")>=0)parts.push("* rate is a source default, not read from the lot page");
  return parts.join(" · ");}
function compCell(v,n){
  // Numeric comps arrive as raw floats straight off BrickLink (36.3624) --
  // money-format them; non-numeric values are REASONS ("no sold comps") and
  // must render verbatim rather than as a number.
  //
  // On a multi-set lot the comp is a SUM across every set, so say so. The
  // count is DERIVED from r.nums here. It used to arrive baked into the value
  // as the string "$20.32 (2 sets)", which made a real number render through
  // the "no comps" reason path and could never be sorted or compared.
  if(typeof v==="number")return money(v)+(n>1?' <span class="dim">('+n+' sets)</span>':"");
  return '<span class="nocomp">'+esc(v)+'</span>';}

function sortVal(r,k){
  switch(k){
    case"score":return rank(r);
    case"quality":return r.quality;
    case"maxPrice":return r.maxPrice;
    case"modelScore":return r.modelScore;
    case"total":return r.total;
    case"perLb":return r.perLb;
    case"profit":return profitDisplay(r);
    case"price":return r.auc?null:r.hammer;}
  return null;}

function rows(){const q=document.getElementById("q").value.toLowerCase();
  let d=DATA.filter(r=>{
    // 'active' = still needs a decision. Anything Adam has acted on is out:
    // rejected, bought, or waiting on someone else. Those rows stay in the
    // payload so their own filters and the spend total still work.
    // 'needs_review' is a slice of 'active', not a stored status -- the
    // ledger's `status` field is lifecycle-only by design (there is no
    // deal-quality bucket in it). A row needs review when the pipeline could
    // not price it at all: no weight/landed cost for bulk, no comps/landed
    // cost for a set, or a gated-incomplete set. `score==null` already means
    // exactly that -- see score_deal.py's `unscorable` reasons.
    if(filter==="needs_review"){if(ACTED.has(r.status)||r.score!=null)return false;}
    else if(filter==="active"){if(ACTED.has(r.status)||r.score==null)return false;}
    else if(filter!=="all"&&r.status!==filter)return false;
    if(catFilter!=="all"&&r.cat!==catFilter)return false;
    if(firmOnly&&r.auc)return false;
    if(flaggedOnly&&!r.divergenceFlag)return false;
    // The min-profit floor only makes sense once a set actually has a price --
    // the needs-review tab exists specifically to show the ones that don't.
    if(minProfitOnly&&filter!=="needs_review"&&(r.cat==="set"||r.cat==="minifigure")&&(r.profit==null||r.profit<10))return false;
    if(minPriceOnly&&r.hammer!=null&&r.hammer<20)return false;
    if(q){const hay=(r.title+" "+r.source+" "+(r.nums?r.nums.join(" "):"")).toLowerCase();
      if(hay.indexOf(q)<0)return false;}
    return true;});
  if(sortCol)d.sort((a,b)=>{const av=sortVal(a,sortCol),bv=sortVal(b,sortCol);
    // Unknown values are neither best nor worst -- they always sort last, in
    // either direction, instead of masquerading as an extreme.
    if(av==null&&bv==null)return 0;
    if(av==null)return 1;
    if(bv==null)return -1;
    return sortAsc?(av-bv):(bv-av);});
  return d;}

function scoreCell(r){
  if(!r.scored)return '<td><span class="sc" style="background:'+scoreBg(null)+';color:'+scoreFg(null)+'" title="'+LEGACY_TIP+'">'+(r.score!=null?r.score:"—")+'<span class="dim">†</span></span></td>';
  if(r.score==null)return '<td><span class="sc" style="background:'+scoreBg(null)+';color:'+scoreFg(null)+'" title="'+UNSCORABLE_TIP+'">n/s</span></td>';
  return '<td><span class="sc" style="background:'+scoreBg(r.score)+';color:'+scoreFg(r.score)+'">'+r.score+'</span></td>';}

function profitCell(r){
  const v=profitDisplay(r);
  if(v==null)return'<td class="num dim">—</td>';
  const compCats=["set","minifigure"];
  const star=(r.cat==="set"||r.cat==="minifigure")&&r.auc?'<span class="dim" title="'+esc(MAXBID_PROFIT_TIP)+'">*</span>':"";
  const zc=compCats.includes(r.cat)&&r.zeroCompNote?'<span class="dim" title="'+esc(r.zeroCompNote)+'">&dagger;</span>':"";
  return '<td class="num"><span class="sc" style="background:'+profitBg(v)+';color:'+profitFg(v)+'">'
    +(v<0?"-$":"$")+Math.abs(v).toFixed(2)+'</span>'+star+zc+'</td>';}

function sellerCell(r){
  if(!r.sellerId)return '<td class="dim">—</td>';
  const on=r.sellerFavorite;
  return '<td class="dim"><span class="star'+(on?" on":"")+'" title="'
    +(on?"Favorited — click to remove":"Favorite this seller")
    +'" onclick="toggleFavorite(\''+esc(r.sellerSource)+'\',\''+esc(r.sellerId)+'\','+(on?"false":"true")+')">'
    +(on?"★":"☆")+'</span> '+esc(r.sellerName||r.sellerId)+'</td>';
}

function minifigDetail(r){
  const complete=!!r.identificationComplete;
  const summary='<div class="minifig-summary"><span class="id-state '+(complete?"complete":"incomplete")+'">'
    +(complete?"identification complete":"identification incomplete")+'</span><span>'
    +Number(r.identifiedCount||0)+' identified · '+Number(r.unknownCount||0)+' unknown</span><span>Identified subtotal '
    +money(r.minifigSubtotal)+'</span></div>';
  const figures=(r.figures||[]).map(f=>{
    const known=!!f.figNo;
    const identity=known?'<a href="https://www.bricklink.com/v2/catalog/catalogitem.page?M='
      +encodeURIComponent(f.figNo)+'" target="_blank" rel="noopener noreferrer">'+esc(f.figNo)+'</a>'
      :'<span class="dim">unknown identity</span>';
    const notes=[f.conditionNotes].concat(f.errors||[]).filter(Boolean).map(esc).join(' · ');
    return '<div class="fig-entry" data-fig-status="'+esc(f.status||"unknown")+'">'
      +'<img class="minifig-crop" src="'+esc(f.cropUrl)+'" alt="'+esc(known?(f.name||f.figNo)+' crop':"Unknown minifigure crop")+'" loading="lazy">'
      +'<div><div class="dk">Name</div><div class="fig-name">'+esc(f.name||"Unknown")+'</div>'
      +'<div class="dk">Identity</div><div class="fig-id">'+identity+'</div>'
      +'<div class="dk">Condition notes</div><div class="fig-notes">'+(notes||'—')+'</div>'
      +(f.nullValueReason?'<div class="fig-meta">'+esc(f.nullValueReason)+'</div>':'')+'</div>'
      +'<div class="fig-money"><div class="dk">Qty</div><div class="fig-number">'+Number(f.quantity||0)+'</div></div>'
      +'<div class="fig-money"><div class="dk">Unit value</div><div class="fig-value">'
      +(f.unitValue!=null?money(f.unitValue):'—')+'</div></div>'
      +'<div class="fig-money"><div class="dk">Extended value</div><div class="fig-value">'
      +(f.extendedValue!=null?money(f.extendedValue):'—')+'</div></div>'
      +'<div class="fig-money"><div class="dk">Market depth</div><div class="fig-number">'
      +(f.soldCount!=null?Number(f.soldCount)+' sold':'—')+'</div></div></div>';
  }).join("");
  return summary+'<div class="fig-list">'+figures+'</div>';
}

function detail(r){
  const cells=[];
  let figureBody="";
  const add=(k,v)=>cells.push('<div><div class="dk">'+k+'</div><div class="dv">'+v+'</div></div>');
  const shipTxt=r.fulfil==="pickup"?'<span class="dim" title="'+PICKUP_TIP+'">pickup</span>'
    :r.ship!=null?money(r.ship)+(r.shipEst?'<span class="dim" title="'+SHIP_TIP+'">~</span>':"")
    :'<span class="dim" title="'+NO_SHIP_TIP+'">—</span>';
  if(r.cat==="bulk"){
    add("Weight",(r.weight?Number(r.weight).toFixed(1)+" lb":'<span class="dim">—</span>')
      +(r.weightSource==="estimated"?' <span class="dim" title="Weight read off the listing photos, not stated by the seller. The score is capped at 85 because of it.">~est</span>':""));
    add("Target colours",r.targetColors?esc(r.targetColors):'<span class="dim">not observed</span>');
  }else if(r.cat==="minifigure"){
    add("Figure count",r.figCount!=null?r.figCount+(r.figSrc&&r.figSrc!=="unknown"?' <span class="dim" title="Count source: '+esc(r.figSrc)+'">('+(r.figSrc==="stated"?"seller stated":"counted from photos")+')</span>':""):'<span class="dim">—</span>');
    if(Array.isArray(r.figures)){
      figureBody=minifigDetail(r);
    }else{
      // Reader-only compatibility for rows written before identifier artifacts.
      add("Legacy eBay $/fig",r.perFig!=null?"$"+Number(r.perFig).toFixed(2):'<span class="dim">—</span>');
      add("Legacy eBay comps",r.ebayCount!=null?r.ebayCount:'<span class="dim">—</span>');
    }
    add("Potential profit",r.profit==null?'<span class="dim">—</span>'
      :'<span class="'+(r.profit>=0?"pos":"neg")+'">'+(r.profit<0?"-$":"$")+Math.abs(r.profit).toFixed(2)+(r.pinc?"*":"")+'</span>');
  }else if(r.cat==="excluded"){
    add("Excluded",r.exclReason?esc(r.exclReason):'<span class="dim">reason not recorded</span>');
  }else{
    add("Sets",blLinks(r.nums));
    add("Condition",esc(r.cond));
    add("Completeness",r.cmpl==="incomplete"?'<span class="dim" title="'+INCOMPLETE_TIP+'">incomplete</span>':esc(r.cmpl));
    const nsets=Array.isArray(r.nums)?r.nums.length:0;
    add("Used avg (6mo)",compCell(r.used,nsets));
    add("New avg (6mo)",compCell(r.new,nsets));
    add("Potential profit",r.profit==null?'<span class="dim">—</span>'
      :'<span class="'+(r.profit>=0?"pos":"neg")+'">'+(r.profit<0?"-$":"$")+Math.abs(r.profit).toFixed(2)+(r.pinc?"*":"")+'</span>');
  }
  add("Shipping",shipTxt);
  add("Fees",'<span title="'+esc(feeTitle(r))+'">'+esc(r.fees)+(r.feeAmt?" = "+money(r.feeAmt):"")+'</span>');
  add("Images",esc(r.visionStatus).replace(/_/g," "));
  if(r.modelScore!=null)add("Model score",r.modelScore+(r.divergence!=null?' <span class="dim">('+(r.divergence>0?"+":"")+r.divergence+" vs computed)</span>":""));
  let body='<div class="dgrid">'+cells.join("")+'</div>'+figureBody;
  if(r.unscorable)body+='<div class="basis">Not scored: '+esc(r.unscorable)+'</div>';
  else if(r.scoreBasis)body+='<div class="basis">Max bid basis: '+esc(r.scoreBasis)+'</div>';
  return '<tr class="det"><td colspan="'+COLS.length+'">'+body+'</td></tr>';}

function render(){const d=rows();
  document.getElementById("thead").innerHTML=COLS.map(c=>
    '<th style="'+(c.w||"")+'" class="'+(sortCol===c.k?"on":"")+'" '+(c.s?'onclick="setSort(\''+c.k+'\')"':"")+'>'
    +c.l+(c.s&&sortCol===c.k?(sortAsc?" ↑":" ↓"):"")+'</th>').join("");

  const cnt={rejected:0,inquired:0,bid_placed:0,purchased:0};
  let spend=0,ship=0,flagged=0,unscored=0;
  d.forEach(r=>{if(cnt[r.status]!==undefined)cnt[r.status]++;
    if(r.divergenceFlag)flagged++;
    if(r.scored&&r.score==null)unscored++;
    if(r.ship!=null)ship+=r.ship;
    if(r.status==="purchased"&&r.total!=null)spend+=Number(r.total);});
  const m=[["Listings",d.length],["Not scored",unscored],
    ["Flagged",flagged?'<span class="flag">'+flagged+'</span>':0],
    ["Bid placed",cnt.bid_placed],
    ["Purchased",cnt.purchased+(spend?' <span class="dim" style="font-size:12px">$'+spend.toFixed(2)+'</span>':'')],
    ["Shipping total","$"+ship.toFixed(2)]];
  document.getElementById("metrics").innerHTML=m.map(([l,v])=>
    '<div class="metric"><div class="metric-label">'+l+'</div><div class="metric-value">'+v+'</div></div>').join("");

  document.getElementById("tbody").innerHTML=d.map(r=>{
    const st=r.status,open=EXPANDED.has(r.key);
    // Fixed grid slots (inquire/bid/buy/reject), one per column, on every row.
    // Each slot always emits an element -- a blank placeholder rather than "" --
    // so a missing button never lets a later slot get auto-placed into an
    // earlier column.
    const blank='<span></span>';
    const inqSlot=st==="inquired"?'<span class="lbl">Inquired</span>'
      :(st!=="bid_placed"&&st!=="purchased"&&st!=="rejected"&&r.contact
        ?'<button class="b-inq" onclick="mark(\''+r.key+'\',\'inquired\')">Inquired</button>':blank);
    const bidSlot=st==="bid_placed"?'<span class="lbl">Bid placed</span>'
      :(st!=="inquired"&&st!=="purchased"&&st!=="rejected"&&r.ltype!=="fixed"
        ?'<button class="b-bid" onclick="mark(\''+r.key+'\',\'bid_placed\')">Bid</button>':blank);
    const buySlot=st==="purchased"?'<span class="lbl bought">✓ Purchased</span>'
      :(st!=="rejected"?'<button class="b-buy" onclick="mark(\''+r.key+'\',\'purchased\')">Purchased</button>':blank);
    const rejSlot=st==="rejected"?'<span class="lbl">Rejected</span>'
      :(st!=="inquired"&&st!=="bid_placed"&&st!=="purchased"
        ?'<button class="b-rej" onclick="mark(\''+r.key+'\',\'rejected\')">Reject</button>':blank);
    const act='<div class="act">'+inqSlot+bidSlot+buySlot+rejSlot+'</div>';
    const tlbUnit="/lb";
    const tlbHasUnits=r.cat==="bulk"&&r.weight;
    const tlbCell=(tlbHasUnits&&r.ltype!=="fixed")
      ?'<td class="tlb"><input type="number" step="0.01" min="0" inputmode="decimal" placeholder="$'+tlbUnit+'" '
        +'value="'+esc(TARGETLB.get(r.key)||"")+'" oninput="setTlb(\''+r.key+'\',this.value)"> '
        +'<span class="tlb-out" id="tlbo-'+esc(r.key)+'">'+tlbOut(r,TARGETLB.get(r.key))+'</span></td>'
      :'<td class="num dim">—</td>';
    const flag=r.divergenceFlag
      ?' <span class="flag" title="The model scored this '+r.modelScore+' against a computed '+r.score+'. Worth a look.">&#9873;</span>':"";
    const favBadge=r.sellerFavorite?'<span class="favbadge" title="Favorited seller">★</span>':"";
    const tr='<tr data-k="'+esc(r.key)+'" class="'
      +(st==="purchased"?"is-bought ":"")+(r.sellerFavorite?"is-fav ":"")+(r.key===LASTOPENED?"is-last":"")+'">'
      +scoreCell(r)
      +'<td class="tc"><span class="exp" onclick="toggle(\''+r.key+'\')">'+(open?"▾":"▸")+'</span> '
        +'<a href="'+esc(r.url)+'" target="_blank" rel="noopener noreferrer">'+esc(r.title)+'</a>'+favBadge+flag+'</td>'
      +'<td><span class="cat">'+r.cat+'</span></td>'
      +'<td class="dim">'+esc(r.source)+'</td>'
      +sellerCell(r)
      +'<td class="num'+(r.auc?" dim":"")+'"'+(r.auc?' title="'+AUCTION_TIP+'"':"")+'>'
        +(r.hammer!=null?money(r.hammer)+(r.auc?"*":""):"—")+'</td>'
      +'<td class="num'+(r.auc?" dim":"")+'">'+(r.total!=null?money(r.total)+(r.auc?"*":""):"—")+'</td>'
      +'<td class="num dim">'+(r.perLb!=null?"$"+r.perLb.toFixed(2):"—")+'</td>'
      +profitCell(r)
      +'<td class="num" style="font-weight:600" title="'+MAXBID_TIP+'">'+money(r.maxPrice)+'</td>'
      +'<td class="num dim" title="'+QUAL_TIP+'">'+(r.quality!=null?r.quality:"—")+'</td>'
      +'<td class="num dim">'+(r.modelScore!=null?r.modelScore:"—")+'</td>'
      +'<td class="dim">'+esc(r.ends||"—")+'</td>'+tlbCell+'<td>'+act+'</td></tr>';
    return open?tr+detail(r):tr;}).join("");

  document.getElementById("catfilters").innerHTML=["all","bulk","set","minifigure"].map(v=>
    '<button class="ftab '+(v===catFilter?"on":"")+'" onclick="setCat(\''+v+'\')">'+v+'</button>').join("");
  document.getElementById("filters").innerHTML=["active","needs_review","purchased","bid_placed","inquired","rejected","all"].map(v=>
    '<button class="ftab '+(v===filter?"on":"")+'" onclick="setFilter(\''+v+'\')">'+v.replace("_"," ")+'</button>').join("");
}

// Static chrome, not data: the two tabs exist whatever the ledger says, so this
// runs at load and on a view switch and never from a data render. Hanging it
// off render() made the Prospects view unreachable the moment /rows.json
// failed -- refresh() threw before render() ran, which is exactly the moment
// Adam would want the other view.
function renderViewTabs(){
  document.getElementById("viewtabs").innerHTML=[["deals","Deals"],["prospects","Prospects"]].map(v=>
    '<button class="ftab '+(v[0]===VIEW?"on":"")+'" onclick="setView(\''+v[0]+'\')">'+v[1]+'</button>').join("");
}

// Deals-only chrome: the metric tiles, the filter/search row, and the header
// checkboxes all describe listings, so none of them mean anything against a
// prospect row.
function setView(v){VIEW=v;
  renderViewTabs();
  const d=(v==="deals")?"":"none";
  document.getElementById("metrics").style.display=d;
  document.querySelector(".controls").style.display=d;
  document.querySelectorAll("header label.meta").forEach(el=>{el.style.display=d;});
  refresh();}

// A null renders — here, in the browser. The JSON keeps the null, so a missing
// outreach state stays distinguishable from a stored empty string.
function renderProspects(){
  document.getElementById("thead").innerHTML=PCOLS.map(c=>'<th style="'+(c.w||"")+'">'+c.l+'</th>').join("");
  document.getElementById("tbody").innerHTML=PDATA.map(r=>{
    const star='<span class="star'+(r.is_favorite?" on":"")+'" title="'
      +(r.is_favorite?"Favorited — click to remove":"Favorite this prospect")
      +'" onclick="toggleProspectFavorite('+r.prospect_id+','+(r.is_favorite?"false":"true")+')">'
      +(r.is_favorite?"★":"☆")+'</span> ';
    const cells=PCOLS.map(c=>{
      if(c.k==="act"){
        // Same slot discipline as the deals table: rejected shows its label and
        // a Restore path back; everything else gets a Reject button.
        return r.status==="rejected"
          ?'<td><button class="b-inq" onclick="markProspect('+r.prospect_id+',\'active\')">Restore</button></td>'
          :'<td><button class="b-rej" onclick="markProspect('+r.prospect_id+',\'rejected\')">Reject</button></td>';
      }
      const v=r[c.k];
      if(c.k==="name")return '<td class="tc">'+star+'<a href="'+esc(r.citation_url)+'" target="_blank" rel="noopener noreferrer">'+esc(v)+'</a></td>';
      if(v===null||v===undefined||v==="")return '<td class="dim">—</td>';
      if(c.k==="distance_miles")return '<td class="num">'+Number(v).toFixed(1)+'</td>';
      if(c.k==="contact_count")return '<td class="num">'+esc(v)+'</td>';
      if(c.k==="available_fulfillment"){
        const opts=JSON.parse(v);
        const label=opts.includes("local_pickup")&&opts.includes("shipping")?"ship/pickup"
          :opts.includes("local_pickup")?"pickup":"ship";
        return '<td>'+label+'</td>';
      }
      return '<td'+(c.k==="created_at"?' class="dim"':"")+'>'+esc(v)+'</td>';}).join("");
    return '<tr data-pid="'+r.prospect_id+'" class="'+(r.is_favorite?"is-fav":"")+'">'+cells+'</tr>';}).join("");
}
async function markProspect(prospectId,status){
  try{const res=await fetch("/prospect_status",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({prospect_id:prospectId,status:status})});
    const j=await res.json();
    if(!j.ok){toast("Failed: "+j.error);return;}
    const r=PDATA.find(x=>x.prospect_id===prospectId);if(r)r.status=status;
    renderProspects();toast((status==="rejected"?"Rejected":"Restored")+" prospect #"+prospectId);
  }catch(e){toast("Failed: "+e.message);}
}
// A prospect favorite changes no score -- a local patch is enough; no refresh.
async function toggleProspectFavorite(prospectId,next){
  try{const res=await fetch("/prospect_favorite",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({prospect_id:prospectId,is_favorite:next})});
    const j=await res.json();
    if(!j.ok){toast("Failed: "+j.error);return;}
    const r=PDATA.find(x=>x.prospect_id===prospectId);if(r)r.is_favorite=next;
    renderProspects();
    toast((next?"Favorited":"Unfavorited")+" prospect #"+prospectId);
  }catch(e){toast("Failed: "+e.message);}
}
function toggle(k){if(EXPANDED.has(k))EXPANDED.delete(k);else EXPANDED.add(k);render();}
function setFilter(v){filter=v;render();}
function setCat(v){catFilter=v;render();}
function setSort(k){if(sortCol===k)sortAsc=!sortAsc;else{sortCol=k;sortAsc=false;}render();}
function toast(msg){const t=document.getElementById("toast");t.textContent=msg;t.className="show";
  clearTimeout(window._tt);window._tt=setTimeout(()=>t.className="",2200);}

async function mark(key,status){
  try{const res=await fetch("/status",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({listing_key:key,status:status})});
    const j=await res.json();
    if(!j.ok){toast("Failed: "+j.error);return;}
    const r=DATA.find(x=>x.key===key);if(r)r.status=status;
    render();toast("Marked "+key+" as "+status.replace("_"," "));
  }catch(e){toast("Failed: "+e.message);}
}
// Favoriting rescopes and rescores that seller's own live deals server-side
// (rescore_ledger.rescore_seller), so more than this one row's score can
// change -- a full refresh() is simpler and safer than a local patch.
async function toggleFavorite(source,sellerId,next){
  try{const res=await fetch("/favorite",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({source:source,seller_id:sellerId,is_favorite:next})});
    const j=await res.json();
    if(!j.ok){toast("Failed: "+j.error);return;}
    toast((next?"Favorited ":"Unfavorited ")+sellerId);
    refresh();
  }catch(e){toast("Failed: "+e.message);}
}
// Same eligibility as the per-row Reject button (rejSlot): a row already
// inquired, bid placed, purchased, or rejected has no Reject button, so it is
// not part of "all". Uses rows() -- the exact filtered/sorted set the table
// is currently rendering -- so "shown" means what Adam is actually looking at.
async function rejectAll(){
  const targets=rows().filter(r=>r.status!=="inquired"&&r.status!=="bid_placed"
    &&r.status!=="purchased"&&r.status!=="rejected");
  if(!targets.length){toast("Nothing shown is eligible to reject");return;}
  if(!confirm("Reject all "+targets.length+" deal"+(targets.length===1?"":"s")+" currently shown?"))return;
  const btn=document.getElementById("rejectall");btn.disabled=true;
  let ok=0,fail=0;
  for(const r of targets){
    try{
      const res=await fetch("/status",{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({listing_key:r.key,status:"rejected"})});
      const j=await res.json();
      if(j.ok){r.status="rejected";ok++;}else fail++;
    }catch(e){fail++;}
  }
  btn.disabled=false;
  render();
  toast("Rejected "+ok+(fail?", "+fail+" failed":""));
}
async function refresh(){const b=document.getElementById("refresh");b.disabled=true;b.textContent="↻ Refreshing…";
  try{
    if(VIEW==="prospects"){
      const res=await fetch("/prospects.json",{cache:"no-store"});
      const j=await res.json();if(j.error)throw new Error(j.error);PDATA=j.prospects;
      document.getElementById("stamp").textContent="prospects read "+j.read_at+" · "+PDATA.length+" prospects";
      renderProspects();toast("Reloaded the prospects");
    }else{
      const res=await fetch("/rows.json?all="+(showAll?"1":"0"),{cache:"no-store"});
      const j=await res.json();if(j.error)throw new Error(j.error);DATA=j.rows;
      document.getElementById("stamp").textContent="ledger read "+j.read_at+" · "+j.deal_count+" deals";
      render();toast("Reloaded from the ledger");
    }
  }catch(e){toast("Refresh failed: "+e.message);}
  b.disabled=false;b.textContent="↻ Refresh";}

// Opening a listing marks its row, so returning from the marketplace tab shows
// which one was just clicked. Class swap in place -- a re-render would reset
// scroll position for no reason.
document.getElementById("tbody").addEventListener("click",e=>{
  // Prospect rows carry no listing_key, so "where I was" is a deals-only idea.
  if(VIEW!=="deals")return;
  const a=e.target.closest("td.tc a");if(!a)return;
  const tr=a.closest("tr");if(!tr)return;
  LASTOPENED=tr.dataset.k;localStorage.setItem("ls_last_opened",LASTOPENED);
  document.querySelectorAll("tr.is-last").forEach(x=>x.classList.remove("is-last"));
  tr.classList.add("is-last");});

document.getElementById("refresh").onclick=refresh;
document.getElementById("rejectall").onclick=rejectAll;
document.getElementById("q").oninput=render;
document.getElementById("showall").onchange=e=>{showAll=e.target.checked;refresh();};
document.getElementById("firmonly").onchange=e=>{firmOnly=e.target.checked;render();};
document.getElementById("flagged").onchange=e=>{flaggedOnly=e.target.checked;render();};
document.getElementById("minprofit").onchange=e=>{minProfitOnly=e.target.checked;render();};
document.getElementById("minprice").onchange=e=>{minPriceOnly=e.target.checked;render();};
// Tabs first, and unconditionally: a failed first fetch must not be able to
// strand Adam in the deals view.
renderViewTabs();
refresh();
</script></body></html>"""


class QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # A browser closing a tab resets the SSE socket; that's expected.
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _host_ok(self):
        """The Host header has to name this server.

        A page on any domain can point that domain's A record at this
        server's bind address and then read /prospects.json from its own
        origin -- DNS rebinding. The browser sends the attacker's hostname in
        Host, so comparing it is the whole defence, and it costs one dict
        lookup.
        """
        return self.headers.get("Host") in ALLOWED_HOSTS

    def _origin_ok(self):
        """The request has to have come from the page this server serves.

        A browser sends Origin on every POST, same-origin included, so a value
        that is not ours means another page issued the write. Referer is the
        stated fallback for a client that suppresses Origin. Neither header
        means no browser sent it -- curl, a script, the e2e suite -- and those
        already run with Adam's own file access, so there is nothing to forge.
        """
        origin = self.headers.get("Origin")
        if origin is not None:
            return origin in ALLOWED_ORIGINS
        referer = self.headers.get("Referer")
        if referer is not None:
            parsed = urlparse(referer)
            return "%s://%s" % (parsed.scheme, parsed.netloc) in ALLOWED_ORIGINS
        return True

    def _fail(self, exc):
        """500 with a FIXED body; the detail goes to the server's stderr.

        The exception text carries absolute ledger paths, so returning it hands
        the internal layout of Adam's machine to whatever is rendering the
        response. stderr is where it is useful and where it is already private.
        """
        print("%s %s failed: %s: %s"
              % (self.command, self.path, type(exc).__name__, exc),
              file=sys.stderr)
        return self._send(500, json.dumps(
            {"ok": False, "error": "internal error - see the server log"}))

    def _send(self, code, body, ctype="application/json", *,
              cache_control="no-store"):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(b)

    def _send_crop(self, encoded_relative):
        try:
            relative = unquote(encoded_relative, errors="strict")
        except UnicodeDecodeError:
            return self._send(400, json.dumps({"error": "invalid crop path"}))
        if "\x00" in relative:
            # A decoded NUL terminates C-string handling in some layers and
            # must answer 400 like any other malformed request, never drop
            # the connection.
            return self._send(400, json.dumps({"error": "invalid crop path"}))
        parts = relative.split("/")
        if (not relative or relative.startswith("/") or "\\" in relative
                or any(part in ("", ".", "..") for part in parts)):
            return self._send(403, json.dumps({"error": "crop path not allowed"}))

        root = Path(CROP_ROOT).resolve()
        target = (root / relative).resolve()
        if not target.is_relative_to(root):
            return self._send(403, json.dumps({"error": "crop path not allowed"}))
        if not target.exists() or not target.is_file():
            return self._send(404, json.dumps({"error": "crop not found"}))
        ctype = CROP_TYPES.get(target.suffix.lower())
        if ctype is None:
            return self._send(415, json.dumps({"error": "unsupported crop type"}))
        try:
            body = target.read_bytes()
        except OSError:
            return self._send(404, json.dumps({"error": "crop not found"}))
        if len(body) > CROP_MAX_BYTES:
            return self._send(413, json.dumps({"error": "crop is too large"}))
        magic = CROP_MAGIC.get(ctype)
        # The extension names the type; the bytes must prove it, so arbitrary
        # payloads cannot masquerade as images behind a .jpg name.
        if magic is None or not body.startswith(magic):
            return self._send(
                415, json.dumps({"error": "crop content does not match type"}))
        cache_control = (
            "public, max-age=31536000, immutable"
            if CONTENT_HASH_CROP_RE.fullmatch(target.name) else "no-store")
        return self._send(
            200,
            body,
            ctype,
            cache_control=cache_control,
        )

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, json.dumps({"error": "host not allowed"}))
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/crops/"):
            return self._send_crop(path[len("/crops/"):])
        if path == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if path == "/rows.json":
            # Both halves read the SAME database. The rows used to come from a
            # separate node process that always read the default ledger, so a
            # DB_OVERRIDE on the count query alone made one response mix two
            # databases and report a count that contradicted its own rows.
            all_ = "all=1" in self.path
            try:
                page_rows = build_rows(active_only=not all_)
                n = ledger_db.query("SELECT COUNT(*) AS n FROM deals",
                                    path=DB_OVERRIDE)[0]["n"]
                return self._send(200, json.dumps({
                    "rows": page_rows, "deal_count": n,
                    "read_at": datetime.now().strftime("%H:%M:%S")}))
            except Exception as exc:
                return self._fail(exc)
        if path == "/prospects.json":
            try:
                rows = prospects_db.list_prospects(path=DB_OVERRIDE)
                return self._send(200, json.dumps({
                    "prospects": rows,
                    "read_at": datetime.now().strftime("%H:%M:%S")}))
            except Exception as exc:
                return self._fail(exc)
        return self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if not self._host_ok():
            return self._send(403, json.dumps({"ok": False,
                                               "error": "host not allowed"}))
        # /status and /favorite write deals; /prospect_status and
        # /prospect_favorite are Adam's Reject/Restore and ★ on a prospect
        # row. POST /prospects.json is still a 404 -- the prospect READ stays
        # exactly where it was, and these four named routes are the whole
        # write surface.
        if self.path not in ("/status", "/favorite",
                             "/prospect_status", "/prospect_favorite"):
            return self._send(404, json.dumps({"error": "not found"}))
        if not self._origin_ok():
            return self._send(403, json.dumps({"ok": False,
                                               "error": "origin not allowed"}))
        # application/json is not a CORS-safelisted content type, so demanding
        # it stops /status from being a "simple request". A cross-origin write
        # now needs a preflight, this server answers none, and the browser never
        # sends the write at all. A form POST cannot set this header, so that
        # route closes with it.
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != JSON_CTYPE:
            return self._send(415, json.dumps(
                {"ok": False, "error": "Content-Type must be application/json"}))
        try:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n)
        except Exception as exc:
            return self._fail(exc)
        try:
            payload = json.loads(raw or b"{}")
        except ValueError as exc:
            return self._send(400, json.dumps(
                {"ok": False, "error": "body is not valid JSON: %s" % exc}))
        if not isinstance(payload, dict):
            return self._send(400, json.dumps(
                {"ok": False, "error": "body must be a JSON object"}))
        try:
            if self.path == "/status":
                ok, msg = set_status(payload.get("listing_key"), payload.get("status"),
                                     DB_OVERRIDE)
            elif self.path == "/favorite":
                ok, msg = set_favorite(payload.get("source"), payload.get("seller_id"),
                                       payload.get("is_favorite"), DB_OVERRIDE)
            elif self.path == "/prospect_status":
                ok, msg = set_prospect_status(payload.get("prospect_id"),
                                              payload.get("status"), DB_OVERRIDE)
            else:
                ok, msg = set_prospect_favorite(payload.get("prospect_id"),
                                                payload.get("is_favorite"),
                                                DB_OVERRIDE)
        except Exception as exc:
            return self._fail(exc)
        return self._send(200 if ok else 400,
                          json.dumps({"ok": ok, "error": None if ok else msg}))


def main():
    global DB_OVERRIDE
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1",
                    help="Interface to bind. adam-server's pm2 deploy passes its "
                         "Tailscale IP; local debugging keeps the loopback default.")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--no-open", action="store_true")
    # Applies to EVERY read and write, /rows.json included. The rows used to
    # come from a separate node process that always read the default ledger, so
    # a split read reported a count that contradicted its own rows.
    ap.add_argument("--db", default=ledger_db.DB_PATH,
                    help="ledger path for Python-side reads/writes (tests)")
    a = ap.parse_args()
    DB_OVERRIDE = a.db
    # The RESOLVED path, not the module constant: a bad --db must fail here, at
    # startup, instead of 500-ing on the first request. Opening it is the only
    # honest test -- os.path.exists says yes to a directory and to any file that
    # is not a SQLite database, and both of those used to start a server that
    # could answer nothing.
    try:
        ledger_db.connect_readonly(DB_OVERRIDE).close()
    except Exception as exc:
        print("unusable --db %s: %s: %s"
              % (DB_OVERRIDE, type(exc).__name__, exc), file=sys.stderr)
        return 1
    # The guards in Handler compare against the host/port actually bound, so
    # they are filled here rather than at import time. `localhost` is kept as
    # an alias only for the loopback case -- nobody types "localhost" to reach
    # a Tailscale IP, so it would just be a second name that never matches.
    hosts = {"%s:%d" % (a.host, a.port)}
    if a.host in ("127.0.0.1", "localhost"):
        hosts |= {"127.0.0.1:%d" % a.port, "localhost:%d" % a.port}
    for host in hosts:
        ALLOWED_HOSTS.add(host)
        ALLOWED_ORIGINS.add("http://%s" % host)
    # Never 0.0.0.0 -- this exposes a write endpoint, so it always binds one
    # specific interface: loopback for local debugging, adam-server's
    # Tailscale IP for the deployed page. Reachability beyond that interface
    # is Tailscale's job, not this server's.
    srv = QuietServer((a.host, a.port), Handler)
    url = "http://%s:%d/" % (a.host, a.port)
    print("LEGO Scout deals page: %s" % url)
    if not a.no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
