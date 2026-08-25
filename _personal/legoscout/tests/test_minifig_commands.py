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
