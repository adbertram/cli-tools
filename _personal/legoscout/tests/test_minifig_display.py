from __future__ import annotations

import http.client
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import pytest

from legoscout_cli.display import rows
from legoscout_cli.display import server
from legoscout_cli.ledger import db as ledger_db
from legoscout_cli.ledger import minifig_analysis


_HASH = "a" * 64


class _Registry:
    def entry(self, _listing_key):
        return {
            "short": "K-BID",
            "capability": {"can_offer": False},
        }


def _crop_ref(label: str, suffix: str = ".jpg") -> str:
    digest = (_HASH[:-len(label)] + label).lower()
    return f"{digest[:2]}/figcrop-v1-{digest}{suffix}"


def _detection(crop_ref: str):
    return {
        "crop_id": "figcrop-v1-" + Path(crop_ref).stem.rsplit("-", 1)[-1],
        "source_photo_sha256": "b" * 64,
        "photo_relative_id": "photo-0001",
        "box": [0.1, 0.1, 0.4, 0.8],
        "detector_name": "grounding-dino-tiny",
        "detector_version": "v1",
        "detector_confidence": 0.9,
        "crop_ref": crop_ref,
    }


def _analysis_entry(
    group_id: str,
    crop_ref: str,
    *,
    quantity: int = 1,
    fig_no: str | None = "sw0001a",
    name: str | None = "Stormtrooper",
    unit_value: float | None = 12.5,
    sold_count: int | None = 8,
    condition_notes: str | None = "Light play wear",
):
    verified = fig_no is not None
    return {
        "match_group_id": group_id,
        "detections": [_detection(crop_ref)],
        "representative_crop_ref": crop_ref,
        "brickognize_candidates": [],
        "verification": {
            "status": "verified" if verified else "unknown",
            "reason": "catalog confirmed" if verified else "no confident identity",
            "compared_candidate_ids": [fig_no] if verified else [],
            "catalog_checked_at": "2026-08-25T00:00:00Z",
        },
        "fig_no": fig_no,
        "catalog": {"no": fig_no, "name": name} if verified else None,
        "quantity": quantity,
        "condition_notes": condition_notes,
        "used": ({
            "avg_price": unit_value,
            "price_detail_count": sold_count,
        } if unit_value is not None else None),
        "unit_value": unit_value,
        "extended_value": (
            round(unit_value * quantity, 2) if unit_value is not None else None),
        "null_value_reason": None if unit_value is not None else "unknown_identity",
        "errors": [],
    }


def _deal(*, analysis=True):
    deal = {
        "listing_key": "k-bid|display-1",
        "source": "k-bid",
        "title": "Ten minifigures",
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
    if analysis:
        deal["minifig_analysis"] = [
            _analysis_entry("g1", _crop_ref("01"), quantity=6),
            _analysis_entry(
                "g2", _crop_ref("02"), quantity=4, fig_no=None, name=None,
                unit_value=None, sold_count=None, condition_notes=None),
        ]
        # Legacy evidence must be ignored when canonical analysis is present.
        deal["ebay_avg_price_per_fig"] = 99.0
        deal["ebay_comp_count"] = 999
    return deal


def test_should_shape_new_minifigure_rows_from_canonical_helpers_only(monkeypatch):
    helper_names = (
        "entries", "figure_count", "identified_count", "unknown_count",
        "priced_subtotal", "sold_count",
    )
    calls: list[str] = []
    for name in helper_names:
        original = getattr(minifig_analysis, name)

        def wrapper(*args, _name=name, _original=original, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(minifig_analysis, name, wrapper)

    deal = _deal()
    deal["figure_count"] = 999
    shaped = rows.row(deal, favorites=set(), reg=cast(Any, _Registry()))

    assert calls == list(helper_names)
    assert shaped["figCount"] == 10
    assert shaped["identifiedCount"] == 6
    assert shaped["unknownCount"] == 4
    assert shaped["minifigSubtotal"] == 75.0
    assert shaped["minifigSoldCount"] == 8
    assert shaped["identificationComplete"] is False
    assert "perFig" not in shaped
    assert "ebayCount" not in shaped
    assert shaped["figures"] == [
        {
            "figNo": "sw0001a",
            "name": "Stormtrooper",
            "quantity": 6,
            "unitValue": 12.5,
            "extendedValue": 75.0,
            "soldCount": 8,
            "conditionNotes": "Light play wear",
            "cropUrl": "/crops/aa/figcrop-v1-" + (_HASH[:-2] + "01") + ".jpg",
            "status": "verified",
            "nullValueReason": None,
            "errors": [],
        },
        {
            "figNo": None,
            "name": "Unknown",
            "quantity": 4,
            "unitValue": None,
            "extendedValue": None,
            "soldCount": None,
            "conditionNotes": None,
            "cropUrl": "/crops/aa/figcrop-v1-" + (_HASH[:-2] + "02") + ".jpg",
            "status": "unknown",
            "nullValueReason": "unknown_identity",
            "errors": [],
        },
    ]


def test_should_mark_fully_identified_analysis_complete():
    deal = _deal()
    deal["minifig_analysis"] = [
        _analysis_entry("g1", _crop_ref("03"), quantity=10),
    ]

    shaped = rows.row(deal, favorites=set(), reg=cast(Any, _Registry()))

    assert shaped["identifiedCount"] == 10
    assert shaped["unknownCount"] == 0
    assert shaped["identificationComplete"] is True


def test_should_preserve_positive_legacy_branch_only_when_analysis_absent():
    deal = _deal(analysis=False)
    deal.update({
        "figure_count_source": "stated",
        "ebay_avg_price_per_fig": 7.5,
        "ebay_comp_count": 11,
    })

    shaped = rows.row(deal, favorites=set(), reg=cast(Any, _Registry()))

    assert shaped["perFig"] == 7.5
    assert shaped["ebayCount"] == 11
    assert shaped["figSrc"] == "stated"
    assert "figures" not in shaped
    assert "identifiedCount" not in shaped
    assert "identificationComplete" not in shaped


@contextmanager
def _crop_server(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "ledger.db"
    ledger_db.init(str(db_path)).close()
    crop_root = tmp_path / "crops"
    crop_root.mkdir()
    monkeypatch.setattr(server, "DB_OVERRIDE", str(db_path))
    monkeypatch.setattr(server, "CROP_ROOT", crop_root)
    original_hosts = set(server.ALLOWED_HOSTS)
    original_origins = set(server.ALLOWED_ORIGINS)
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    host = f"127.0.0.1:{httpd.server_port}"
    server.ALLOWED_HOSTS.add(host)
    server.ALLOWED_HOSTS.add(f"localhost:{httpd.server_port}")
    server.ALLOWED_ORIGINS.add(f"http://{host}")
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_port, crop_root
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()
        server.ALLOWED_HOSTS.clear()
        server.ALLOWED_HOSTS.update(original_hosts)
        server.ALLOWED_ORIGINS.clear()
        server.ALLOWED_ORIGINS.update(original_origins)


def _get(port: int, path: str, *, host: str | None = None):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    headers = {"Host": host or f"localhost:{port}"}
    conn.request("GET", path, headers=headers)
    response = conn.getresponse()
    body = response.read()
    headers = dict(response.getheaders())
    conn.close()
    return response.status, headers, body


def test_should_serve_url_decoded_content_hash_crop_with_exact_headers(
    monkeypatch, tmp_path,
):
    with _crop_server(monkeypatch, tmp_path) as (port, crop_root):
        expected = b"\xff\xd8crop-bytes\xff\xd9"
        nested = crop_root / "aa"
        nested.mkdir()
        filename = f"figcrop-v1-{_HASH}.jpg"
        (nested / filename).write_bytes(expected)

        status, headers, body = _get(
            port, f"/crops/aa/{filename.replace('-', '%2D', 1)}")

    assert status == 200
    assert body == expected
    assert headers["Content-Type"] == "image/jpeg"
    assert headers["Content-Length"] == str(len(expected))
    assert headers["Cache-Control"] == "public, max-age=31536000, immutable"
    assert headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize(
    ("suffix", "expected_type"),
    [(".jpeg", "image/jpeg"), (".png", "image/png"), (".webp", "image/webp")],
)
def test_should_serve_only_supported_crop_mime_types(
    monkeypatch, tmp_path, suffix, expected_type,
):
    with _crop_server(monkeypatch, tmp_path) as (port, crop_root):
        filename = f"figcrop-v1-{_HASH}{suffix}"
        (crop_root / filename).write_bytes(b"image")
        status, headers, body = _get(port, f"/crops/{filename}")

    assert status == 200
    assert body == b"image"
    assert headers["Content-Type"] == expected_type
    assert headers["Content-Length"] == "5"
    assert headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize(
    ("path", "expected_status"),
    [
        ("/crops/../outside.jpg", 403),
        ("/crops/%2e%2e/outside.jpg", 403),
        ("/crops/%2Fetc/passwd", 403),
        ("/crops/missing.jpg", 404),
        ("/crops/not-image.txt", 415),
        ("/crops/not-image.gif", 415),
    ],
)
def test_should_reject_unsafe_or_invalid_crop_requests(
    monkeypatch, tmp_path, path, expected_status,
):
    with _crop_server(monkeypatch, tmp_path) as (port, crop_root):
        (crop_root / "not-image.txt").write_text("not an image")
        (crop_root / "not-image.gif").write_bytes(b"GIF89a")
        status, _, _ = _get(port, path)
    assert status == expected_status


def test_should_reject_symlink_escape_and_directory(monkeypatch, tmp_path):
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"outside")
    with _crop_server(monkeypatch, tmp_path) as (port, crop_root):
        os.symlink(outside, crop_root / "escape.jpg")
        (crop_root / "directory.jpg").mkdir()
        escaped, _, _ = _get(port, "/crops/escape.jpg")
        directory, _, _ = _get(port, "/crops/directory.jpg")
    assert escaped == 403
    assert directory == 404


def test_should_reject_arbitrary_shared_root_read(monkeypatch, tmp_path):
    secret = tmp_path / "secret.jpg"
    secret.write_bytes(b"not a crop")
    with _crop_server(monkeypatch, tmp_path) as (port, _):
        status, _, body = _get(port, "/crops/%2e%2e/secret.jpg")
    assert status == 403
    assert body != b"not a crop"


def test_should_enforce_ten_mib_crop_boundary(monkeypatch, tmp_path):
    with _crop_server(monkeypatch, tmp_path) as (port, crop_root):
        exact = crop_root / "exact.png"
        with exact.open("wb") as stream:
            stream.truncate(10 * 1024 * 1024)
        too_large = crop_root / "large.png"
        with too_large.open("wb") as stream:
            stream.truncate(10 * 1024 * 1024 + 1)

        exact_status, exact_headers, exact_body = _get(port, "/crops/exact.png")
        large_status, _, _ = _get(port, "/crops/large.png")

    assert exact_status == 200
    assert exact_headers["Content-Length"] == str(10 * 1024 * 1024)
    assert len(exact_body) == 10 * 1024 * 1024
    assert large_status == 413


def test_should_use_no_store_for_non_content_hash_image(monkeypatch, tmp_path):
    with _crop_server(monkeypatch, tmp_path) as (port, crop_root):
        (crop_root / "legacy.jpg").write_bytes(b"legacy")
        status, headers, _ = _get(port, "/crops/legacy.jpg")
    assert status == 200
    assert headers["Cache-Control"] == "no-store"


def test_should_keep_host_guard_on_crop_route(monkeypatch, tmp_path):
    with _crop_server(monkeypatch, tmp_path) as (port, crop_root):
        (crop_root / "ok.jpg").write_bytes(b"ok")
        status, _, _ = _get(port, "/crops/ok.jpg", host="evil.example")
    assert status == 403


def test_should_remove_new_minifigure_mixed_unit_and_target_calculator_surfaces():
    assert '$ / lb·fig' not in server.PAGE
    assert 'placeholder="$ /fig"' not in server.PAGE
    assert 'r.cat==="minifigure"&&r.figCount' not in server.PAGE
