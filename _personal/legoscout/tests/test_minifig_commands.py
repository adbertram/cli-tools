from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from legoscout_cli.main import app


runner = CliRunner()


def _identification():
    return importlib.import_module(
        "legoscout_cli.pricing.minifig_identification")


def _row(paths, key="source|1", observations=None):
    return {
        "listing_key": key,
        "saved_photo_paths": [str(path) for path in paths],
        "observations": observations if observations is not None else {
            "vision": {"stated_figure_count": 2},
        },
    }


def _save(path: Path, image_format: str) -> Path:
    Image.new("RGB", (100, 100), color=(10, 20, 30)).save(
        path, format=image_format)
    return path


def _success_detector(name, paths):
    from legoscout_cli.pricing import minifig_detector

    rows = []
    for path in paths:
        box = [0.1, 0.2, 0.8, 0.9]
        photo_bytes = Path(path).read_bytes()
        rows.append({
            "path": path,
            "status": "success",
            "reason": None,
            "detections": [{
                "crop_id": minifig_detector.stable_crop_id(photo_bytes, box),
                "box": box,
                "confidence": 0.88,
                "class": "minifigure",
            }],
        })
    return rows


def test_should_register_the_offline_detect_leaf():
    result = runner.invoke(app, ["minifig", "detect", "--help"])
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("payload, message", [
    ({}, "array"),
    ([{"listing_key": "source|1", "saved_photo_paths": []}], "exact keys"),
    ([{
        "listing_key": "source|1",
        "saved_photo_paths": [],
        "observations": {},
        "extra": True,
    }], "exact keys"),
    ([{
        "listing_key": "",
        "saved_photo_paths": [],
        "observations": {},
    }], "listing_key"),
    ([{
        "listing_key": "source|1",
        "saved_photo_paths": "photo.jpg",
        "observations": {},
    }], "saved_photo_paths"),
    ([{
        "listing_key": "source|1",
        "saved_photo_paths": ["https://example.com/photo.jpg"],
        "observations": {},
    }], "absolute local path"),
    ([{
        "listing_key": "source|1",
        "saved_photo_paths": [],
        "observations": [],
    }], "observations"),
])
def test_should_require_exact_detection_input_contract(
    payload,
    message,
    tmp_path,
):
    path = tmp_path / "input.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(_identification().DetectionInputError, match=message):
        _identification().load_detection_input(path)


def test_should_reject_duplicate_listing_keys(tmp_path):
    path = tmp_path / "input.json"
    path.write_text(json.dumps([_row([], "source|1"),
                                _row([], "source|1")]), encoding="utf-8")

    with pytest.raises(
        _identification().DetectionInputError,
        match="duplicate listing_key",
    ):
        _identification().load_detection_input(path)


def test_should_consume_every_saved_path_once_and_write_durable_crops(tmp_path):
    first = _save(tmp_path / "first.jpg", "JPEG")
    second = _save(tmp_path / "second.png", "PNG")
    third = _save(tmp_path / "third.jpg", "JPEG")
    listings = [
        _row([first, second], "source|1"),
        _row([third], "source|2", {"vision": {"photo_figure_count": 1}}),
    ]
    detector_calls = []

    def detector(name, paths):
        detector_calls.append((name, list(paths)))
        return _success_detector(name, paths)

    artifact = _identification().detect_batch(
        listings,
        detector_name="grounding-dino-tiny",
        crop_root=tmp_path / "crops",
        detector_fn=detector,
    )

    assert detector_calls == [(
        "grounding-dino-tiny",
        [str(first), str(second), str(third)],
    )]
    assert artifact["version"] == 1
    assert artifact["kind"] == "minifig_detection"
    assert artifact["detector"] == {
        "name": "grounding-dino-tiny",
        "contract_version": "v1",
    }
    assert [row["listing_key"] for row in artifact["listings"]] == [
        "source|1", "source|2"]
    assert artifact["listings"][1]["observations"] == {
        "vision": {"photo_figure_count": 1}}
    photos = [photo for listing in artifact["listings"]
              for photo in listing["photos"]]
    assert [row["photo_relative_id"] for row in photos] == [
        "photo-0001", "photo-0002", "photo-0001"]
    assert [row["source_photo_sha256"] for row in photos] == [
        hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (first, second, third)
    ]
    detections = [row["detections"][0] for row in photos]
    assert [Path(row["crop_ref"]).suffix for row in detections] == [
        ".jpg", ".png", ".jpg"]
    assert all(not Path(row["crop_ref"]).is_absolute() for row in detections)
    assert all((tmp_path / "crops" / row["crop_ref"]).is_file()
               for row in detections)
    assert all(row["source_photo_sha256"] == photos[index]["source_photo_sha256"]
               for index, row in enumerate(detections))
    assert all(row["photo_relative_id"] == photos[index]["photo_relative_id"]
               for index, row in enumerate(detections))
    assert all(row["detector_name"] == "grounding-dino-tiny"
               for row in detections)
    assert all(row["detector_version"] == "v1" for row in detections)
    assert all(row["detector_confidence"] == 0.88 for row in detections)
    dumped = json.dumps(artifact)
    assert str(first) not in dumped
    assert str(second) not in dumped
    assert str(third) not in dumped
    assert artifact["summary"] == {
        "listing_count": 2,
        "success_count": 2,
        "partial_count": 0,
        "skipped_count": 0,
        "photo_count": 3,
        "photo_success_count": 3,
        "photo_skipped_count": 0,
        "detection_count": 3,
    }


def test_should_preserve_empty_detection_as_success_and_isolate_bad_photo(tmp_path):
    good_empty = _save(tmp_path / "empty.jpg", "JPEG")
    bad = tmp_path / "missing.jpg"
    good = _save(tmp_path / "good.jpg", "JPEG")
    listings = [
        _row([good_empty, bad], "source|1"),
        _row([good], "source|2"),
    ]

    def detector(name, paths):
        successful = _success_detector(name, [paths[2]])[0]
        return [{
            "path": paths[0],
            "status": "success",
            "reason": None,
            "detections": [],
        }, {
            "path": paths[1],
            "status": "skipped",
            "reason": "FileNotFoundError: missing photo",
            "detections": [],
        }, successful]

    artifact = _identification().detect_batch(
        listings,
        detector_name="grounding-dino-tiny",
        crop_root=tmp_path / "crops",
        detector_fn=detector,
    )

    assert [row["status"] for row in artifact["listings"]] == [
        "partial", "success"]
    first_photos = artifact["listings"][0]["photos"]
    assert first_photos[0]["status"] == "success"
    assert first_photos[0]["detections"] == []
    assert first_photos[1]["status"] == "skipped"
    assert "missing photo" in first_photos[1]["reason"]
    assert artifact["summary"]["detection_count"] == 1
    assert artifact["summary"]["photo_skipped_count"] == 1


def test_should_isolate_crop_write_failure_to_its_photo(tmp_path):
    first = _save(tmp_path / "first.jpg", "JPEG")
    second = _save(tmp_path / "second.jpg", "JPEG")
    calls = []

    def writer(photo_path, detection, crop_root):
        calls.append(photo_path)
        if photo_path == str(first):
            raise OSError("disk refused crop")
        return "ab/figcrop-v1-second.jpg"

    artifact = _identification().detect_batch(
        [_row([first], "source|1"), _row([second], "source|2")],
        detector_name="grounding-dino-tiny",
        crop_root=tmp_path / "crops",
        detector_fn=_success_detector,
        crop_writer=writer,
    )

    assert calls == [str(first), str(second)]
    assert artifact["listings"][0]["status"] == "skipped"
    assert "disk refused crop" in artifact["listings"][0]["photos"][0]["reason"]
    assert artifact["listings"][1]["status"] == "success"
    assert artifact["summary"]["detection_count"] == 1


def test_should_write_empty_valid_array_and_loud_zero_summary(tmp_path):
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text("[]", encoding="utf-8")

    result = runner.invoke(app, [
        "minifig", "detect",
        "--input", str(input_path),
        "--output", str(output_path),
        "--crop-root", str(tmp_path / "crops"),
    ])

    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    summary = json.loads(result.stdout)
    assert summary == {
        "listing_count": 0,
        "success_count": 0,
        "partial_count": 0,
        "skipped_count": 0,
        "photo_count": 0,
        "photo_success_count": 0,
        "photo_skipped_count": 0,
        "detection_count": 0,
    }
    artifact = json.loads(output_path.read_text())
    assert artifact["listings"] == []
    assert artifact["summary"] == summary


@pytest.mark.parametrize("content, expected", [
    ("{bad", "invalid JSON"),
    ("{}", "array"),
    (json.dumps([_row([], "source|1"), _row([], "source|1")]),
     "duplicate listing_key"),
])
def test_should_fail_publicly_without_output_for_invalid_batches(
    content,
    expected,
    tmp_path,
):
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(content, encoding="utf-8")

    result = runner.invoke(app, [
        "minifig", "detect",
        "--input", str(input_path),
        "--output", str(output_path),
    ])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert expected in result.stderr
    assert not output_path.exists()


def test_should_fail_publicly_for_unreadable_input(tmp_path):
    input_path = tmp_path / "missing.json"
    output_path = tmp_path / "output.json"

    result = runner.invoke(app, [
        "minifig", "detect",
        "--input", str(input_path),
        "--output", str(output_path),
    ])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "unable to read input" in result.stderr
    assert not output_path.exists()


def test_should_reject_input_equal_to_output_without_truncation(tmp_path):
    path = tmp_path / "same.json"
    path.write_text("[]", encoding="utf-8")

    result = runner.invoke(app, [
        "minifig", "detect", "--input", str(path), "--output", str(path),
    ])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "different paths" in result.stderr
    assert path.read_text() == "[]"


def test_should_preserve_existing_output_when_atomic_promotion_fails(
    monkeypatch,
    tmp_path,
):
    identification = _identification()
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text("[]", encoding="utf-8")
    output_path.write_text('{"sentinel": true}\n', encoding="utf-8")

    def fail_replace(source, destination):
        raise OSError("promotion refused")

    monkeypatch.setattr(identification.os, "replace", fail_replace)
    result = runner.invoke(app, [
        "minifig", "detect",
        "--input", str(input_path),
        "--output", str(output_path),
    ])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "promotion refused" in result.stderr
    assert output_path.read_text() == '{"sentinel": true}\n'
    assert [path.name for path in tmp_path.iterdir()] == [
        "input.json", "output.json"]


def test_should_report_nine_command_groups_plus_triage():
    main_module = importlib.import_module("legoscout_cli.main")
    assert main_module.__doc__ is not None
    assert "Nine command groups plus `triage`" in main_module.__doc__


def _candidate(candidate_id, score):
    return {
        "id": candidate_id,
        "name": f"Figure {candidate_id}",
        "img_url": f"https://example.invalid/{candidate_id}.webp",
        "external_sites": [{
            "name": "bricklink",
            "url": f"https://www.bricklink.com/v2/catalog/catalogitem.page?M={candidate_id}",
        }],
        "category": "Theme / Subtheme",
        "type": "fig",
        "score": score,
    }


def _provider_response(items):
    from legoscout_cli.pricing import brickognize

    return {
        "contract": {
            "endpoint": brickognize.ENDPOINT,
            "contract_version": brickognize.CONTRACT_VERSION,
            "crop_sha256": "0" * 64,
            "top_k_items": 10,
            "min_similarity_items": .5,
        },
        "response": {
            "listing_id": "recorded-result",
            "bounding_box": {
                "left": 0.0,
                "upper": 0.0,
                "right": 100.0,
                "lower": 100.0,
                "image_width": 100.0,
                "image_height": 100.0,
                "score": .99,
            },
            "items": items,
        },
    }


def _detected(crop_id, crop_ref, confidence=.8, photo_id="photo-0001"):
    return {
        "crop_id": crop_id,
        "source_photo_sha256": "1" * 64,
        "photo_relative_id": photo_id,
        "box": [.1, .2, .8, .9],
        "detector_name": "grounding-dino-tiny",
        "detector_version": "v1",
        "detector_confidence": confidence,
        "crop_ref": crop_ref,
    }


def _detection_artifact(listings):
    rows = []
    detection_count = 0
    for key, detections in listings:
        detection_count += len(detections)
        rows.append({
            "listing_key": key,
            "observations": {"vision": {"photo_figure_count": len(detections)}},
            "status": "success",
            "reason": None,
            "photos": [{
                "photo_relative_id": "photo-0001",
                "source_photo_sha256": "1" * 64,
                "status": "success",
                "reason": None,
                "detections": detections,
            }] if detections else [],
        })
    return {
        "version": 1,
        "kind": "minifig_detection",
        "detector": {
            "name": "grounding-dino-tiny",
            "contract_version": "v1",
        },
        "listings": rows,
        "summary": {
            "listing_count": len(rows),
            "success_count": len(rows),
            "partial_count": 0,
            "skipped_count": 0,
            "photo_count": sum(bool(row["photos"]) for row in rows),
            "photo_success_count": sum(bool(row["photos"]) for row in rows),
            "photo_skipped_count": 0,
            "detection_count": detection_count,
        },
    }


def _prediction(path, items=None, cached=False, error=None):
    if error is not None:
        return {
            "path": str(path),
            "status": "skipped",
            "reason": error,
            "cached": False,
            "prediction": None,
        }
    return {
        "path": str(path),
        "status": "success",
        "reason": None,
        "cached": cached,
        "prediction": _provider_response(items if items is not None else []),
    }


def _write_crops(root, refs):
    for index, ref in enumerate(refs):
        path = root / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"crop-{index}".encode())


def test_should_register_the_offline_identify_leaf():
    result = runner.invoke(app, ["minifig", "identify", "--help"])
    assert result.exit_code == 0, result.output


def test_should_normalize_candidate_signature_and_handle_threshold_edges():
    identification = _identification()
    forward = [_candidate("sw0002", .7), _candidate("sw0001", .9)]
    reverse = list(reversed(forward))
    normalized_forward = identification.normalize_candidate_items(
        forward, min_similarity=.5)
    normalized_reverse = identification.normalize_candidate_items(
        reverse, min_similarity=.5)

    assert normalized_forward == normalized_reverse
    assert identification.candidate_signature(normalized_forward) == (
        identification.candidate_signature(normalized_reverse))
    edges = identification.normalize_candidate_items([
        _candidate("below", .49),
        _candidate("equal", .5),
        _candidate("above", .50001),
    ], min_similarity=.5)
    assert [row["id"] for row in edges] == ["above"]

    with pytest.raises(identification.IdentificationArtifactError,
                       match="duplicate candidate id"):
        identification.normalize_candidate_items([
            _candidate("same", .9), _candidate("same", .8),
        ], min_similarity=.5)
    missing = _candidate("missing", .9)
    del missing["id"]
    with pytest.raises(identification.IdentificationArtifactError,
                       match="candidate id"):
        identification.normalize_candidate_items(
            [missing], min_similarity=.5)


def test_should_group_signatures_choose_representative_and_emit_timings(tmp_path):
    root = tmp_path / "crops"
    refs = ["aa/a.jpg", "bb/b.jpg", "cc/c.jpg"]
    _write_crops(root, refs)
    detections = [
        _detected("figcrop-v1-a", refs[0], .8),
        _detected("figcrop-v1-b", refs[1], .9),
        _detected("figcrop-v1-c", refs[2], .7),
    ]
    artifact = _detection_artifact([("source|1", detections)])
    calls = []

    def predictor(paths, **kwargs):
        calls.append((list(paths), kwargs))
        return [
            _prediction(paths[0], [
                _candidate("sw0001", .9), _candidate("sw0002", .7)]),
            _prediction(paths[1], [
                _candidate("sw0002", .8), _candidate("sw0001", .95)], True),
            _prediction(paths[2], []),
        ]

    clock_values = iter([10.0, 12.0])
    output = _identification().identify_batch(
        artifact,
        crop_root=root,
        workers=2,
        top_k=10,
        min_similarity=.5,
        predictor=predictor,
        clock=lambda: next(clock_values),
    )

    expected_paths = [str(root / ref) for ref in refs]
    assert calls[0][0] == expected_paths
    assert calls[0][1]["workers"] == 2
    assert calls[0][1]["top_k"] == 10
    assert calls[0][1]["min_similarity"] == .5
    assert output["version"] == 1
    assert output["kind"] == "minifig_identification"
    groups = output["listings"][0]["groups"]
    assert len(groups) == 2
    grouped = next(row for row in groups if len(row["detections"]) == 2)
    empty = next(row for row in groups if len(row["detections"]) == 1)
    assert grouped["representative_crop_ref"] == refs[1]
    assert [row["id"] for row in grouped["brickognize_candidates"]] == [
        "sw0001", "sw0002"]
    assert empty["candidate_signature"] is None
    assert empty["brickognize_candidates"] == []
    assert empty["status"] == "success"
    assert output["summary"] == {
        "listing_count": 1,
        "success_count": 1,
        "partial_count": 0,
        "skipped_count": 0,
        "crop_count": 3,
        "group_count": 2,
        "provider_success_count": 3,
        "provider_skipped_count": 0,
        "cache_hit_count": 1,
    }
    assert output["timings"] == {
        "total_seconds": 2.0,
        "mean_per_crop_seconds": 0.666667,
    }
    assert output["request_contract"] == {
        "endpoint": "https://api.brickognize.com/predict/figs/",
        "contract_version": "brickognize-legacy-figs-v1",
        "top_k_items": 10,
        "min_similarity_items": .5,
    }
    dumped = json.dumps(output)
    assert str(root) not in dumped

    reversed_artifact = _detection_artifact([
        ("source|1", list(reversed(detections))),
    ])

    def reversed_predictor(paths, **kwargs):
        return [
            _prediction(paths[0], []),
            _prediction(paths[1], [
                _candidate("sw0002", .8), _candidate("sw0001", .95)]),
            _prediction(paths[2], [
                _candidate("sw0001", .9), _candidate("sw0002", .7)]),
        ]

    clock_values = iter([20.0, 22.0])
    reordered = _identification().identify_batch(
        reversed_artifact,
        crop_root=root,
        workers=2,
        top_k=10,
        min_similarity=.5,
        predictor=reversed_predictor,
        clock=lambda: next(clock_values),
    )
    reordered_group = next(
        row for row in reordered["listings"][0]["groups"]
        if len(row["detections"]) == 2)
    assert reordered_group["match_group_id"] == grouped["match_group_id"]
    assert reordered_group["representative_crop_ref"] == refs[1]


def test_should_break_representative_confidence_ties_by_crop_id(tmp_path):
    root = tmp_path / "crops"
    refs = ["bb/b.jpg", "aa/a.jpg"]
    _write_crops(root, refs)
    artifact = _detection_artifact([("source|1", [
        _detected("figcrop-v1-b", refs[0], .9),
        _detected("figcrop-v1-a", refs[1], .9),
    ])])

    def predictor(paths, **kwargs):
        items = [_candidate("sw0001", .9)]
        return [_prediction(path, items) for path in paths]

    output = _identification().identify_batch(
        artifact,
        crop_root=root,
        workers=2,
        top_k=10,
        min_similarity=.5,
        predictor=predictor,
    )

    assert output["listings"][0]["groups"][0][
        "representative_crop_ref"] == "aa/a.jpg"


def test_should_isolate_provider_failure_and_preserve_listing_order(tmp_path):
    root = tmp_path / "crops"
    refs = ["aa/a.jpg", "bb/b.jpg", "cc/c.jpg"]
    _write_crops(root, refs)
    artifact = _detection_artifact([
        ("source|1", [
            _detected("figcrop-v1-a", refs[0]),
            _detected("figcrop-v1-b", refs[1]),
        ]),
        ("source|2", [_detected("figcrop-v1-c", refs[2])]),
    ])

    def predictor(paths, **kwargs):
        return [
            _prediction(paths[0], [_candidate("sw0001", .9)]),
            _prediction(paths[1], error="HTTP 503"),
            _prediction(paths[2], [_candidate("sw0002", .8)]),
        ]

    output = _identification().identify_batch(
        artifact,
        crop_root=root,
        workers=2,
        top_k=10,
        min_similarity=.5,
        predictor=predictor,
    )

    assert [row["listing_key"] for row in output["listings"]] == [
        "source|1", "source|2"]
    assert [row["status"] for row in output["listings"]] == [
        "partial", "success"]
    failed = next(group for group in output["listings"][0]["groups"]
                  if group["status"] == "skipped")
    assert failed["reason"] == "HTTP 503"
    assert failed["brickognize_candidates"] == []
    assert output["summary"]["provider_success_count"] == 2
    assert output["summary"]["provider_skipped_count"] == 1


def test_should_keep_each_empty_provider_result_in_an_isolated_group(tmp_path):
    root = tmp_path / "crops"
    refs = ["aa/a.jpg", "bb/b.jpg"]
    _write_crops(root, refs)
    artifact = _detection_artifact([("source|1", [
        _detected("figcrop-v1-a", refs[0]),
        _detected("figcrop-v1-b", refs[1]),
    ])])

    output = _identification().identify_batch(
        artifact,
        crop_root=root,
        workers=2,
        top_k=10,
        min_similarity=.5,
        predictor=lambda paths, **kwargs: [
            _prediction(path, []) for path in paths],
    )

    groups = output["listings"][0]["groups"]
    assert len(groups) == 2
    assert len({group["match_group_id"] for group in groups}) == 2
    assert all(group["candidate_signature"] is None for group in groups)
    assert all(group["status"] == "success" for group in groups)


def test_should_write_empty_identification_and_loud_zero_timings(tmp_path):
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(json.dumps(_detection_artifact([])), encoding="utf-8")

    result = runner.invoke(app, [
        "minifig", "identify",
        "--input", str(input_path),
        "--output", str(output_path),
    ])

    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    public = json.loads(result.stdout)
    assert public == {
        "summary": {
            "listing_count": 0,
            "success_count": 0,
            "partial_count": 0,
            "skipped_count": 0,
            "crop_count": 0,
            "group_count": 0,
            "provider_success_count": 0,
            "provider_skipped_count": 0,
            "cache_hit_count": 0,
        },
        "timings": {
            "total_seconds": 0.0,
            "mean_per_crop_seconds": 0.0,
        },
    }
    artifact = json.loads(output_path.read_text())
    assert artifact["listings"] == []
    assert artifact["summary"] == public["summary"]
    assert artifact["timings"] == public["timings"]


@pytest.mark.parametrize("payload, expected", [
    ("{bad", "invalid JSON"),
    (json.dumps([]), "object"),
    (json.dumps({**_detection_artifact([]), "version": 2}), "version 1"),
    (json.dumps({**_detection_artifact([]), "kind": "wrong"}),
     "minifig_detection"),
    (json.dumps(_detection_artifact([
        ("source|1", []), ("source|1", []),
    ])), "duplicate listing_key"),
])
def test_should_fail_identify_publicly_without_output(
    payload,
    expected,
    tmp_path,
):
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(payload, encoding="utf-8")

    result = runner.invoke(app, [
        "minifig", "identify",
        "--input", str(input_path),
        "--output", str(output_path),
    ])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert expected in result.stderr
    assert not output_path.exists()


@pytest.mark.parametrize("args, expected", [
    (["--workers", "0"], "workers"),
    (["--workers", "-1"], "workers"),
    (["--workers", "3"], "workers"),
    (["--top-k", "0"], "top_k"),
    (["--top-k", "51"], "top_k"),
    (["--min-similarity", "-0.1"], "min_similarity"),
    (["--min-similarity", "1.1"], "min_similarity"),
])
def test_should_reject_identify_options_at_public_boundary(
    args,
    expected,
    tmp_path,
):
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(json.dumps(_detection_artifact([])), encoding="utf-8")

    result = runner.invoke(app, [
        "minifig", "identify",
        "--input", str(input_path),
        "--output", str(output_path),
        *args,
    ])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert expected in result.stderr
    assert not output_path.exists()


def test_should_fail_identify_publicly_for_unreadable_input(tmp_path):
    input_path = tmp_path / "missing.json"
    output_path = tmp_path / "output.json"

    result = runner.invoke(app, [
        "minifig", "identify",
        "--input", str(input_path),
        "--output", str(output_path),
    ])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "unable to read input" in result.stderr
    assert not output_path.exists()


def test_should_reject_unknown_minifig_stage():
    result = runner.invoke(app, ["minifig", "missing-stage"])
    assert result.exit_code == 2
    assert "No such command 'missing-stage'" in result.output


def test_should_reject_unknown_detector_at_detect_boundary(tmp_path):
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text("[]", encoding="utf-8")

    result = runner.invoke(app, [
        "minifig", "detect",
        "--input", str(input_path),
        "--output", str(output_path),
        "--detector", "missing-detector",
    ])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "unknown detector" in result.stderr
    assert not output_path.exists()


def test_should_reject_duplicate_crop_ids_and_traversal_refs(tmp_path):
    identification = _identification()
    duplicate = _detection_artifact([("source|1", [
        _detected("figcrop-v1-a", "aa/a.jpg"),
        _detected("figcrop-v1-a", "bb/b.jpg"),
    ])])
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps(duplicate), encoding="utf-8")
    with pytest.raises(identification.IdentificationArtifactError,
                       match="duplicate crop_id"):
        identification.load_identification_input(path)

    traversal = _detection_artifact([("source|1", [
        _detected("figcrop-v1-a", "../outside.jpg"),
    ])])
    path.write_text(json.dumps(traversal), encoding="utf-8")
    with pytest.raises(identification.IdentificationArtifactError,
                       match="crop_ref"):
        identification.load_identification_input(path)


def test_should_preserve_identify_input_and_existing_output_on_failures(
    monkeypatch,
    tmp_path,
):
    identification = _identification()
    same = tmp_path / "same.json"
    same.write_text(json.dumps(_detection_artifact([])), encoding="utf-8")
    before = same.read_text()

    result = runner.invoke(app, [
        "minifig", "identify", "--input", str(same), "--output", str(same),
    ])
    assert result.exit_code == 1
    assert "different paths" in result.stderr
    assert same.read_text() == before

    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(json.dumps(_detection_artifact([])), encoding="utf-8")
    output_path.write_text('{"sentinel": true}\n', encoding="utf-8")

    monkeypatch.setattr(
        identification.os,
        "replace",
        lambda source, destination: (_ for _ in ()).throw(
            OSError("identify promotion refused")),
    )
    result = runner.invoke(app, [
        "minifig", "identify",
        "--input", str(input_path),
        "--output", str(output_path),
    ])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "identify promotion refused" in result.stderr
    assert output_path.read_text() == '{"sentinel": true}\n'
