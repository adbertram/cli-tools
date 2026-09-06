"""`legoscout pricing` -- fees, landed cost, comps, freight, images, pickup area."""
from __future__ import annotations

import json
import sys
from typing import List, Optional

import typer
from cli_tools_shared.output import command, print_json

from .. import delegate
from ..pricing import build_pickup_area, fees as fees_module
from ..pricing import (
    inbound_shipping,
    listing_images,
    pickup_area as pickup_module,
)
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
    if (shipping is not None) == shipping_unknown:
        raise typer.BadParameter(
            "pass exactly one of --shipping / --shipping-unknown")
    b = fees_module.landed_cost(
        source, hammer, None if shipping_unknown else shipping,
        handling if handling is not None else 0.0,
        premium_pct, sales_tax_pct,
        buyer_protection_fee=buyer_protection_fee)
    # allow_nan=False: stdout is contracted to be ONE parseable JSON object,
    # and Python's default writes NaN/Infinity, which no other parser reads.
    print(json.dumps(b, indent=2, allow_nan=False))
    # The one-line explanation goes to STDERR, never stdout, so
    # `legoscout pricing landed-cost ... | json.loads` never sees trailing text.
    print(fees_module.explain(b), file=sys.stderr)


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
    if condition not in ("N", "U"):
        raise typer.BadParameter("--condition must be 'N' or 'U'")
    try:
        result = set_sales.cli_summarize(
            set_no, condition, purchase_price=purchase_price,
            fee_rate=fee_rate, no_cache=refresh)
    except set_sales.LookupFailed as exc:
        print(str(exc), file=sys.stderr)
        raise typer.Exit(1) from exc
    print_json(result)


@app.command("ebay-comps")
@command
def ebay_comps_command(
    set_no: Optional[str] = typer.Argument(
        None, help="A LEGO set number. Required unless --bulk"),
    bulk: bool = typer.Option(
        False, "--bulk", help="Bulk-lot mode: match by weight, not a set number"),
    condition: Optional[str] = typer.Option(
        None, "--condition", help="N or U. Required unless --bulk"),
    description: Optional[str] = typer.Option(
        None, "--description",
        help="Extra search keywords: set name/theme or bulk lot description"),
    dollars_per_lb: Optional[float] = typer.Option(
        None, "--dollars-per-lb",
        help="Bulk mode only: the target listing's own $/lb, for comparison"),
    limit: int = typer.Option(50, "--limit", help="Max eBay results to search"),
):
    """eBay sold comps for one LEGO set or one bulk lot with --bulk.

    Never fails on an eBay auth lapse -- returns `{"available": false,
    "reason": "ebay_auth_required", ...}` instead. Run `ebay auth login
    --credential-type browser_session` to authenticate completed/sold search.
    """
    if bulk:
        print_json(ebay_comps.search_bulk_comps(
            description, dollars_per_lb=dollars_per_lb, limit=limit))
        return
    if not set_no or not condition:
        raise typer.BadParameter("set_no and --condition are required unless --bulk")
    if condition not in ("N", "U"):
        raise typer.BadParameter("--condition must be 'N' or 'U'")
    print_json(ebay_comps.search_set_comps(
        set_no, condition, description=description, limit=limit))


@app.command("comps")
@command
def comps_command(
    set_no: Optional[List[str]] = typer.Option(
        None, "--set-no",
        help="A LEGO set number. Repeatable -- pass it once per detected set on a "
             "multi-set listing. Required unless --bulk"),
    bulk: bool = typer.Option(
        False, "--bulk", help="Bulk-lot mode: eBay $/lb comps only, no BrickLink"),
    condition: Optional[str] = typer.Option(
        None, "--condition", help="N or U. Required unless --bulk"),
    description: Optional[str] = typer.Option(
        None, "--description",
        help="Extra search keywords: set name/theme or bulk lot description"),
    dollars_per_lb: Optional[float] = typer.Option(
        None, "--dollars-per-lb",
        help="Bulk mode only: the target listing's own $/lb, for comparison"),
    limit: int = typer.Option(50, "--limit", help="Max eBay results to search"),
):
    """BrickLink + eBay sold comps for sets, or eBay-only for a bulk lot.

    The single command the comps-only appraiser calls. Pass --set-no once per
    detected set number; a single-set listing still passes it once. BrickLink
    and eBay are independent lookups -- one failing never blocks the other;
    read `bricklink.lookup_status` and `ebay.available` separately per set.
    """
    if bulk:
        if not description:
            raise typer.BadParameter("--description is required in --bulk mode")
        print_json(comps_module.bulk_comps(
            description, dollars_per_lb=dollars_per_lb, limit=limit))
        return
    if not set_no or not condition:
        raise typer.BadParameter(
            "--set-no (repeatable) and --condition are required unless --bulk")
    if condition not in ("N", "U"):
        raise typer.BadParameter("--condition must be 'N' or 'U'")
    print_json(comps_module.set_comps(
        set_no, condition, description=description, limit=limit))


@app.command("comps-batch")
@command
def comps_batch_command(
    input: str = typer.Option(
        ..., "--input", metavar="FILE",
        help="JSON array file of classifier comps hand-offs: listing_key, "
             "listing_category, and set_numbers/condition/description (set), "
             "description/dollars_per_lb (bulk), or exclusion_reason (excluded)"),
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
    try:
        print_json(comps_batch_module.run_comps_batch_cli(
            input, output, workers=workers, limit=limit))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise typer.Exit(1) from exc


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
    print_json(profit_module.compute_potential_profit(
        avg_price, price_detail_count, estimated_total, fee_rate))


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
    if weight_lbs is None:
        raise typer.BadParameter("--weight-lbs is required")
    try:
        zip_, city, state = inbound_shipping.resolve_origin(
            origin_zip, origin_city or "", origin_state or "", house, hibid_lot)
    except inbound_shipping.OriginError as exc:
        print(str(exc), file=sys.stderr)
        raise typer.Exit(1) from exc
    out = inbound_shipping.quote(zip_, city, state, weight_lbs, refresh)
    print(json.dumps(out, indent=2))
    if "error" not in out:
        # STDERR, so stdout stays one parseable JSON object.
        print("\n$%.2f %s %s + $%.2f assumed handling = $%.2f estimated inbound"
              % (out["carrier_rate"], out["carrier"], out["service"],
                 out["handling_assumed"], out["estimated_total"]),
              file=sys.stderr)


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
    code = listing_images.discover_and_fetch(url=url, key=key, urls=urls, max=max)
    if code:
        raise typer.Exit(code)


@app.command("pickup-area")
@command
def pickup_area(
    location: str = typer.Argument(..., help="A stated listing location"),
):
    """Can Adam drive there? Resolves a stated location against the radius.

    A bare town name raises: Chandler IN is 15 miles away and Chandler AZ is
    1,500.
    """
    try:
        print_json(pickup_module.resolve(location))
    except ValueError as exc:
        print("pickup_area: %s" % exc, file=sys.stderr)
        raise typer.Exit(1) from exc


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
    kwargs = {k: v for k, v in {
        "radius_miles": radius_miles, "csv": csv, "zcta_place": zcta_place,
        "place_gazetteer": place_gazetteer, "geonames": geonames, "out": out,
    }.items() if v is not None}
    try:
        build_pickup_area.build(**kwargs)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise typer.Exit(1) from exc


