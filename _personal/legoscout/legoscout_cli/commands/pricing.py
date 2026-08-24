"""`legoscout pricing` -- fees, landed cost, comps, freight, images, pickup area."""
from __future__ import annotations

from typing import List, Optional

import typer
from cli_tools_shared.output import command, print_json

from .. import delegate
from ..pricing import auctionninja_fees, build_pickup_area, fees as fees_module
from ..pricing import inbound_shipping, listing_images, pickup_area as pickup_module
from ..pricing import set_sales
from ..pricing import comps as comps_module
from ..pricing import comps_batch as comps_batch_module
from ..pricing import ebay_comps
from ..pricing import preflight as preflight_module
from ..pricing import profit as profit_module

COMMAND_CREDENTIALS = ["no_auth"]

app = typer.Typer(help="Deal economics: fees, landed cost, comps and freight",
                  no_args_is_help=True)


@app.command("fees")
@command
def fees(
    source: str = typer.Option(..., "--source", help="A namespace or listing_key"),
):
    """The published fee configuration for one source."""
    print_json(fees_module.config(source))


@app.command("landed-cost")
@command
def landed_cost(
    source: str = typer.Option(..., "--source", help="A namespace or listing_key"),
    hammer: float = typer.Option(..., "--hammer", help="The price actually paid"),
    shipping: Optional[float] = typer.Option(
        None, "--shipping", help="Known freight; omit with --shipping-unknown"),
    shipping_unknown: bool = typer.Option(
        False, "--shipping-unknown",
        help="No freight is known, so the landed total is a FLOOR"),
    handling: Optional[float] = typer.Option(None, "--handling", help="Handling fee"),
    premium_pct: Optional[float] = typer.Option(
        None, "--premium-pct", help="Override the source's buyer premium"),
    sales_tax_pct: Optional[float] = typer.Option(
        None, "--sales-tax-pct", help="Override the source's sales tax"),
    buyer_protection_fee: Optional[float] = typer.Option(
        None, "--buyer-protection-fee",
        help="The listing's numeric buyer protection fee"),
):
    """Landed cost from a hammer price plus whatever freight is known.

    An unknown freight cost is NEVER passed as 0.0: the row is marked
    `shipping_unknown` and `landed_is_floor` instead.
    """
    argv = ["--source", source, "--hammer", str(hammer)]
    if shipping_unknown:
        argv.append("--shipping-unknown")
    else:
        delegate.option(argv, "--shipping", shipping)
    delegate.option(argv, "--handling", handling)
    delegate.option(argv, "--premium-pct", premium_pct)
    delegate.option(argv, "--sales-tax-pct", sales_tax_pct)
    delegate.option(argv, "--buyer-protection-fee", buyer_protection_fee)
    delegate.run(fees_module, argv)


@app.command("set-sales")
@command
def set_sales_command(
    set_no: str = typer.Argument(..., help="A LEGO set number"),
    condition: str = typer.Option(..., "--condition", help="N or U"),
    purchase_price: Optional[float] = typer.Option(
        None, "--purchase-price",
        help="Landed cost of the lot. Omit together with --fee-rate for a "
             "comps-only lookup with no potential_profit"),
    fee_rate: Optional[float] = typer.Option(
        None, "--fee-rate",
        help="Resale fee rate. Omit together with --purchase-price"),
    refresh: bool = typer.Option(
        False, "--refresh",
        help="Call BrickLink directly, ignoring and not writing the call cache"),
):
    """BrickLink sold comps for one set number.

    The flag is `--refresh`, not `--no-cache`. `cli_tools_shared.create_app`
    registers `--no-cache` as an APP-level option and `_hoist_no_cache_flag()`
    moves the token to the front of `sys.argv`, so a subcommand of the same
    name never receives it. This one was silently inert until 2026-08-06.
    """
    argv = [set_no, "--condition", condition]
    delegate.option(argv, "--purchase-price", purchase_price)
    delegate.option(argv, "--fee-rate", fee_rate)
    delegate.flag(argv, "--no-cache", refresh)
    delegate.run(set_sales, argv)


@app.command("ebay-comps")
@command
def ebay_comps_command(
    set_no: Optional[str] = typer.Argument(
        None, help="A LEGO set number. Required unless --bulk or --minifigure"),
    bulk: bool = typer.Option(
        False, "--bulk", help="Bulk-lot mode: match by weight, not a set number"),
    minifigure: bool = typer.Option(
        False, "--minifigure",
        help="Minifigure-lot mode: match by figure count, not a set number"),
    condition: Optional[str] = typer.Option(
        None, "--condition", help="N or U. Required unless --bulk or --minifigure"),
    description: Optional[str] = typer.Option(
        None, "--description",
        help="Extra search keywords: set name/theme, bulk lot description, "
             "or minifigure theme/name"),
    dollars_per_lb: Optional[float] = typer.Option(
        None, "--dollars-per-lb",
        help="Bulk mode only: the target listing's own $/lb, for comparison"),
    limit: int = typer.Option(50, "--limit", help="Max eBay results to search"),
):
    """eBay sold comps for one LEGO set, one bulk lot with --bulk, or one
    minifigure lot with --minifigure.

    Never fails on an eBay auth lapse -- returns `{"available": false,
    "reason": "ebay_auth_required", ...}` instead. Run `ebay auth login
    --credential-type browser_session` to authenticate completed/sold search.
    """
    argv = []
    if set_no:
        argv.append(set_no)
    delegate.flag(argv, "--bulk", bulk)
    delegate.flag(argv, "--minifigure", minifigure)
    delegate.option(argv, "--condition", condition)
    delegate.option(argv, "--description", description)
    delegate.option(argv, "--dollars-per-lb", dollars_per_lb)
    delegate.option(argv, "--limit", limit)
    delegate.run(ebay_comps, argv)


@app.command("comps")
@command
def comps_command(
    set_no: Optional[List[str]] = typer.Option(
        None, "--set-no",
        help="A LEGO set number. Repeatable -- pass it once per detected set on a "
             "multi-set listing. Required unless --bulk or --minifigure"),
    bulk: bool = typer.Option(
        False, "--bulk", help="Bulk-lot mode: eBay $/lb comps only, no BrickLink"),
    minifigure: bool = typer.Option(
        False, "--minifigure",
        help="Minifigure-lot mode: eBay $/fig comps only, no BrickLink"),
    condition: Optional[str] = typer.Option(
        None, "--condition", help="N or U. Required unless --bulk or --minifigure"),
    description: Optional[str] = typer.Option(
        None, "--description",
        help="Extra search keywords: set name/theme, bulk lot description, "
             "or minifigure theme/name"),
    dollars_per_lb: Optional[float] = typer.Option(
        None, "--dollars-per-lb",
        help="Bulk mode only: the target listing's own $/lb, for comparison"),
    limit: int = typer.Option(50, "--limit", help="Max eBay results to search"),
):
    """BrickLink + eBay sold comps for a LEGO set (or several, on one listing),
    eBay-only for a bulk lot, or eBay-only $/fig for a minifigure lot.

    The single command the comps-only appraiser calls. Pass --set-no once per
    detected set number; a single-set listing still passes it once. BrickLink
    and eBay are independent lookups -- one failing never blocks the other;
    read `bricklink.lookup_status` and `ebay.available` separately per set.
    """
    argv = []
    if set_no:
        for one in set_no:
            argv.extend(["--set-no", one])
    delegate.flag(argv, "--bulk", bulk)
    delegate.flag(argv, "--minifigure", minifigure)
    delegate.option(argv, "--condition", condition)
    delegate.option(argv, "--description", description)
    delegate.option(argv, "--dollars-per-lb", dollars_per_lb)
    delegate.option(argv, "--limit", limit)
    delegate.run(comps_module, argv)


@app.command("comps-batch")
@command
def comps_batch_command(
    input: str = typer.Option(
        ..., "--input", metavar="FILE",
        help="JSON array file of the classifier's comps hand-offs: listing_key, "
             "listing_category, and set_numbers/condition/description (set), "
             "description/dollars_per_lb (bulk), description/figure_count/"
             "figure_count_source (minifigure), or exclusion_reason (excluded)"),
    output: str = typer.Option(
        ..., "--output", metavar="FILE",
        help="Write the full batch JSON here (timings + one result per candidate)"),
    workers: int = typer.Option(
        comps_batch_module.DEFAULT_WORKERS, "--workers",
        help="Concurrent candidates. Keep narrow: eBay is a browser-session scrape"),
    limit: int = typer.Option(50, "--limit", help="Max eBay results per search"),
):
    """Price a whole appraiser batch in ONE call: BrickLink + eBay sold comps
    for every candidate, concurrently.

    Each result is exactly what `legoscout pricing comps` would print for that
    candidate, plus `listing_key`. One candidate's failure becomes that
    candidate's `blocked` result -- it never fails the batch. The root
    `timings` object reports wall seconds vs the serial equivalent, so batch
    sizing stays a measurement.
    """
    delegate.run(comps_batch_module,
                 ["--input", input, "--output", output,
                  "--workers", str(workers), "--limit", str(limit)])


@app.command("preflight")
@command
def preflight(
    profile: Optional[str] = typer.Option(
        None, "--profile",
        help="Check this profile on the authed tools instead of each tool's own active profile"),
    source: Optional[list[str]] = typer.Option(
        None, "--source", metavar="NS",
        help="Scope the source-CLI and fee-config checks to this active "
             "namespace instead of every active source. Repeatable. Match a "
             "planned selected-source run; omit for an all-active run."),
):
    """Mandatory FULL pre-run gate for a deal run.

    Verifies EVERY dependency a run touches before any source worker starts:
    BrickLink and eBay live auth, every planned CLI-first source's binary
    (plus live auth where the registry requires it), the runtime headless
    browser, adam-server SSH + the deployed display app's pm2 process,
    source-registry structure and researched fee configs, ledger working
    copy writability, all four custom-agent definitions on both harnesses
    plus hard-rules parity, the nine project skills, the global agent
    standards file, and the run workspace directories. A session-wide eBay
    auth lapse looks identical to a per-candidate miss inside any one comps
    call -- this gate catches it at the door instead of 20 candidates deep.
    Exits non-zero on any blocker; warnings (unresearched fee configs, dead
    Gmail outreach) are reported without failing the run. Pass --source once
    per namespace for a selected-source run; omit it for an all-active run.
    """
    argv = []
    delegate.option(argv, "--profile", profile)
    for namespace in source or []:
        argv.extend(["--source", namespace])
    delegate.run(preflight_module, argv)


@app.command("profit")
@command
def profit_command(
    estimated_total: float = typer.Option(
        ..., "--estimated-total", help="Landed cost"),
    fee_rate: float = typer.Option(
        ..., "--fee-rate", help="Resale fee rate, as a decimal"),
    avg_price: Optional[float] = typer.Option(
        None, "--avg-price",
        help="Selected-condition six-month avg sold price; omit for 'no comp'"),
    price_detail_count: Optional[int] = typer.Option(
        None, "--price-detail-count", help="How many sold listings backed --avg-price"),
):
    """Net-of-fees profit from a comp average, landed cost, and fee rate.

    Pure math -- no network call. The one place the orchestrator turns a
    classifier's landed cost plus an appraiser's comp average into
    `potential_profit`, so the two agents' outputs never get hand-merged.
    """
    argv = ["--estimated-total", str(estimated_total), "--fee-rate", str(fee_rate)]
    delegate.option(argv, "--avg-price", avg_price)
    delegate.option(argv, "--price-detail-count", price_detail_count)
    delegate.run(profit_module, argv)


@app.command("shipping")
@command
def shipping(
    origin_zip: Optional[str] = typer.Option(None, "--origin-zip", help="Ship-from ZIP"),
    origin_city: Optional[str] = typer.Option(None, "--origin-city", help="Ship-from city"),
    origin_state: Optional[str] = typer.Option(None, "--origin-state", help="Ship-from state"),
    house: Optional[str] = typer.Option(
        None, "--house", help="A curated auction house name from seller_origins.json"),
    hibid_lot: Optional[str] = typer.Option(
        None, "--hibid-lot", help="Read the origin off a HiBid lot"),
    weight_lbs: Optional[float] = typer.Option(None, "--weight-lbs", help="Parcel weight"),
    refresh: bool = typer.Option(
        False, "--refresh", help="Re-quote the carrier, ignoring the rate cache"),
):
    """A carrier rate for a listing whose SOURCE publishes none.

    Auction houses invoice freight after the sale, so the rate that decides the
    bid does not exist at bid time. A row with no stated weight cannot be
    quoted, and this NEVER invents one.

    The flag is `--refresh`, not `--no-cache`: `cli_tools_shared` hoists a
    `--no-cache` token to the front of `sys.argv` for its own app-level option,
    so a subcommand flag of that name never arrives.
    """
    argv = []
    delegate.option(argv, "--origin-zip", origin_zip)
    delegate.option(argv, "--origin-city", origin_city)
    delegate.option(argv, "--origin-state", origin_state)
    delegate.option(argv, "--house", house)
    delegate.option(argv, "--hibid-lot", hibid_lot)
    delegate.option(argv, "--weight-lbs", weight_lbs)
    delegate.flag(argv, "--no-cache", refresh)
    delegate.run(inbound_shipping, argv)


@app.command("images")
@command
def images(
    url: Optional[str] = typer.Option(None, "--url", help="A listing URL to read"),
    key: Optional[str] = typer.Option(None, "--key", help="A ledger listing_key"),
    urls: Optional[List[str]] = typer.Option(
        None, "--urls", help="Explicit image URLs (repeatable)"),
    max: Optional[int] = typer.Option(None, "--max", help="Stop after this many images"),
):
    """Fetch a listing's images for the vision pass."""
    argv = []
    delegate.option(argv, "--url", url)
    delegate.option(argv, "--key", key)
    if urls:
        argv.append("--urls")
        argv.extend(urls)
    delegate.option(argv, "--max", max)
    delegate.run(listing_images, argv)


@app.command("pickup-area")
@command
def pickup_area(
    location: str = typer.Argument(..., help="A stated listing location"),
):
    """Can Adam drive there? Resolves a stated location against the radius.

    A bare town name raises: Chandler IN is 15 miles away and Chandler AZ is
    1,500.
    """
    delegate.run(pickup_module, [location])


@app.command("rebuild-pickup-area")
@command
def rebuild_pickup_area(
    radius_miles: Optional[float] = typer.Option(
        None, "--radius-miles", help="The drive radius to build for"),
    csv: Optional[str] = typer.Option(None, "--csv", help="ZIP centroid CSV"),
    zcta_place: Optional[str] = typer.Option(None, "--zcta-place", help="ZCTA place file"),
    place_gazetteer: Optional[str] = typer.Option(
        None, "--place-gazetteer", help="Census place gazetteer"),
    geonames: Optional[str] = typer.Option(None, "--geonames", help="GeoNames dump"),
    out: Optional[str] = typer.Option(None, "--out", help="Write the table here"),
):
    """Rebuild the pickup-area table from the public geography sources."""
    argv = []
    delegate.option(argv, "--radius-miles", radius_miles)
    delegate.option(argv, "--csv", csv)
    delegate.option(argv, "--zcta-place", zcta_place)
    delegate.option(argv, "--place-gazetteer", place_gazetteer)
    delegate.option(argv, "--geonames", geonames)
    delegate.option(argv, "--out", out)
    delegate.run(build_pickup_area, argv)


@app.command("auctionninja-fees")
@command
def auctionninja(
    url: Optional[str] = typer.Option(None, "--url", help="One AuctionNinja lot URL"),
    batch: Optional[str] = typer.Option(None, "--batch", metavar="FILE",
                                        help="A file of lot URLs"),
    weight_lbs: Optional[float] = typer.Option(
        None, "--weight-lbs", help="Estimate inbound freight at this weight"),
    register: bool = typer.Option(
        False, "--register", help="Persist the discovered house record"),
):
    """Discover an AuctionNinja house's published premium, tax and origin."""
    argv = []
    delegate.option(argv, "--url", url)
    delegate.option(argv, "--batch", batch)
    delegate.option(argv, "--weight-lbs", weight_lbs)
    delegate.flag(argv, "--register", register)
    delegate.run(auctionninja_fees, argv)
