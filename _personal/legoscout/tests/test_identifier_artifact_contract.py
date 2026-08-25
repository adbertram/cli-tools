from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from legoscout_cli.ledger import minifig_analysis as mfa
from legoscout_cli.main import app
from legoscout_cli.pricing import minifig_identification as identification
from legoscout_cli.pricing import minifig_sales

runner = CliRunner()


def _candidate(candidate_id, score=.9):
    return {
        "id": candidate_id,
        "name": f"Figure {candidate_id}",
        "img_url": f"https://example.invalid/{candidate_id}.webp",
        "external_sites": [],
        "category": "Theme",
        "type": "fig",
        "score": score,
    }


def _detection(
    crop_id,
    *,
    photo="photo-a",
    box=None,
    confidence=.9,
):
    return {
        "crop_id": crop_id,
        "source_photo_sha256": hashlib.sha256(photo.encode("utf-8")).hexdigest(),
        "photo_relative_id": photo,
        "box": box or [.1, .1, .4, .8],
        "detector_name": "grounding-dino-tiny",
        "detector_version": "v1",
        "detector_confidence": confidence,
        "crop_ref": f"{crop_id[-2:]}/{crop_id}.jpg",
    }


def _verification(status="verified", compared=None):
    return {
        "status": status,
        "reason": "visual and BrickLink catalog comparison complete",
        "compared_candidate_ids": compared if compared is not None else [],
        "catalog_checked_at": "2026-08-25T12:00:00Z",
    }


def _group(
    group_id,
    detections,
    *,
    fig_no: str | None = "sw0001a",
    verification_status="verified",
    candidate_ids=None,
    condition_notes=None,
):
    candidate_ids = candidate_ids if candidate_ids is not None else (
        [fig_no] if fig_no else [])
    candidates = [_candidate(candidate_id, .9 - index * .05)
                  for index, candidate_id in enumerate(candidate_ids)]
    verification = _verification(
        verification_status,
        compared=list(candidate_ids),
    )
    catalog = ({
        "no": fig_no,
        "name": f"Catalog {fig_no}",
        "thumbnail_url": f"//img.bricklink.com/M/{fig_no}.jpg",
    } if verification_status == "verified" and fig_no else None)
    return {
        "match_group_id": group_id,
        "candidate_signature": "same-signature",
        "detections": detections,
        "representative_crop_ref": min(
            detections,
            key=lambda row: (-row["detector_confidence"], row["crop_id"]),
        )["crop_ref"],
        "brickognize_candidates": candidates,
        "brickognize_contract": {
            "endpoint": "https://api.brickognize.com/predict/figs/",
            "contract_version": "brickognize-legacy-figs-v1",
            "crop_sha256": "c" * 64,
            "top_k_items": 10,
            "min_similarity_items": .5,
        },
        "status": "success",
        "reason": None,
        "verification": verification,
        "fig_no": fig_no if verification_status == "verified" else None,
        "catalog": catalog,
        "condition_notes": condition_notes,
    }


def _artifact(listings):
    rows = []
    group_count = 0
    crop_count = 0
    for key, groups, status, reason in listings:
        group_count += len(groups)
        crop_count += sum(len(group["detections"]) for group in groups)
        row = {
            "listing_key": key,
            "observations": {"vision": {"photo_figure_count": crop_count}},
            "status": status,
            "reason": reason,
            "groups": groups,
        }
        membership = {
            "contract_version": "minifig-source-members-v1",
            "listing_key": key,
            "groups": [
                {
                    "match_group_id": group["match_group_id"],
                    "detections": [
                        {field: detection[field] for field in sorted(
                            identification.DETECTION_FIELDS)}
                        for detection in group["detections"]
                    ],
                }
                for group in groups
            ],
        }
        encoded = json.dumps(
            membership, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        row["source_member_digest"] = (
            "figmembers-v1-" + hashlib.sha256(encoded).hexdigest())
        rows.append(row)
    return {
        "version": 1,
        "kind": "minifig_identification",
        "request_contract": {
            "endpoint": "https://api.brickognize.com/predict/figs/",
            "contract_version": "brickognize-legacy-figs-v1",
            "top_k_items": 10,
            "min_similarity_items": .5,
        },
        "listings": rows,
        "summary": {
            "listing_count": len(rows),
            "success_count": sum(status == "success"
                                 for _, _, status, _ in listings),
            "partial_count": sum(status == "partial"
                                 for _, _, status, _ in listings),
            "skipped_count": sum(status == "skipped"
                                 for _, _, status, _ in listings),
            "crop_count": crop_count,
            "group_count": group_count,
            "provider_success_count": crop_count,
            "provider_skipped_count": 0,
            "cache_hit_count": 0,
        },
        "timings": {
            "total_seconds": 1.0,
            "mean_per_crop_seconds": (
                round(1.0 / crop_count, 6) if crop_count else 0.0),
        },
    }


def _found(fig_no, catalog, unit: float | None = 10.0, count=5, refresh=False):
    return {
        "fig_no": fig_no,
        "catalog": catalog,
        "used": {
            "condition": "U",
            "guide_type": "sold",
            "sold_window": "bricklink_sold_guide_last_6_months",
            "six_month_avg_sold_price": unit,
            "avg_price": unit,
            "qty_avg_price": unit,
            "unit_quantity": count,
            "total_quantity": count,
            "price_detail_count": count,
            "price_detail": [],
        },
        "lookup_status": "found" if unit is not None else "zero_sales",
        "unit_value": unit,
        "null_value_reason": None if unit is not None else "no sold data",
    }


def _price(artifact, pricer=_found, workers=4, refresh=False):
    return identification.price_batch(
        artifact,
        workers=workers,
        refresh=refresh,
        pricer=pricer,
    )


def test_should_register_the_offline_price_leaf():
    result = runner.invoke(app, ["minifig", "price", "--help"])
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("detections, expected_quantity", [
    ([
        _detection("figcrop-v1-a", photo="photo-a"),
        _detection("figcrop-v1-b", photo="photo-b"),
    ], 1),
    ([
        _detection("figcrop-v1-a", photo="photo-a", box=[0, 0, .3, 1]),
        _detection("figcrop-v1-b", photo="photo-a", box=[.6, 0, .9, 1]),
    ], 2),
    ([
        _detection("figcrop-v1-a", photo="photo-a", box=[0, 0, .3, 1]),
        _detection("figcrop-v1-b", photo="photo-a", box=[.6, 0, .9, 1]),
        _detection("figcrop-v1-c", photo="photo-b"),
    ], 2),
])
def test_should_set_quantity_to_max_simultaneous_count(
    detections,
    expected_quantity,
):
    report = _price(_artifact([
        ("source|1", [_group("g1", detections)], "success", None),
    ]))
    entry = report["results"][0]["minifig_analysis"][0]
    assert entry["quantity"] == expected_quantity
    assert entry["extended_value"] == 10.0 * expected_quantity
    assert report["results"][0]["figure_count"] == expected_quantity


def test_should_count_live_three_figure_shape_once_across_repeated_photos():
    clone_front = _group(
        "g-clone-front",
        [_detection(
            "figcrop-v1-clone-front",
            photo="photo-a",
            box=[.05, .25, .31, .72],
            confidence=.72,
        )],
        fig_no="sw1090",
        candidate_ids=["sw1090", "sw0201"],
    )
    r2 = _group(
        "g-r2",
        [
            _detection(
                "figcrop-v1-r2-a",
                photo="photo-a",
                box=[.32, .38, .65, .75],
                confidence=.73,
            ),
            _detection(
                "figcrop-v1-r2-b-outer",
                photo="photo-b",
                box=[.32, .42, .63, .74],
                confidence=.62,
            ),
            _detection(
                "figcrop-v1-r2-b-inner",
                photo="photo-b",
                box=[.38, .42, .56, .69],
                confidence=.26,
            ),
        ],
        fig_no="sw0527a",
    )
    storm = _group(
        "g-storm",
        [
            _detection(
                "figcrop-v1-storm-a",
                photo="photo-a",
                box=[.68, .26, .95, .72],
                confidence=.59,
            ),
            _detection(
                "figcrop-v1-storm-b",
                photo="photo-b",
                box=[.67, .29, .95, .72],
                confidence=.56,
            ),
        ],
        fig_no="sw0905",
    )
    clone_split = _group(
        "g-clone-split",
        [_detection(
            "figcrop-v1-clone-b",
            photo="photo-b",
            box=[.05, .26, .31, .70],
            confidence=.72,
        )],
        fig_no=None,
        verification_status="unknown",
        candidate_ids=["sw1090"],
    )
    backs = [
        _group(
            f"g-back-{index}",
            [_detection(
                f"figcrop-v1-back-{index}",
                photo="photo-c",
                box=box,
                confidence=confidence,
            )],
            fig_no=None,
            verification_status="unknown",
            candidate_ids=[],
        )
        for index, (box, confidence) in enumerate((
            ([.05, .28, .28, .74], .72),
            ([.31, .35, .62, .71], .73),
            ([.67, .25, .95, .71], .74),
        ), start=1)
    ]
    groups = [clone_front, r2, storm, clone_split, *backs]
    artifact = _artifact([
        ("k-bid|66023-13 Mini Fig", groups, "success", None),
    ])

    assert len(groups) == 7
    assert sum(len(group["detections"]) for group in groups) == 10
    # The old per-group max-per-photo sum was 8: 1 + 2 + 1 + 1 + 1 + 1 + 1.
    assert sum(identification._quantity(group["detections"])
               for group in groups) == 8

    result = _price(artifact)["results"][0]
    analysis = result["minifig_analysis"]
    quantities = {entry["match_group_id"]: entry["quantity"]
                  for entry in analysis}

    assert result["figure_count"] == 3
    assert result["identified_count"] == 3
    assert result["unknown_count"] == 0
    assert quantities == {
        "g-clone-front": 1,
        "g-r2": 1,
        "g-storm": 1,
        "g-clone-split": 0,
        "g-back-1": 0,
        "g-back-2": 0,
        "g-back-3": 0,
    }
    assert len(analysis) == 7
    assert sum(len(entry["detections"]) for entry in analysis) == 9
    assert {entry["quantity_basis"]["rule"] for entry in analysis} == {
        "representative-photo-max-simultaneous-v1",
    }
    assert {entry["quantity_basis"]["photo_relative_id"]
            for entry in analysis} == {"photo-a"}


@pytest.mark.parametrize("overlap_width, expected_count, retained", [
    (.6999, 2, {"figcrop-v1-a", "figcrop-v1-b"}),
    (.70, 1, {"figcrop-v1-a"}),
])
def test_should_apply_iou_boundary_and_equal_confidence_crop_id_tie(
    overlap_width,
    expected_count,
    retained,
):
    width = .8
    shift = width * (1.0 - overlap_width) / (1.0 + overlap_width)
    detections = [
        _detection("figcrop-v1-b", box=[0, 0, width, 1], confidence=.9),
        _detection(
            "figcrop-v1-a",
            box=[shift, 0, width + shift, 1],
            confidence=.9,
        ),
    ]
    entry = _price(_artifact([
        ("source|1", [_group("g1", detections)], "success", None),
    ]))["results"][0]["minifig_analysis"][0]
    assert len(entry["detections"]) == expected_count
    assert {row["crop_id"] for row in entry["detections"]} == retained
    assert entry["quantity"] == expected_count


def test_should_merge_exact_verified_fig_across_groups_and_price_once():
    groups = [
        _group("g1", [_detection("figcrop-v1-a", photo="photo-a")]),
        _group("g2", [_detection("figcrop-v1-b", photo="photo-b")]),
    ]
    calls = []

    def pricer(fig_no, catalog, refresh=False):
        calls.append((fig_no, refresh))
        return _found(fig_no, catalog)

    result = _price(_artifact([
        ("source|1", groups, "success", None),
    ]), pricer=pricer)["results"][0]
    assert calls == [("sw0001a", False)]
    assert len(result["minifig_analysis"]) == 1
    assert result["minifig_analysis"][0]["quantity"] == 1
    assert len(result["minifig_analysis"][0]["detections"]) == 2


def test_should_never_merge_suffix_distinct_or_differently_verified_groups():
    groups = [
        _group("g1", [_detection("figcrop-v1-a")], fig_no="sw0001a"),
        _group("g2", [_detection("figcrop-v1-b")], fig_no="sw0001b"),
        _group("g3", [_detection("figcrop-v1-c")], fig_no="sw0002",
               candidate_ids=["sw0002", "sw0003"]),
        _group("g4", [_detection("figcrop-v1-d")], fig_no="sw0003",
               candidate_ids=["sw0002", "sw0003"]),
    ]
    result = _price(_artifact([
        ("source|1", groups, "success", None),
    ]))["results"][0]
    assert [entry["fig_no"] for entry in result["minifig_analysis"]] == [
        "sw0001a", "sw0001b", "sw0002", "sw0003"]


def test_should_never_merge_unknown_or_unverifiable_groups():
    groups = [
        _group("g1", [_detection("figcrop-v1-a")], fig_no=None,
               verification_status="unknown", candidate_ids=["same"]),
        _group("g2", [_detection("figcrop-v1-b")], fig_no=None,
               verification_status="unknown", candidate_ids=["same"]),
        _group("g3", [_detection("figcrop-v1-c")], fig_no=None,
               verification_status="unverifiable", candidate_ids=["same"]),
    ]
    analysis = _price(_artifact([
        ("source|1", groups, "success", None),
    ]))["results"][0]["minifig_analysis"]
    assert len(analysis) == 3
    assert [entry["verification"]["status"] for entry in analysis] == [
        "unknown", "unknown", "unverifiable"]
    assert [entry["null_value_reason"] for entry in analysis] == [
        "unknown_identity", "unknown_identity", "unverifiable"]


def test_should_choose_final_representative_by_confidence_then_crop_id():
    groups = [
        _group("g1", [_detection("figcrop-v1-b", confidence=.9)]),
        _group("g2", [_detection("figcrop-v1-a", confidence=.9)]),
    ]
    entry = _price(_artifact([
        ("source|1", groups, "success", None),
    ]))["results"][0]["minifig_analysis"][0]
    assert entry["representative_crop_ref"].endswith("figcrop-v1-a.jpg")


def test_should_isolate_mixed_pricing_and_malformed_verification_matrix():
    boxes = [
        [index * .16, .1, index * .16 + .14, .8]
        for index in range(6)
    ]
    groups = [
        _group("g-found", [_detection("figcrop-v1-a", box=boxes[0])],
               fig_no="sw0001"),
        _group("g-zero", [_detection("figcrop-v1-b", box=boxes[1])],
               fig_no="sw0002"),
        _group("g-not-found", [_detection("figcrop-v1-c", box=boxes[2])],
               fig_no="sw0003"),
        _group("g-transient", [_detection("figcrop-v1-d", box=boxes[3])],
               fig_no="sw0004"),
        _group("g-malformed", [_detection("figcrop-v1-e", box=boxes[4])],
               fig_no="sw0005"),
        _group("g-unknown", [_detection("figcrop-v1-f", box=boxes[5])],
               fig_no=None,
               verification_status="unknown", candidate_ids=[]),
    ]
    del groups[4]["verification"]
    calls = []

    def pricer(fig_no, catalog, refresh=False):
        calls.append(fig_no)
        if fig_no == "sw0001":
            return _found(fig_no, catalog, unit=10.0, count=5)
        if fig_no == "sw0002":
            return _found(fig_no, catalog, unit=None, count=0)
        if fig_no == "sw0003":
            raise minifig_sales.LookupNotFound("RESOURCE_NOT_FOUND")
        if fig_no == "sw0004":
            raise minifig_sales.LookupFailed("temporary timeout")
        pytest.fail(f"unexpected price call for {fig_no}")

    result = _price(_artifact([
        ("source|1", groups, "success", None),
    ]), pricer=pricer, workers=4)["results"][0]
    entries = result["minifig_analysis"]
    by_group = {entry["match_group_id"]: entry for entry in entries}

    assert set(calls) == {"sw0001", "sw0002", "sw0003", "sw0004"}
    assert len(calls) == 4
    assert by_group["g-found"]["unit_value"] == 10.0
    assert by_group["g-found"]["extended_value"] == 10.0
    assert by_group["g-zero"]["null_value_reason"] == "zero_sales"
    assert by_group["g-zero"]["errors"] == []
    assert by_group["g-not-found"]["null_value_reason"] == "price_lookup_failed"
    assert by_group["g-not-found"]["errors"][0].startswith("LookupNotFound:")
    assert by_group["g-transient"]["null_value_reason"] == "price_lookup_failed"
    assert by_group["g-transient"]["errors"][0].startswith("LookupFailed:")
    malformed = by_group["g-malformed"]
    assert malformed["verification"]["status"] == "unverifiable"
    assert malformed["null_value_reason"] == "stage_failed"
    assert "verification" in malformed["errors"][0]
    assert by_group["g-unknown"]["null_value_reason"] == "unknown_identity"
    assert all(mfa.entry_errors(entry) == [] for entry in entries)
    assert mfa.batch_errors(entries) == []
    assert result["status"] == "success"
    assert result["figure_count"] == 6
    assert result["figure_count_source"] == "detection"
    assert result["identified_count"] == 4
    assert result["unknown_count"] == 2
    assert result["priced_subtotal"] == 10.0
    assert result["sold_count"] == 5
    assert result["pricing_complete"] is False
    assert by_group["g-found"]["catalog"]["thumbnail_url"].startswith("https:")


def test_should_reject_detection_level_verification_as_stage_failure():
    group = _group("g1", [_detection("figcrop-v1-a")])
    group["detections"][0]["verification"] = _verification(
        "verified", ["sw0001a"])
    entry = _price(_artifact([
        ("source|1", [group], "success", None),
    ]))["results"][0]["minifig_analysis"][0]
    assert entry["verification"]["status"] == "unverifiable"
    assert entry["null_value_reason"] == "stage_failed"
    assert "representative" in entry["errors"][0]


def test_should_forward_refresh_and_keep_result_order_under_workers():
    groups = [
        _group("g1", [_detection("figcrop-v1-a")], fig_no="sw0001"),
        _group("g2", [_detection("figcrop-v1-b")], fig_no="sw0002"),
    ]
    calls = []

    def pricer(fig_no, catalog, refresh=False):
        calls.append((fig_no, refresh))
        return _found(fig_no, catalog)

    results = _price(_artifact([
        ("source|1", [groups[0]], "success", None),
        ("source|2", [groups[1]], "success", None),
    ]), pricer=pricer, workers=2, refresh=True)["results"]
    assert set(calls) == {("sw0001", True), ("sw0002", True)}
    assert [row["listing_key"] for row in results] == ["source|1", "source|2"]


def test_should_coalesce_exact_price_target_across_listings_and_fan_out():
    calls = []

    def pricer(fig_no, catalog, refresh=False):
        calls.append((fig_no, copy.deepcopy(catalog), refresh))
        return _found(fig_no, catalog, unit=12.5, count=7)

    report = _price(_artifact([
        ("source|1", [
            _group("g1", [_detection("figcrop-v1-a")], fig_no="sw0001"),
        ], "success", None),
        ("source|2", [
            _group("g2", [_detection("figcrop-v1-b")], fig_no="sw0001"),
        ], "success", None),
    ]), pricer=pricer, workers=2, refresh=True)

    assert calls == [("sw0001", {
        "no": "sw0001",
        "name": "Catalog sw0001",
        "thumbnail_url": "//img.bricklink.com/M/sw0001.jpg",
    }, True)]
    assert [row["listing_key"] for row in report["results"]] == [
        "source|1", "source|2"]
    assert [row["priced_subtotal"] for row in report["results"]] == [12.5, 12.5]
    assert report["summary"]["priced_entry_count"] == 2


def test_should_coalesce_same_fig_with_different_catalog_contracts():
    first = _group("g1", [_detection("figcrop-v1-a")], fig_no="sw0001")
    second = _group("g2", [_detection("figcrop-v1-b")], fig_no="sw0001")
    second["catalog"]["name"] = "Different catalog contract"
    calls = []

    def pricer(fig_no, catalog, refresh=False):
        calls.append((fig_no, catalog["name"]))
        return _found(fig_no, catalog)

    report = _price(_artifact([
        ("source|1", [first], "success", None),
        ("source|2", [second], "success", None),
    ]), pricer=pricer, workers=2)

    assert calls == [("sw0001", "Catalog sw0001")]
    assert [row["minifig_analysis"][0]["catalog"]["name"]
            for row in report["results"]] == [
        "Catalog sw0001", "Different catalog contract"]
    assert len(calls) == 1


def test_should_fan_one_coalesced_price_failure_to_each_listing():
    calls = []

    def pricer(fig_no, catalog, refresh=False):
        calls.append((fig_no, refresh))
        raise minifig_sales.LookupFailed("shared BrickLink timeout")

    report = _price(_artifact([
        ("source|1", [
            _group("g1", [_detection("figcrop-v1-a")], fig_no="sw0001"),
        ], "success", None),
        ("source|2", [
            _group("g2", [_detection("figcrop-v1-b")], fig_no="sw0001"),
        ], "success", None),
    ]), pricer=pricer, workers=2)

    assert calls == [("sw0001", False)]
    entries = [row["minifig_analysis"][0] for row in report["results"]]
    assert [entry["null_value_reason"] for entry in entries] == [
        "price_lookup_failed", "price_lookup_failed"]
    assert [entry["errors"] for entry in entries] == [[
        "LookupFailed: shared BrickLink timeout",
    ], [
        "LookupFailed: shared BrickLink timeout",
    ]]
    assert [row["status"] for row in report["results"]] == ["success", "success"]


@pytest.mark.parametrize("drift", ["dropped", "added", "moved", "split"])
def test_should_reject_detector_membership_drift_before_pricing(drift):
    artifact = _artifact([
        ("source|1", [
            _group("g1", [
                _detection("figcrop-v1-a"),
                _detection("figcrop-v1-b", box=[.5, .1, .8, .8]),
            ], fig_no="sw0001"),
            _group("g2", [
                _detection("figcrop-v1-c", photo="photo-b"),
            ], fig_no="sw0002"),
        ], "success", None),
    ])
    groups = artifact["listings"][0]["groups"]
    if drift == "dropped":
        groups[0]["detections"].pop()
    elif drift == "added":
        groups[0]["detections"].append(
            _detection("figcrop-v1-d", box=[.05, .05, .2, .7]))
    elif drift == "moved":
        groups[1]["detections"].append(groups[0]["detections"].pop())
    else:
        split = copy.deepcopy(groups[0])
        split["match_group_id"] = "g3"
        split["detections"] = [groups[0]["detections"].pop()]
        split["representative_crop_ref"] = split["detections"][0]["crop_ref"]
        groups.append(split)

    calls = []
    with pytest.raises(
        identification.IdentificationArtifactError,
        match="detector membership drift",
    ):
        _price(
            artifact,
            pricer=lambda *args, **kwargs: calls.append((args, kwargs)),
        )
    assert calls == []


def test_should_emit_blocked_result_for_listing_without_groups():
    result = _price(_artifact([
        ("source|1", [], "skipped", "detector found no usable crops"),
    ]))["results"][0]
    assert result["listing_key"] == "source|1"
    assert result["blocked"] is True
    assert result["blocker"] == "detector found no usable crops"
    assert result["minifig_analysis"] is None
    assert result["figure_count"] is None


def test_should_write_empty_plain_array_and_loud_zero_price_summary(tmp_path):
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(json.dumps(_artifact([])), encoding="utf-8")

    result = runner.invoke(app, [
        "minifig", "price",
        "--input", str(input_path),
        "--output", str(output_path),
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(output_path.read_text()) == []
    summary = json.loads(result.stdout)
    assert summary["listing_count"] == 0
    assert summary["success_count"] == 0
    assert summary["partial_count"] == 0
    assert summary["blocked_count"] == 0
    assert summary["entry_count"] == 0
    assert summary["workers"] == 4
    assert summary["wall_seconds"] == 0.0
    assert summary["serial_equivalent_seconds"] == 0.0


@pytest.mark.parametrize("payload, expected", [
    ("{bad", "invalid JSON"),
    (json.dumps([]), "object"),
    (json.dumps({**_artifact([]), "version": 2}), "version 1"),
    (json.dumps({**_artifact([]), "kind": "wrong"}),
     "minifig_identification"),
])
def test_should_fail_price_publicly_without_output(
    payload,
    expected,
    tmp_path,
):
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(payload, encoding="utf-8")

    result = runner.invoke(app, [
        "minifig", "price",
        "--input", str(input_path),
        "--output", str(output_path),
    ])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert expected in result.stderr
    assert not output_path.exists()


def test_should_preserve_price_input_and_existing_output_on_failures(
    monkeypatch,
    tmp_path,
):
    same = tmp_path / "same.json"
    same.write_text(json.dumps(_artifact([])), encoding="utf-8")
    before = same.read_text()
    result = runner.invoke(app, [
        "minifig", "price", "--input", str(same), "--output", str(same),
    ])
    assert result.exit_code == 1
    assert "different paths" in result.stderr
    assert same.read_text() == before

    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(json.dumps(_artifact([])), encoding="utf-8")
    output_path.write_text('{"sentinel": true}\n', encoding="utf-8")
    monkeypatch.setattr(
        identification.os,
        "replace",
        lambda source, destination: (_ for _ in ()).throw(
            OSError("price promotion refused")),
    )
    result = runner.invoke(app, [
        "minifig", "price",
        "--input", str(input_path),
        "--output", str(output_path),
    ])
    assert result.exit_code == 1
    assert "price promotion refused" in result.stderr
    assert output_path.read_text() == '{"sentinel": true}\n'


def test_should_reject_price_workers_outside_one_through_eight(tmp_path):
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(_artifact([])), encoding="utf-8")
    for workers in (0, -1, 9):
        output_path = tmp_path / f"output-{workers}.json"
        result = runner.invoke(app, [
            "minifig", "price",
            "--input", str(input_path),
            "--output", str(output_path),
            "--workers", str(workers),
        ])
        assert result.exit_code == 1
        assert "workers" in result.stderr
        assert not output_path.exists()


def _source_candidate(key, category="minifigure"):
    return {
        "listing_key": key,
        "source": key.split("|", 1)[0],
        "listing_type": "fixed",
        "price_basis": "current_price",
        "current_price": 25.0,
        "available_fulfillment": ["shipping"],
    }


def _appraisal(key, category="minifigure"):
    return {
        "listing_key": key,
        "listing_category": category,
        "estimated_total": 25.0,
        "observations": {
            "model_score": 50,
            "model_rationale": "fixture",
        },
    }


def _priced_result(key="shop|1", fig_no="sw0001"):
    group = _group("g-" + key, [_detection("figcrop-v1-" + key[-1])],
                   fig_no=fig_no)
    return _price(_artifact([
        (key, [group], "success", None),
    ]))["results"][0]


def test_should_validate_success_and_blocked_identification_results():
    import legoscout_cli.orchestrator as orchestrator

    result = _priced_result()
    orchestrator.validate_identification_result(result)
    orchestrator.validate_identification_result({
        "listing_key": "shop|2",
        "blocked": True,
        "blocker": "no detector crops",
        "minifig_analysis": None,
        "figure_count": None,
        "figure_count_source": None,
        "identified_count": 0,
        "unknown_count": 0,
        "priced_subtotal": 0.0,
        "sold_count": None,
        "pricing_complete": False,
        "status": "blocked",
    })


def test_should_validate_exact_minifigure_subset_keys():
    import legoscout_cli.orchestrator as orchestrator

    candidates = [
        _source_candidate("shop|1", "minifigure"),
        _source_candidate("shop|2", "bulk"),
        _source_candidate("shop|3", "set"),
        _source_candidate("shop|4", "excluded"),
    ]
    appraisals = [
        _appraisal("shop|1", "minifigure"),
        _appraisal("shop|2", "bulk"),
        _appraisal("shop|3", "set"),
        _appraisal("shop|4", "excluded"),
    ]
    result = _priced_result("shop|1")
    assert orchestrator.validate_identification_batch(
        candidates, appraisals, [result]) == {"shop|1": result}

    with pytest.raises(Exception, match="missing identification results"):
        orchestrator.validate_identification_batch(candidates, appraisals, [])
    with pytest.raises(Exception, match="extra identification results"):
        orchestrator.validate_identification_batch(
            candidates, appraisals, [result, {
                **result, "listing_key": "shop|2",
            }])
    with pytest.raises(Exception, match="duplicate identification result keys"):
        orchestrator.validate_identification_batch(
            candidates, appraisals, [result, result])


def test_should_isolate_one_malformed_identification_result_in_synthesis(
    monkeypatch,
):
    import legoscout_cli.orchestrator as orchestrator
    from legoscout_cli.ledger import build_record

    candidates = [
        _source_candidate("shop|1"),
        _source_candidate("shop|2"),
    ]
    appraisals = [_appraisal("shop|1"), _appraisal("shop|2")]
    good = _priced_result("shop|1")
    malformed = {"listing_key": "shop|2", "minifig_analysis": "bad"}
    builds = []

    def fake_build(candidate, appraisal, **kwargs):
        builds.append((candidate["listing_key"], kwargs.get("identification")))
        return {}

    monkeypatch.setattr(build_record, "build_deal_record", fake_build)
    report = orchestrator.synthesis_coverage(
        candidates,
        appraisals,
        identification_results=[good, malformed],
    )

    assert report["complete"] is False
    assert report["buildable_count"] == 1
    assert report["build_errors"][0]["listing_key"] == "shop|2"
    assert builds == [("shop|1", good)]


def _source_artifact(candidates):
    return {
        "source": "shop",
        "checked": True,
        "blocked": False,
        "blocker": None,
        "candidate_records": candidates,
        "unavailable_updates": [],
        "unchanged_duplicate_keys": [],
        "learning_notes": [],
        "actions_requiring_approval": [],
        "evidence_summary": "fixture",
        "completed_at": "2026-08-25T00:00:00Z",
    }


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _stub_manifest_build(monkeypatch):
    from legoscout_cli.ledger import build_record

    monkeypatch.setattr(
        build_record,
        "build_deal_record",
        lambda candidate, appraisal, **kwargs: {},
    )


def test_manifest_pairs_same_number_identification_for_minifigures(
    monkeypatch,
    tmp_path,
):
    import legoscout_cli.orchestrator as orchestrator

    _stub_manifest_build(monkeypatch)
    candidate = _source_candidate("shop|1")
    _write(tmp_path / "shop.json", _source_artifact([candidate]))
    _write(tmp_path / "shop.appraisal-1.json", [_appraisal("shop|1")])
    _write(tmp_path / "shop.identify-1.json", [_priced_result("shop|1")])

    manifest = orchestrator.build_run_manifest(
        str(tmp_path), active_sources=["shop"])

    assert manifest["complete"] is True, manifest
    report = manifest["sources"][0]["appraisal_batches"][0]
    assert report["identification_artifact"].endswith("shop.identify-1.json")
    assert report["identification_count"] == 1


def test_manifest_requires_identification_only_for_minifigure_subset(
    monkeypatch,
    tmp_path,
):
    import legoscout_cli.orchestrator as orchestrator

    _stub_manifest_build(monkeypatch)
    candidate = _source_candidate("shop|1")
    _write(tmp_path / "shop.json", _source_artifact([candidate]))
    _write(tmp_path / "shop.appraisal-1.json", [_appraisal("shop|1")])
    missing = orchestrator.build_run_manifest(
        str(tmp_path), active_sources=["shop"])
    assert missing["complete"] is False
    assert "identification artifact is missing" in "\n".join(
        missing["sources"][0]["problems"])

    bulk_dir = tmp_path / "bulk"
    bulk = _source_candidate("shop|2", "bulk")
    _write(bulk_dir / "shop.json", _source_artifact([bulk]))
    _write(bulk_dir / "shop.appraisal-1.json", [
        _appraisal("shop|2", "bulk")])
    complete = orchestrator.build_run_manifest(
        str(bulk_dir), active_sources=["shop"])
    assert complete["complete"] is True, complete


@pytest.mark.parametrize("name, payload, expected", [
    ("shop.identify-1.json", "{bad", "not valid JSON"),
    ("shop.identify-1.json", {"results": []}, "must be an array"),
    ("shop.identify-x.json", [], "invalid identification artifact name"),
    ("shop.identify-2.json", [], "unexpected identification batches"),
])
def test_manifest_reports_identification_artifact_defects(
    monkeypatch,
    tmp_path,
    name,
    payload,
    expected,
):
    import legoscout_cli.orchestrator as orchestrator

    _stub_manifest_build(monkeypatch)
    candidate = _source_candidate("shop|1")
    _write(tmp_path / "shop.json", _source_artifact([candidate]))
    _write(tmp_path / "shop.appraisal-1.json", [_appraisal("shop|1")])
    path = tmp_path / name
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        _write(path, payload)

    manifest = orchestrator.build_run_manifest(
        str(tmp_path), active_sources=["shop"])
    assert manifest["complete"] is False
    assert expected in "\n".join(manifest["sources"][0]["problems"])


def test_manifest_rejects_duplicate_identification_batch_number(
    monkeypatch,
    tmp_path,
):
    import legoscout_cli.orchestrator as orchestrator

    _stub_manifest_build(monkeypatch)
    candidate = _source_candidate("shop|1")
    _write(tmp_path / "shop.json", _source_artifact([candidate]))
    _write(tmp_path / "shop.appraisal-1.json", [_appraisal("shop|1")])
    result = [_priced_result("shop|1")]
    _write(tmp_path / "shop.identify-1.json", result)
    _write(tmp_path / "shop.identify-01.json", result)

    manifest = orchestrator.build_run_manifest(
        str(tmp_path), active_sources=["shop"])
    assert "duplicate identification batch number" in "\n".join(
        manifest["sources"][0]["problems"])


def test_manifest_reports_wrong_source_identification_as_orphan(
    monkeypatch,
    tmp_path,
):
    import legoscout_cli.orchestrator as orchestrator

    _stub_manifest_build(monkeypatch)
    bulk = _source_candidate("shop|1", "bulk")
    _write(tmp_path / "shop.json", _source_artifact([bulk]))
    _write(tmp_path / "shop.appraisal-1.json", [_appraisal("shop|1", "bulk")])
    _write(tmp_path / "wrong.identify-1.json", [_priced_result("wrong|1")])

    manifest = orchestrator.build_run_manifest(
        str(tmp_path), active_sources=["shop"])
    assert manifest["complete"] is False
    assert manifest["orphan_identification_artifacts"] == [
        str(tmp_path / "wrong.identify-1.json")]


def test_malformed_identification_batch_does_not_hide_valid_sibling(
    monkeypatch,
    tmp_path,
):
    import legoscout_cli.orchestrator as orchestrator

    _stub_manifest_build(monkeypatch)
    candidates = [_source_candidate(f"shop|{index}")
                  for index in range(1, 27)]
    _write(tmp_path / "shop.json", _source_artifact(candidates))
    _write(tmp_path / "shop.appraisal-1.json", [
        _appraisal(item["listing_key"]) for item in candidates[:25]])
    _write(tmp_path / "shop.appraisal-2.json", [
        _appraisal(candidates[25]["listing_key"])])
    (tmp_path / "shop.identify-1.json").write_text("{bad", encoding="utf-8")
    _write(tmp_path / "shop.identify-2.json", [
        _priced_result(candidates[25]["listing_key"]),
    ])

    manifest = orchestrator.build_run_manifest(
        str(tmp_path), active_sources=["shop"])
    reports = manifest["sources"][0]["appraisal_batches"]
    assert [report["complete"] for report in reports] == [False, True]
    assert "not valid JSON" in reports[0]["error"]
    assert reports[1]["identification_count"] == 1
