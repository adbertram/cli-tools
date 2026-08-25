from __future__ import annotations

import math
import sys
import tomllib
import types
from pathlib import Path

import pytest
from PIL import Image

from legoscout_cli.pricing import minifig_detector as detector


def _image(path: Path, fmt="JPEG", color="white") -> str:
    Image.new("RGB", (100, 100), color).save(path, format=fmt)
    return str(path)


def _row(path, boxes):
    return {"path": str(path), "detections": boxes}


def _box(box=(0.1, 0.1, 0.4, 0.7), confidence=0.9):
    return {"box": list(box), "confidence": confidence}


def _loader(return_rows=None, load_error=None, calls=None):
    def load():
        calls["loads"] += 1
        if load_error:
            raise load_error

        def detect_many(paths):
            calls["batches"].append(list(paths))
            return return_rows(paths) if callable(return_rows) else return_rows

        return detect_many
    return load


def _run(paths, rows, calls=None):
    calls = calls or {"loads": 0, "batches": []}
    return detector.detect_many(
        "fake", paths,
        loaders={"fake": _loader(rows, calls=calls)}), calls


def test_should_load_one_warm_detector_and_call_one_batch(tmp_path):
    paths = [_image(tmp_path / "a.jpg"), _image(tmp_path / "b.jpg")]
    calls = {"loads": 0, "batches": []}
    rows = lambda ps: [_row(p, [_box()]) for p in ps]
    out, calls = _run(paths, rows, calls)
    assert [r["status"] for r in out] == ["success", "success"]
    assert calls == {"loads": 1, "batches": [paths]}


def test_should_preserve_input_order_and_sort_boxes_deterministically(tmp_path):
    paths = [_image(tmp_path / "b.jpg"), _image(tmp_path / "a.jpg")]
    rows = [
        _row(paths[0], [_box((0.6, 0.2, 0.8, 0.8), .7),
                            _box((0.1, 0.1, 0.3, 0.6), .8)]),
        _row(paths[1], [_box()]),
    ]
    out, _ = _run(paths, rows)
    assert [r["path"] for r in out] == paths
    assert [d["box"] for d in out[0]["detections"]] == [
        [0.1, 0.1, 0.3, 0.6], [0.6, 0.2, 0.8, 0.8]]


def test_should_make_crop_id_from_bytes_box_and_contract_not_path(tmp_path):
    a = Path(_image(tmp_path / "a.jpg"))
    b = tmp_path / "nested" / "b.jpg"
    b.parent.mkdir()
    b.write_bytes(a.read_bytes())
    rows = lambda ps: [_row(p, [_box()]) for p in ps]
    out, _ = _run([str(a), str(b)], rows)
    assert out[0]["detections"][0]["crop_id"] == out[1]["detections"][0]["crop_id"]
    assert detector.DETECTOR_CONTRACT_VERSION in out[0]["detections"][0]["crop_id"]


def test_should_record_unknown_detector_for_every_input(tmp_path):
    paths = [_image(tmp_path / "a.jpg"), _image(tmp_path / "b.jpg")]
    out = detector.detect_many("missing", paths, loaders={})
    assert [r["status"] for r in out] == ["skipped", "skipped"]
    assert all("unknown detector" in r["reason"] for r in out)


def test_should_record_dependency_or_model_load_error_for_every_input(tmp_path):
    paths = [_image(tmp_path / "a.jpg"), _image(tmp_path / "b.jpg")]
    calls = {"loads": 0, "batches": []}
    out = detector.detect_many(
        "broken", paths,
        loaders={"broken": _loader(load_error=ImportError("weights absent"),
                                    calls=calls)})
    assert [r["status"] for r in out] == ["skipped", "skipped"]
    assert all("weights absent" in r["reason"] for r in out)
    assert calls == {"loads": 1, "batches": []}


def test_should_isolate_malformed_row_to_its_expected_image(tmp_path):
    paths = [_image(tmp_path / "a.jpg"), _image(tmp_path / "b.jpg")]
    out, _ = _run(paths, ["not-an-object", _row(paths[1], [_box()])])
    assert out[0]["status"] == "skipped"
    assert "object" in out[0]["reason"]
    assert out[1]["status"] == "success"


def test_should_key_non_list_backend_output_as_skips(tmp_path):
    paths = [_image(tmp_path / "a.jpg"), _image(tmp_path / "b.jpg")]
    out, _ = _run(paths, {"detections": []})
    assert [r["status"] for r in out] == ["skipped", "skipped"]
    assert all("list" in r["reason"] for r in out)


@pytest.mark.parametrize("bad, phrase", [
    ({"box": [0.1, 0.1, 0.4, 0.7], "confidence": float("nan")}, "finite"),
    ({"box": [0.1, 0.1, 0.4, 0.7], "confidence": float("inf")}, "finite"),
    ({"box": [0.1, 0.1, 0.4, 0.7], "confidence": -0.1}, "0..1"),
    ({"box": [0.1, 0.1, 0.4, 0.7], "confidence": 1.1}, "0..1"),
    ({"box": [-0.1, 0.1, 0.4, 0.7], "confidence": .5}, "0..1"),
    ({"box": [0.1, 0.1, 1.1, 0.7], "confidence": .5}, "0..1"),
    ({"box": [0.4, 0.1, 0.1, 0.7], "confidence": .5}, "inverted"),
    ({"box": [0.1, 0.1, 0.1, 0.7], "confidence": .5}, "zero-area"),
    ({"box": [0.1, 0.1, 0.4], "confidence": .5}, "four"),
    ("not-an-object", "object"),
])
def test_should_skip_only_image_with_malformed_detection(tmp_path, bad, phrase):
    paths = [_image(tmp_path / "bad.jpg"), _image(tmp_path / "good.jpg")]
    out, _ = _run(paths, [_row(paths[0], [bad]), _row(paths[1], [_box()])])
    assert out[0]["status"] == "skipped"
    assert phrase in out[0]["reason"]
    assert out[0]["detections"] == []
    assert out[1]["status"] == "success"


def _shift_for_iou(value):
    return (1.0 - value) / (1.0 + value)


def test_should_not_suppress_at_iou_06999(tmp_path):
    path = _image(tmp_path / "a.jpg")
    shift = _shift_for_iou(0.6999)
    rows = [_row(path, [_box((0, 0, 1, 1), .9),
                            _box((shift, 0, 1 + shift, 1), .8)])]
    # Normalize the second box into 0..1 while preserving the target IoU by
    # using a narrower first box.
    width = 0.8
    shift = width * _shift_for_iou(0.6999)
    rows = [_row(path, [_box((0, 0, width, 1), .9),
                            _box((shift, 0, width + shift, 1), .8)])]
    out, _ = _run([path], rows)
    assert len(out[0]["detections"]) == 2


def test_should_suppress_at_iou_070_and_keep_higher_confidence(tmp_path):
    path = _image(tmp_path / "a.jpg")
    width = 0.8
    shift = width * _shift_for_iou(0.70)
    rows = [_row(path, [_box((0, 0, width, 1), .4),
                            _box((shift, 0, width + shift, 1), .9)])]
    out, _ = _run([path], rows)
    assert len(out[0]["detections"]) == 1
    assert out[0]["detections"][0]["confidence"] == .9


def test_should_break_equal_confidence_overlap_tie_by_crop_id(tmp_path):
    path = _image(tmp_path / "a.jpg")
    width = 0.8
    shift = width * _shift_for_iou(0.70)
    rows = [_row(path, [_box((0, 0, width, 1), .8),
                            _box((shift, 0, width + shift, 1), .8)])]
    raw_ids = [detector.stable_crop_id(Path(path).read_bytes(), b["box"])
               for b in rows[0]["detections"]]
    out, _ = _run([path], rows)
    assert out[0]["detections"][0]["crop_id"] == min(raw_ids)


def test_should_ship_only_the_two_host_benchmark_winner():
    assert set(detector.DETECTOR_LOADERS) == {"grounding-dino-tiny"}
    assert detector.GROUNDING_DINO_MODEL == "IDEA-Research/grounding-dino-tiny"
    assert detector.GROUNDING_DINO_REVISION == (
        "a2bb814dd30d776dcf7e30523b00659f4f141c71")
    assert detector.GROUNDING_DINO_WEIGHTS_SHA256 == (
        "1a2412ef99bd74bcd3c2a246fa1e48581f8889a1300c9051974741314fc042f3")
    pyproject = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text())
    dependencies = pyproject["project"]["dependencies"]
    assert "transformers==5.15.1" in dependencies
    assert "torch==2.13.0" in dependencies
    assert not any("ultralytics" in value for value in dependencies)
    assert not any("opencv" in value for value in dependencies)


def test_should_call_the_pinned_grounding_dino_api_and_isolate_images(
    monkeypatch,
    tmp_path,
):
    calls = {}

    class Tensor:
        def __init__(self, value):
            self.value = value

        def tolist(self):
            return self.value

    class Inputs(dict):
        @property
        def input_ids(self):
            return self["input_ids"]

    class Processor:
        def __call__(self, **kwargs):
            calls["processor_call"] = kwargs
            return Inputs(input_ids=[1, 2, 3])

        def post_process_grounded_object_detection(self, outputs, **kwargs):
            calls["post"] = {"outputs": outputs, **kwargs}
            return [{
                "boxes": Tensor([[10.0, 20.0, 80.0, 90.0]]),
                "scores": Tensor([0.88]),
            }]

    processor = Processor()

    class AutoProcessor:
        @staticmethod
        def from_pretrained(model, revision):
            calls["processor_load"] = (model, revision)
            return processor

    class Model:
        def eval(self):
            calls["eval"] = True

        def __call__(self, **kwargs):
            calls["model_call"] = kwargs
            return "outputs"

    class AutoModel:
        @staticmethod
        def from_pretrained(model, revision):
            calls["model_load"] = (model, revision)
            return Model()

    class NoGrad:
        def __enter__(self):
            calls["no_grad"] = True

        def __exit__(self, exc_type, exc_value, traceback):
            return False

    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(
        no_grad=lambda: NoGrad()))
    monkeypatch.setitem(sys.modules, "transformers", types.SimpleNamespace(
        AutoModelForZeroShotObjectDetection=AutoModel,
        AutoProcessor=AutoProcessor,
    ))
    photo = _image(tmp_path / "photo.jpg", "JPEG")
    missing = tmp_path / "missing.jpg"

    backend = detector._load_grounding_dino_tiny()
    rows = backend([str(photo), str(missing)])

    expected_pin = (
        detector.GROUNDING_DINO_MODEL,
        detector.GROUNDING_DINO_REVISION,
    )
    assert calls["processor_load"] == expected_pin
    assert calls["model_load"] == expected_pin
    assert calls["eval"] is True
    assert calls["no_grad"] is True
    assert calls["processor_call"]["text"] == "lego minifigure."
    assert calls["post"]["threshold"] == 0.25
    assert calls["post"]["text_threshold"] == 0.25
    assert calls["post"]["target_sizes"] == [(100, 100)]
    assert rows[0] == {
        "path": str(photo),
        "detections": [{
            "box": [0.1, 0.2, 0.8, 0.9],
            "confidence": 0.88,
        }],
    }
    failure = rows[1]
    assert isinstance(failure, dict)
    assert failure["path"] == str(missing)
    assert failure["error"].startswith("FileNotFoundError:")


def test_should_write_deterministic_jpeg_and_png_crops_atomically(tmp_path):
    crop_root = tmp_path / "crops"
    outputs = []
    for suffix, fmt in (("jpg", "JPEG"), ("png", "PNG")):
        path = Path(_image(tmp_path / ("source." + suffix), fmt=fmt))
        det = detector.normalize_detections([_box()], path.read_bytes())[0]
        ref1 = detector.write_crop(str(path), det, str(crop_root))
        bytes1 = (crop_root / ref1).read_bytes()
        ref2 = detector.write_crop(str(path), det, str(crop_root))
        assert (crop_root / ref2).read_bytes() == bytes1
        assert not Path(ref1).is_absolute()
        outputs.append(ref1)
    assert outputs[0].endswith(".jpg")
    assert outputs[1].endswith(".png")


def test_should_not_promote_partial_crop_when_encoder_fails(tmp_path, monkeypatch):
    path = Path(_image(tmp_path / "source.jpg"))
    crop_root = tmp_path / "crops"
    det = detector.normalize_detections([_box()], path.read_bytes())[0]

    def broken_save(self, fp, *args, **kwargs):
        Path(fp).write_bytes(b"partial")
        raise OSError("disk write failed")

    monkeypatch.setattr(Image.Image, "save", broken_save)
    with pytest.raises(detector.CropWriteError, match="disk write failed"):
        detector.write_crop(str(path), det, str(crop_root))
    assert list(crop_root.rglob("*.*")) == []
