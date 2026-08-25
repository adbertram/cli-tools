from __future__ import annotations

import itertools
import json
import os
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from PIL import Image

from legoscout_cli.display import server
from legoscout_cli.ledger import db as ledger_db
from legoscout_cli.sources import registry


PLAYWRIGHT_CLI = Path("/Users/adam/.local/bin/playwright-cli")
_HASH = "c" * 64
_SESSION_COUNTER = itertools.count()


def _crop_ref(label: str) -> str:
    digest = _HASH[:-len(label)] + label
    return f"{digest[:2]}/figcrop-v1-{digest}.jpg"


def _entry(group_id: str, crop_ref: str, *, unknown: bool = False, quantity: int = 1):
    fig_no = None if unknown else "sw0001a"
    unit = None if unknown else 12.5
    return {
        "match_group_id": group_id,
        "detections": [{
            "crop_id": "figcrop-v1-" + Path(crop_ref).stem.rsplit("-", 1)[-1],
            "source_photo_sha256": "d" * 64,
            "photo_relative_id": "photo-0001",
            "box": [0.1, 0.1, 0.4, 0.8],
            "detector_name": "grounding-dino-tiny",
            "detector_version": "v1",
            "detector_confidence": 0.9,
            "crop_ref": crop_ref,
        }],
        "representative_crop_ref": crop_ref,
        "brickognize_candidates": [],
        "verification": {
            "status": "unknown" if unknown else "verified",
            "reason": "no confident identity" if unknown else "catalog confirmed",
            "compared_candidate_ids": [] if unknown else [fig_no],
            "catalog_checked_at": "2026-08-25T00:00:00Z",
        },
        "fig_no": fig_no,
        "catalog": None if unknown else {"no": fig_no, "name": "Stormtrooper"},
        "quantity": quantity,
        "condition_notes": None if unknown else "Light play wear",
        "used": None if unknown else {"avg_price": unit, "price_detail_count": 8},
        "unit_value": unit,
        "extended_value": None if unit is None else unit * quantity,
        "null_value_reason": "unknown_identity" if unknown else None,
        "errors": [],
    }


def _base_deal(key: str, title: str):
    return {
        "listing_key": key,
        "source": "k-bid",
        "title": title,
        "url": "https://example.invalid/listing",
        "direct_url": "https://example.invalid/listing",
        "status": "active",
        "listing_type": "fixed",
        "listing_category": "minifigure",
        "estimated_total": 20.0,
        "potential_profit": 55.0,
        "profit_incomplete": True,
        "figure_count": 10,
        "figure_count_source": "detection",
        "fee_breakdown": {
            "hammer": 20.0,
            "premium_pct": 0.0,
            "sales_tax_pct": 0.0,
            "shipping_handling": 0.0,
        },
        "available_fulfillment": ["shipping"],
        "scoring": {
            "score": 80,
            "category": "minifigure",
            "quality": 75,
            "max_price": 60.0,
            "unscorable": None,
        },
        "observations": {"vision": {"status": "observed"}},
    }


def _identified_deal():
    deal = _base_deal("k-bid|browser-new", "Ten identified and unknown minifigures")
    deal["minifig_analysis"] = [
        _entry("g1", _crop_ref("01"), quantity=6),
        _entry("g2", _crop_ref("02"), unknown=True, quantity=4),
    ]
    # These legacy values must never leak into an identifier-backed row.
    deal["ebay_avg_price_per_fig"] = 99.0
    deal["ebay_comp_count"] = 999
    return deal


def _legacy_deal():
    deal = _base_deal("k-bid|browser-legacy", "Legacy minifigure lot")
    deal.update({
        "figure_count": 3,
        "figure_count_source": "stated",
        "ebay_avg_price_per_fig": 7.5,
        "ebay_comp_count": 11,
    })
    return deal


def _seed(db_path: Path, deal: dict):
    ledger_db.init(str(db_path)).close()
    with registry._connect(str(db_path)) as conn:
        conn.execute(
            "INSERT INTO sources(namespace, payload) VALUES (?, ?)",
            ("k-bid", json.dumps({
                "short": "K-BID",
                "capability": {"can_offer": False},
            })),
        )
        conn.commit()
    ledger_db.upsert_deals([deal], path=str(db_path))


@contextmanager
def _scratch_server(monkeypatch, tmp_path: Path, deal: dict, *, with_crops: bool):
    db_path = tmp_path / "ledger.db"
    crop_root = tmp_path / "crops"
    crop_root.mkdir()
    if with_crops:
        for relative, color in ((_crop_ref("01"), "red"), (_crop_ref("02"), "blue")):
            path = crop_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (12, 12), color=color).save(path, format="JPEG")
    _seed(db_path, deal)

    monkeypatch.setattr(server, "DB_OVERRIDE", str(db_path))
    monkeypatch.setattr(server, "CROP_ROOT", crop_root)
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    host = f"127.0.0.1:{httpd.server_port}"
    monkeypatch.setattr(server, "ALLOWED_HOSTS", {host})
    monkeypatch.setattr(server, "ALLOWED_ORIGINS", {f"http://{host}"})
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{host}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def _session() -> str:
    return f"mh{os.getpid() % 10000}{next(_SESSION_COUNTER)}"


def _pw(session: str, *args: str):
    assert PLAYWRIGHT_CLI.is_file()
    result = subprocess.run(
        [str(PLAYWRIGHT_CLI), f"-s={session}", *args, "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"playwright-cli {' '.join(args)} failed rc={result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert result.stdout.strip(), f"playwright-cli {' '.join(args)} returned no JSON"
    payload = json.loads(result.stdout)
    assert "error" not in payload, payload
    return payload


def _result(payload) -> Any:
    value = payload.get("result")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _close(session: str):
    subprocess.run(
        [str(PLAYWRIGHT_CLI), f"-s={session}", "close", "--json"],
        check=False,
        capture_output=True,
        text=True,
    )


def test_should_expand_and_render_identifier_backed_minifigures_in_real_browser(
    monkeypatch, tmp_path,
):
    with _scratch_server(
        monkeypatch, tmp_path, _identified_deal(), with_crops=True,
    ) as base_url:
        session = _session()
        try:
            _pw(session, "open", base_url, "--browser", "chrome")
            _pw(
                session,
                "run-code",
                "async (page) => { await page.locator('tr[data-k=\"k-bid|browser-new\"]').waitFor(); return true; }",
            )
            before = _result(_pw(
                session,
                "eval",
                "() => ({header: document.querySelector('#thead').innerText, targetInputs: document.querySelectorAll('tr[data-k=\"k-bid|browser-new\"] .tlb input').length})",
            ))
            assert "$ / lb" in before["header"]
            assert "$ / lb·fig" not in before["header"]
            assert before["targetInputs"] == 0

            # The dropdown must work through a real user click, not direct DOM mutation.
            _pw(session, "click", 'tr[data-k="k-bid|browser-new"] .exp')
            _pw(session, "snapshot")
            detail_text = _result(_pw(
                session, "eval", "() => document.querySelector('tr.det').innerText"))

            assert "6 identified · 4 unknown" in detail_text
            assert "identification incomplete" in detail_text
            assert "Identified subtotal" in detail_text
            assert "$75.00" in detail_text
            assert "Identity" in detail_text
            assert "sw0001a" in detail_text
            assert "Name" in detail_text
            assert "Stormtrooper" in detail_text
            assert "Qty" in detail_text
            assert "6" in detail_text
            assert "Unit value" in detail_text
            assert "$12.50" in detail_text
            assert "Extended value" in detail_text
            assert "Market depth" in detail_text
            assert "8 sold" in detail_text
            assert "Condition notes" in detail_text
            assert "Light play wear" in detail_text
            assert "Unknown" in detail_text
            assert "eBay $/fig" not in detail_text
            assert "eBay comps" not in detail_text

            images = _result(_pw(
                session,
                "eval",
                "() => Array.from(document.querySelectorAll('tr.det img.minifig-crop')).map(image => ({alt: image.alt, visible: !!(image.offsetWidth || image.offsetHeight || image.getClientRects().length), loaded: image.complete && image.naturalWidth > 0}))",
            ))
            assert images == [
                {"alt": "Stormtrooper crop", "visible": True, "loaded": True},
                {"alt": "Unknown minifigure crop", "visible": True, "loaded": True},
            ]
            unknown_text = _result(_pw(
                session,
                "eval",
                "() => document.querySelector('[data-fig-status=\"unknown\"]').innerText",
            ))
            assert "Qty\n4" in unknown_text
            assert "Unit value\n—" in unknown_text
            assert "Extended value\n—" in unknown_text
            assert "Market depth\n—" in unknown_text
        finally:
            _close(session)


def test_should_render_legacy_per_figure_fields_only_without_analysis_in_real_browser(
    monkeypatch, tmp_path,
):
    with _scratch_server(
        monkeypatch, tmp_path, _legacy_deal(), with_crops=False,
    ) as base_url:
        session = _session()
        try:
            _pw(session, "open", base_url, "--browser", "chrome")
            _pw(
                session,
                "run-code",
                "async (page) => { await page.locator('tr[data-k=\"k-bid|browser-legacy\"]').waitFor(); return true; }",
            )
            _pw(session, "click", 'tr[data-k="k-bid|browser-legacy"] .exp')
            detail_text = _result(_pw(
                session, "eval", "() => document.querySelector('tr.det').innerText"))
            page_state = _result(_pw(
                session,
                "eval",
                "() => ({header: document.querySelector('#thead').innerText, figures: document.querySelectorAll('tr.det .fig-entry').length, targetInputs: document.querySelectorAll('tr[data-k=\"k-bid|browser-legacy\"] .tlb input').length})",
            ))

            assert "Figure count" in detail_text
            assert "3" in detail_text
            assert "Legacy eBay $/fig" in detail_text
            assert "$7.50" in detail_text
            assert "Legacy eBay comps" in detail_text
            assert "11" in detail_text
            assert "identified" not in detail_text
            assert page_state["figures"] == 0
            assert page_state["targetInputs"] == 0
            assert "$ / lb" in page_state["header"]
            assert "$ / lb·fig" not in page_state["header"]
        finally:
            _close(session)
