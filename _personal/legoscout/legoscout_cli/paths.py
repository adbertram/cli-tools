"""Every canonical path and constant LegoScout reads. Nothing else hardcodes one.

The data stays in the LegoScout project. Only the CODE moved into this tool, so
`DB_PATH` still points at the working repo's ledger and the caches still land
beside it. Package data (the deal schema, the pickup area, the curated seller
origins, the hypothesis registry, the triage rules) travels with the package and
is resolved relative to this file.
"""
from __future__ import annotations

from pathlib import Path

PKG = Path(__file__).resolve().parent

# --- the LegoScout project ---------------------------------------------------

LEGOSCOUT_ROOT = Path("/Users/adam/Dropbox/GitRepos/Agents/LegoScout")

DB_PATH = str(LEGOSCOUT_ROOT / "data" / "found_deals.db")
SHIPPING_RATE_CACHE = str(LEGOSCOUT_ROOT / "data" / ".shipping_rate_cache.json")
BRICKLINK_CALL_CACHE = str(LEGOSCOUT_ROOT / "data" / ".bricklink_call_cache.json")
EBAY_COMP_CALL_CACHE = str(LEGOSCOUT_ROOT / "data" / ".ebay_comp_call_cache.json")
LISTING_IMAGES_ROOT = str(LEGOSCOUT_ROOT / "agent_workspaces" / "listing-images")
MINIFIG_EVAL_WORKSPACE = "/Users/adam/Dropbox/GitRepos/Agents/LegoScout/agent_workspaces/minifig-eval"
MINIFIG_CROP_ROOT = "/Users/adam/Dropbox/GitRepos/Agents/LegoScout/agent_workspaces/shared/minifig-crops"
BRICKOGNIZE_MINIFIG_CACHE = "/Users/adam/Dropbox/GitRepos/Agents/LegoScout/data/.brickognize_minifig_cache.json"
SOURCE_RUNS = str(LEGOSCOUT_ROOT / "agent_workspaces" / "source-runs")

# --- package data ------------------------------------------------------------

DEAL_SCHEMA_JSON = str(PKG / "ledger" / "deal_schema.json")
PICKUP_AREA_JSON = str(PKG / "pricing" / "pickup_area.json")
SELLER_ORIGINS_JSON = str(PKG / "pricing" / "seller_origins.json")
HYPOTHESIS_TYPES_JSON = str(PKG / "prospector" / "hypothesis_types.json")
PROSPECT_AREA_JSON = str(PKG / "prospector" / "prospect_area.json")
TRIAGE_RULES_JSON = str(PKG / "sources" / "triage_rules.json")

# --- the one ship-to destination ---------------------------------------------

DEST_ZIP = "47725"
DEST = {"name": "Adam Bertram", "address": "PO Box", "city": "Evansville",
        "state": "IN", "zip": DEST_ZIP}
